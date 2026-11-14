"""关联图构建入口：节点、结构边、去重合并与导出字典。"""
import networkx as nx
from .graph_common import (
    add_containment,
    add_field_node,
    add_table_node,
    annotate_diff,
    assoc_from_edge,
    edge_from_assoc,
    graph_stats,
    merge_associations,
)
def graph_to_dict(graph, associations=None):
    if associations is None:
        associations = [
            assoc_from_edge(edge) for _, _, edge in graph.edges(data=True)
            if not edge.get("structural")
        ]
    nodes = [dict(data) for _, data in graph.nodes(data=True)]
    nodes.sort(key=lambda item: (item["node_type"], item["id"]))
    edges = [dict(data) for _, _, data in graph.edges(data=True)]
    edges.sort(key=lambda item: (
        item.get("structural", False), -item.get("confidence", 0), item["id"]
    ))
    return {
        "schema_version": "1.1",
        "nodes": nodes,
        "edges": edges,
        "stats": graph_stats(graph, associations),
    }
def build_graph(dataset, associations, diff=None):
    """构建含表节点、字段节点和关联边的有向图，可选标注增量差异。"""
    merged = merge_associations(associations)
    graph = nx.DiGraph()
    for item in merged:
        source_node = add_field_node(
            graph, item["source_table"], item["source_field"],
            dataset.tables.get(item["source_table"]),
        )
        target_node = add_field_node(
            graph, item["target_table"], item["target_field"],
            dataset.tables.get(item["target_table"]),
        )
        add_table_node(graph, item["source_table"], dataset)
        add_table_node(graph, item["target_table"], dataset)
        graph.add_edge(source_node, target_node, **edge_from_assoc(item))
        add_containment(graph, item["source_table"], item["source_field"])
        add_containment(graph, item["target_table"], item["target_field"])
    for node_id in graph.nodes:
        graph.nodes[node_id]["degree"] = int(graph.degree(node_id))
    if diff:
        annotate_diff(graph, diff)
    return graph_to_dict(graph, merged)
