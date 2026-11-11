"""关联图构建、去重、增量和筛选测试。"""
from tablelink.detector import build_graph, filter_graph
from tablelink.detector.common import make_association
from tablelink.detector.graph_common import merge_associations
def _assoc(source, target, relation="value_overlap", confidence=0.8, source_name="s"):
    return make_association(source[0], source[1], target[0], target[1], relation,
                            confidence, source_name,
                            evidence=[{"source_value": source[1], "target_value": target[1]}])
def test_full_graph_has_nodes_edges_and_stats(default_dataset, explicit_associations,
                                             overlap_associations, fd_associations):
    graph = build_graph(default_dataset, explicit_associations + overlap_associations + fd_associations)
    assert graph["stats"]["table_count"] == len(default_dataset.tables)
    assert graph["stats"]["association_count"] == len(
        [edge for edge in graph["edges"] if not edge["structural"]])
    assert {node["node_type"] for node in graph["nodes"]} == {"table", "field"}
    structural = [edge for edge in graph["edges"] if edge["structural"]]
    assert structural and all(edge["relation_type"] == "contains" for edge in structural)
    assert len(structural) == graph["stats"]["field_count"]
    assert graph["stats"]["by_detection_source"]
def test_merge_keeps_best_confidence_sources_and_evidence():
    low = _assoc(("a", "x"), ("b", "y"), confidence=0.7, source_name="value_overlap")
    high = _assoc(("a", "x"), ("b", "y"), "custom", 0.95, "custom_rule")
    high["evidence"].append({"source_value": "new", "target_value": "new"})
    duplicate = _assoc(("a", "x"), ("b", "y"), "value_overlap", 0.7, "value_overlap")
    merged = merge_associations([low, high, duplicate])
    assert len(merged) == 1
    item = merged[0]
    assert item["confidence"] == 0.95 and item["relation_type"] == "custom"
    assert item["detection_sources"] == ["custom_rule", "value_overlap"]
    assert item["relation_types"] == ["custom", "value_overlap"]
    assert len(item["evidence"]) == 2 and len(item["detections"]) == 3
def test_graph_diff_added_changed_and_removed(default_dataset):
    keep = _assoc(("device_base", "device_id"), ("alarm_info", "device_id"))
    change = _assoc(("sensor_metric", "device_id"), ("device_base", "device_id"), confidence=0.9)
    current = [keep, change]
    diff = {
        "threshold": 0.05,
        "summary": {"added": 1, "removed": 1, "confidence_changed": 1, "unchanged": 0},
        "added": [dict(keep)],
        "removed": [_assoc(("ghost_a", "old_id"), ("ghost_b", "old_id"), confidence=0.6)],
        "confidence_changed": [dict(change, previous_confidence=0.8, confidence_delta=0.1)],
    }
    graph = build_graph(default_dataset, current, diff=diff)
    changes = {edge["change"] for edge in graph["edges"] if edge["change"]}
    assert changes == {"added", "removed", "confidence_changed"}
    ghost_nodes = [node for node in graph["nodes"] if node.get("ghost")]
    assert ghost_nodes and all(node["dtype"] == "unknown" for node in ghost_nodes
                               if node["node_type"] == "field")
    assert graph["stats"]["changes"] == {"added": 1, "removed": 1, "confidence_changed": 1}
def test_filter_confidence_type_table_and_changes(default_dataset):
    high = _assoc(("device_base", "device_id"), ("room_info", "room_id"), confidence=0.95)
    low = _assoc(("alarm_info", "device_id"), ("device_registry", "device_id"),
                 "explicit_fk", 0.8)
    graph = build_graph(default_dataset, [high, low], diff={
        "added": [high], "removed": [], "confidence_changed": [], "threshold": 0.05,
    })
    assert all(edge["confidence"] >= 0.9 for edge in
               filter_graph(graph, min_confidence=0.9)["edges"]
               if not edge["structural"])
    filtered = filter_graph(graph, relation_types=["explicit_fk"])
    assert filtered["stats"]["by_relation_type"] == {"explicit_fk": 1}
    assert not [n for n in filtered["nodes"] if n["node_type"] == "field"
                and n["table"] == "room_info"]
    assert filter_graph(graph, table="alarm")["edges"]
    assert filter_graph(filtered, relation_types=["explicit_fk"])["edges"]
    assert all(edge["change"] for edge in filter_graph(graph, only_changes=True)["edges"]
               if not edge["structural"])
    assert not filter_graph(graph, min_confidence=1.01)["nodes"]
