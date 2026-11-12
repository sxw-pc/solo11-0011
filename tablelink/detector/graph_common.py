"""图构建共用件：节点标识、关联合并、差异标注与统计。"""
import hashlib
import json
from .common import RELATION_PRIORITY, association_key
def field_node_id(table, field):
    return "field:{0}.{1}".format(table, field)
def table_node_id(table):
    return "table:{0}".format(table)
def containment_id(table, field):
    digest = hashlib.sha1("{0}.{1}".format(table, field).encode("utf-8")).hexdigest()[:10]
    return "contains_" + digest
def _merge_evidence(existing, incoming, limit=8):
    merged = list(existing)
    seen = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in merged}
    for item in incoming:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            merged.append(item)
            seen.add(key)
        if len(merged) >= limit:
            break
    return merged
def _detection(item):
    return {
        "relation_type": item.get("relation_type", "unknown"),
        "source": (item.get("detection_sources") or ["unknown"])[0],
        "confidence": round(float(item.get("confidence", 0)), 4),
        "details": dict(item.get("details", {})),
    }
def merge_associations(associations):
    """按字段端点合并重复关联，保留最高置信度与全部来源/证据。"""
    merged = {}
    for item in associations:
        key = association_key(item)
        if key not in merged:
            merged[key] = {
                "id": item.get("id") or "",
                "source_table": item["source_table"],
                "source_field": item["source_field"],
                "target_table": item["target_table"],
                "target_field": item["target_field"],
                "confidence": round(float(item.get("confidence", 0)), 4),
                "relation_type": item.get("relation_type", "unknown"),
                "relation_types": list(item.get("relation_types") or []),
                "detection_sources": list(item.get("detection_sources") or []),
                "evidence": list(item.get("evidence") or []),
                "details": dict(item.get("details") or {}),
                "detections": [_detection(item)],
                "change": item.get("change"),
                "change_delta": item.get("change_delta"),
            }
            continue
        current = merged[key]
        current["detections"].append(_detection(item))
        for source in item.get("detection_sources") or []:
            if source not in current["detection_sources"]:
                current["detection_sources"].append(source)
        for relation in item.get("relation_types") or []:
            if relation not in current["relation_types"]:
                current["relation_types"].append(relation)
        current["evidence"] = _merge_evidence(
            current["evidence"], item.get("evidence") or []
        )
        if item.get("change") and not current.get("change"):
            current["change"] = item["change"]
            current["change_delta"] = item.get("change_delta")
        candidate_confidence = round(float(item.get("confidence", 0)), 4)
        candidate_type = item.get("relation_type", "unknown")
        if (candidate_confidence, RELATION_PRIORITY.get(candidate_type, 0)) > (
                current["confidence"], RELATION_PRIORITY.get(current["relation_type"], 0)):
            current["confidence"] = candidate_confidence
            current["relation_type"] = candidate_type
            current["details"] = dict(item.get("details") or {})
            current["id"] = item.get("id") or current["id"]
    result = list(merged.values())
    for item in result:
        item["relation_types"].sort(key=lambda name: (-RELATION_PRIORITY.get(name, 0), name))
        item["detections"].sort(
            key=lambda det: (-det["confidence"], -RELATION_PRIORITY.get(det["relation_type"], 0))
        )
        item["detection_sources"].sort()
    return sorted(result, key=lambda item: (
        -item["confidence"], item["source_table"], item["source_field"],
        item["target_table"], item["target_field"],
    ))
def add_field_node(graph, table_name, field_name, table, ghost=False):
    node_id = field_node_id(table_name, field_name)
    if graph.has_node(node_id):
        return node_id
    column = table.column(field_name) if table else None
    graph.add_node(node_id, **{
        "id": node_id,
        "name": "{0}.{1}".format(table_name, field_name),
        "node_type": "field",
        "table": table_name,
        "field": field_name,
        "category": 1,
        "dtype": column["dtype"] if column else "unknown",
        "cardinality": column["cardinality"] if column else 0,
        "non_null_ratio": column["non_null_ratio"] if column else 0.0,
        "ghost": ghost,
    })
    return node_id
def add_table_node(graph, table_name, dataset, ghost=False, table=None):
    node_id = table_node_id(table_name)
    if graph.has_node(node_id):
        return node_id
    table = table if table is not None else (dataset.tables.get(table_name) if dataset else None)
    graph.add_node(node_id, **{
        "id": node_id,
        "name": table_name,
        "node_type": "table",
        "table": table_name,
        "field": None,
        "category": 0,
        "row_count": table.row_count if table else 0,
        "column_count": len(table.columns) if table else 0,
        "ghost": ghost,
    })
    return node_id
def add_containment(graph, table_name, field_name):
    table_node = table_node_id(table_name)
    field_node = field_node_id(table_name, field_name)
    graph.add_edge(table_node, field_node, **{
        "id": containment_id(table_name, field_name),
        "source": table_node,
        "target": field_node,
        "source_table": table_name,
        "source_field": None,
        "target_table": table_name,
        "target_field": field_name,
        "relation_type": "contains",
        "relation_types": ["contains"],
        "detection_sources": ["schema"],
        "confidence": 1.0,
        "evidence": [],
        "details": {},
        "structural": True,
        "change": None,
    })
def edge_from_assoc(item):
    source_node = field_node_id(item["source_table"], item["source_field"])
    target_node = field_node_id(item["target_table"], item["target_field"])
    return {
        "id": item.get("id") or "rel_" + hashlib.sha1(
            json.dumps(association_key(item)).encode("utf-8")
        ).hexdigest()[:12],
        "source": source_node,
        "target": target_node,
        "source_table": item["source_table"],
        "source_field": item["source_field"],
        "target_table": item["target_table"],
        "target_field": item["target_field"],
        "relation_type": item["relation_type"],
        "relation_types": list(item["relation_types"]),
        "detection_sources": list(item["detection_sources"]),
        "confidence": item["confidence"],
        "evidence": list(item["evidence"]),
        "details": dict(item["details"]),
        "detections": list(item.get("detections", [])),
        "structural": False,
        "change": item.get("change"),
        "change_delta": item.get("change_delta"),
    }
def assoc_from_edge(edge):
    return {
        "source_table": edge["source_table"],
        "source_field": edge["source_field"],
        "target_table": edge["target_table"],
        "target_field": edge["target_field"],
        "confidence": edge["confidence"],
        "relation_type": edge.get("relation_type", "unknown"),
        "detection_sources": list(edge.get("detection_sources", [])),
    }
def enrich_degrees(graph, dataset=None):
    for node_id in graph.nodes:
        node = graph.nodes[node_id]
        node["degree"] = int(graph.degree(node_id))
        if node["node_type"] == "field" and dataset and node.get("dtype") == "unknown":
            table = dataset.tables.get(node["table"])
            column = table.column(node["field"]) if table else None
            if column:
                node["dtype"] = column["dtype"]
                node["cardinality"] = column["cardinality"]
                node["non_null_ratio"] = column["non_null_ratio"]
def graph_stats(graph, associations):
    by_relation = {}
    by_source = {}
    for item in associations:
        by_relation[item["relation_type"]] = by_relation.get(item["relation_type"], 0) + 1
        for source in item.get("detection_sources", []):
            by_source[source] = by_source.get(source, 0) + 1
    changes = {"added": 0, "removed": 0, "confidence_changed": 0}
    for _, _, edge in graph.edges(data=True):
        if edge.get("structural"):
            continue
        if edge.get("change") in changes:
            changes[edge["change"]] += 1
    return {
        "table_count": len([n for n, d in graph.nodes(data=True) if d["node_type"] == "table"]),
        "field_count": len([n for n, d in graph.nodes(data=True) if d["node_type"] == "field"]),
        "association_count": len(associations),
        "structural_edge_count": len([
            1 for _, _, d in graph.edges(data=True) if d.get("structural")
        ]),
        "by_relation_type": dict(sorted(by_relation.items())),
        "by_detection_source": dict(sorted(by_source.items())),
        "changes": changes,
    }
def annotate_diff(graph, diff):
    """把新增/失效/置信度变化标记到图；失效项以 ghost 边保留。"""
    if not diff:
        return graph
    current = {}
    for _, _, edge in graph.edges(data=True):
        if not edge.get("structural"):
            current[(edge["source_table"], edge["source_field"],
                     edge["target_table"], edge["target_field"])] = edge
    for item in diff.get("added", []):
        edge = current.get((item["source_table"], item["source_field"],
                            item["target_table"], item["target_field"]))
        if edge:
            edge["change"] = "added"
    for item in diff.get("confidence_changed", []):
        edge = current.get((item["source_table"], item["source_field"],
                            item["target_table"], item["target_field"]))
        if edge:
            edge["change"] = "confidence_changed"
            edge["change_delta"] = round(item["confidence"] - item["previous_confidence"], 4)
    for item in diff.get("removed", []):
        source_table = item["source_table"]
        target_table = item["target_table"]
        add_field_node(graph, source_table, item["source_field"], None, ghost=True)
        add_field_node(graph, target_table, item["target_field"], None, ghost=True)
        add_table_node(graph, source_table, None, ghost=True)
        add_table_node(graph, target_table, None, ghost=True)
        edge = {
            "id": item.get("id") or "removed_" + hashlib.sha1(
                json.dumps(association_key(item)).encode("utf-8")
            ).hexdigest()[:12],
            "source": field_node_id(source_table, item["source_field"]),
            "target": field_node_id(target_table, item["target_field"]),
            "source_table": source_table,
            "source_field": item["source_field"],
            "target_table": target_table,
            "target_field": item["target_field"],
            "relation_type": item.get("relation_type", "historical"),
            "relation_types": item.get("relation_types", ["historical"]),
            "detection_sources": item.get("detection_sources", ["history"]),
            "confidence": item["confidence"],
            "evidence": item.get("evidence", []),
            "details": item.get("details", {}),
            "detections": item.get("detections", []),
            "structural": False,
            "change": "removed",
            "change_delta": None,
        }
        graph.add_edge(edge["source"], edge["target"], **edge)
    enrich_degrees(graph)
    return graph
