"""关联图条件筛选，自动移除筛选后孤立的表节点。"""
import networkx as nx
from .graph_builder import graph_to_dict
from .graph_common import add_containment, assoc_from_edge, enrich_degrees, table_node_id
def _as_networkx(graph):
    if isinstance(graph, nx.DiGraph):
        return graph
    result = nx.DiGraph()
    for node in graph.get("nodes", []):
        result.add_node(node["id"], **dict(node))
    for edge in graph.get("edges", []):
        result.add_edge(edge["source"], edge["target"], **dict(edge))
    return result
def filter_graph(graph, relation_types=None, min_confidence=0.0,
                 max_confidence=1.0, table=None, only_changes=False):
    """按关系类型、置信度、表名筛选，并过滤筛选后孤立节点。"""
    graph = _as_networkx(graph)
    allowed = set(relation_types) if relation_types else None
    table_key = (table or "").strip().lower()
    kept = []
    for _, _, edge in graph.edges(data=True):
        if edge.get("structural"):
            continue
        if only_changes and not edge.get("change"):
            continue
        if not only_changes and edge.get("change") == "removed":
            continue
        if allowed and not (set(edge.get("relation_types", [])) & allowed):
            continue
        if not min_confidence <= edge.get("confidence", 0) <= max_confidence:
            continue
        if table_key and table_key not in edge["source_table"].lower() and \
                table_key not in edge["target_table"].lower():
            continue
        kept.append(edge)
    sub = nx.DiGraph()
    for edge in kept:
        sub.add_node(edge["source"], **dict(graph.nodes[edge["source"]]))
        sub.add_node(edge["target"], **dict(graph.nodes[edge["target"]]))
        for table_name in (edge["source_table"], edge["target_table"]):
            node_id = table_node_id(table_name)
            if graph.has_node(node_id):
                sub.add_node(node_id, **dict(graph.nodes[node_id]))
        sub.add_edge(edge["source"], edge["target"], **dict(edge))
    for node_id in [n for n, data in list(sub.nodes(data=True))
                    if data["node_type"] == "table"]:
        table_name = sub.nodes[node_id]["table"]
        members = [n for n, data in sub.nodes(data=True)
                   if data["node_type"] == "field" and data["table"] == table_name]
        if not members:
            sub.remove_node(node_id)
            continue
        for member in members:
            add_containment(sub, table_name, sub.nodes[member]["field"])
    enrich_degrees(sub)
    associations = [assoc_from_edge(edge) for edge in kept]
    return graph_to_dict(sub, associations)
