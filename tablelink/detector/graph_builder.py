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
def _resolver(dataset, merge_plan):
    """统一表名 → 代表表元数据；未归并表直接使用原表。"""
    if not merge_plan:
        return lambda name: dataset.tables.get(name)
    clusters = {item["name"]: item for item in merge_plan["clusters"]}
    def resolve(name):
        cluster = clusters.get(name)
        if cluster is not None:
            return cluster["representative"]
        return dataset.tables.get(name)
    return resolve
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
        "schema_version": "1.0",
        "nodes": nodes,
        "edges": edges,
        "stats": graph_stats(graph, associations),
    }
def build_graph(dataset, associations, diff=None, merge_plan=None):
    """构建含表节点、字段节点和关联边的有向图，可选标注增量差异。"""
    merged = merge_associations(associations)
    resolve = _resolver(dataset, merge_plan)
    graph = nx.DiGraph()
    for item in merged:
        source_node = add_field_node(
            graph, item["source_table"], item["source_field"],
            resolve(item["source_table"]),
        )
        target_node = add_field_node(
            graph, item["target_table"], item["target_field"],
            resolve(item["target_table"]),
        )
        add_table_node(graph, item["source_table"], dataset, table=resolve(item["source_table"]))
        add_table_node(graph, item["target_table"], dataset, table=resolve(item["target_table"]))
        edge = edge_from_assoc(item)
        if graph.has_edge(source_node, target_node):
            previous = graph.get_edge_data(source_node, target_node)
            if previous.get("confidence", 0) >= edge["confidence"]:
                continue
        graph.add_edge(source_node, target_node, **edge)
        add_containment(graph, item["source_table"], item["source_field"])
        add_containment(graph, item["target_table"], item["target_field"])
    for node_id in graph.nodes:
        graph.nodes[node_id]["degree"] = int(graph.degree(node_id))
    if diff:
        annotate_diff(graph, diff)
    return graph_to_dict(graph, merged)
