"""图构建共用件：节点标识、关联合并、差异标注与统计。"""
import hashlib
import json
from collections import Counter
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
    """规范化单条检测明细；关联字典与既有检测记录均可作为输入。"""
    return {
        "relation_type": item.get("relation_type", "unknown"),
        "source": item.get("source") or (item.get("detection_sources") or ["unknown"])[0],
        "confidence": round(float(item.get("confidence", 0)), 4),
        "details": dict(item.get("details", {})),
        "evidence": list(item.get("evidence") or []),
    }
def _source_groups(detections):
    """按检测来源分组证据；零证据来源不计入来源集合。"""
    grouped = {}
    for det in detections:
        grouped.setdefault(det["source"], []).append(det)
    result = []
    for source in sorted(grouped):
        dets = grouped[source]
        evidence = []
        for det in dets:
            evidence = _merge_evidence(evidence, det.get("evidence") or [])
        if not evidence:
            continue
        best = max(dets, key=lambda det: (
            det["confidence"], RELATION_PRIORITY.get(det["relation_type"], 0)))
        result.append({
            "source": source,
            "relation_types": sorted({det["relation_type"] for det in dets},
                                     key=lambda name: (-RELATION_PRIORITY.get(name, 0), name)),
            "confidence": best["confidence"],
            "evidence": evidence, "details": dict(best["details"]),
        })
    return result
def merge_associations(associations):
    """按字段端点合并重复关联，保留最高置信度与全部来源/证据。可重复调用。"""
    merged = {}
    for item in associations:
        key = association_key(item)
        detections = [_detection(entry) for entry in item.get("detections") or []]
        if not detections:
            detections = [_detection(item)]
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
                "details": dict(item.get("details") or {}),
                "detections": detections,
                "change": item.get("change"),
                "change_delta": item.get("change_delta"),
            }
            continue
        current = merged[key]
        current["detections"].extend(detections)
        for source in item.get("detection_sources") or []:
            if source not in current["detection_sources"]:
                current["detection_sources"].append(source)
        for relation in item.get("relation_types") or []:
            if relation not in current["relation_types"]:
                current["relation_types"].append(relation)
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
        item["detections"].sort(
            key=lambda det: (-det["confidence"], -RELATION_PRIORITY.get(det["relation_type"], 0))
        )
        item["detection_sources"] = sorted(
            set(item["detection_sources"]) | {det["source"] for det in item["detections"]}
        )
        item["relation_types"] = sorted(
            set(item["relation_types"]) | {det["relation_type"] for det in item["detections"]},
            key=lambda name: (-RELATION_PRIORITY.get(name, 0), name),
        )
        evidence = []
        for det in item["detections"]:
            evidence = _merge_evidence(evidence, det["evidence"])
        item["evidence"] = evidence
        item["source_groups"] = _source_groups(item["detections"])
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
def add_table_node(graph, table_name, dataset, ghost=False):
    node_id = table_node_id(table_name)
    if graph.has_node(node_id):
        return node_id
    table = dataset.tables.get(table_name) if dataset else None
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
        "detections": [],
        "source_groups": [],
        "structural": True,
        "change": None,
    })
def _relation_edge(item, edge_id):
    """由关联记录生成非结构边字典，构建与增量标注共用。"""
    return {
        "id": edge_id,
        "source": field_node_id(item["source_table"], item["source_field"]),
        "target": field_node_id(item["target_table"], item["target_field"]),
        "source_table": item["source_table"],
        "source_field": item["source_field"],
        "target_table": item["target_table"],
        "target_field": item["target_field"],
        "relation_type": item.get("relation_type", "unknown"),
        "relation_types": list(item.get("relation_types") or []),
        "detection_sources": list(item.get("detection_sources") or []),
        "confidence": item["confidence"],
        "evidence": list(item.get("evidence") or []),
        "details": dict(item.get("details") or {}),
        "detections": list(item.get("detections") or []),
        "source_groups": list(item.get("source_groups") or []),
        "structural": False,
        "change": item.get("change"),
        "change_delta": item.get("change_delta"),
    }
def _edge_digest(item, prefix):
    return prefix + hashlib.sha1(
        json.dumps(association_key(item)).encode("utf-8")
    ).hexdigest()[:12]
def edge_from_assoc(item):
    return _relation_edge(item, item.get("id") or _edge_digest(item, "rel_"))
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
    by_relation = Counter(item["relation_type"] for item in associations)
    by_source = Counter(
        source for item in associations for source in item.get("detection_sources", [])
    )
    changes = {"added": 0, "removed": 0, "confidence_changed": 0}
    for _, _, edge in graph.edges(data=True):
        if not edge.get("structural") and edge.get("change") in changes:
            changes[edge["change"]] += 1
    node_types = Counter(data["node_type"] for _, data in graph.nodes(data=True))
    return {
        "table_count": node_types["table"],
        "field_count": node_types["field"],
        "association_count": len(associations),
        "structural_edge_count": sum(
            1 for _, _, d in graph.edges(data=True) if d.get("structural")),
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
        edge = _relation_edge(item, item.get("id") or _edge_digest(item, "removed_"))
        edge["relation_type"] = item.get("relation_type", "historical")
        edge["relation_types"] = item.get("relation_types", ["historical"])
        edge["detection_sources"] = item.get("detection_sources", ["history"])
        edge["change"] = "removed"
        graph.add_edge(edge["source"], edge["target"], **edge)
    enrich_degrees(graph)
    return graph
