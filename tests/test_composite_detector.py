"""组合键关联检测：命中、剪枝降级、去重与旧基线兼容测试。"""
import copy
import pandas as pd
from tablelink.detector import build_graph, detect_composite
from tablelink.detector.common import make_association
from tablelink.detector.composite import FIELD_SEP
from tablelink.incremental import compare, load_history
from tablelink.reporter import build_markdown
from tests.conftest import make_dataset


def _composite_config(base, **updates):
    config = copy.deepcopy(base)
    config["composite"]["enabled"] = True
    for key, value in updates.items():
        config["composite"][key] = value
    return config


def _orders_logistics():
    # 单列各自大量重复且单列 Jaccard 不足，两列组合才精确对应
    orders = pd.DataFrame({
        "region_code": ["R1", "R2", "R3"] * 4,
        "doc_no": ["10"] * 3 + ["20"] * 3 + ["30"] * 3 + ["40"] * 3,
        "amount": range(12),
    })
    logistics = pd.DataFrame({
        "area_code": (["R1", "R2", "R3"] * 4)
        + (["R4", "R5", "R6"] * 2) + (["R7", "R8", "R9"] * 2),
        "waybill_no": (["10"] * 3 + ["20"] * 3 + ["30"] * 3 + ["40"] * 3)
        + (["50"] * 2 + ["60"] * 2 + ["70"] * 2)
        + (["80"] * 2 + ["90"] * 2 + ["55"] * 2),
        "carrier": ["sf"] * 24,
    })
    return {"orders": orders, "logistics": logistics}


def _first(result):
    assert len(result) == 1
    return result[0]


def test_disabled_by_default_returns_nothing(default_config, default_dataset):
    assert default_config["composite"]["enabled"] is False
    result, diagnostics = detect_composite(default_dataset, default_config)
    assert result == []
    assert diagnostics == {"degraded": False, "events": []}


def test_two_column_composite_hit(default_config):
    config = _composite_config(default_config)
    dataset = make_dataset(config, _orders_logistics())
    result, diagnostics = detect_composite(dataset, config)
    item = _first(result)
    assert item["source_table"] == "orders"
    assert item["source_field"] == "region_code,doc_no"
    assert item["target_table"] == "logistics"
    assert item["target_field"] == "area_code,waybill_no"
    assert item["relation_type"] == "composite_key"
    assert item["detection_sources"] == ["composite_detection"]
    assert item["confidence"] >= config["composite"]["threshold"]
    details = item["details"]
    assert details["composite"] is True
    assert details["source_fields"] == ["region_code", "doc_no"]
    assert details["target_fields"] == ["area_code", "waybill_no"]
    assert details["width"] == 2
    assert details["matched_tuples"] == 12
    assert details["coverage_ratio"] == 1.0
    assert len(item["evidence"]) == config["composite"]["evidence_limit"]
    sample = item["evidence"][0]
    assert sample["source_value"] == sample["target_value"]
    assert len(sample["source_value"]) == 2
    assert diagnostics["emitted_relations"] == 1
    assert diagnostics["degraded"] is False


def test_below_threshold_and_tuple_minimum(default_config):
    config = _composite_config(default_config, min_matched_tuples=30)
    dataset = make_dataset(config, _orders_logistics())
    result, _ = detect_composite(dataset, config)
    assert result == []
    config = _composite_config(default_config, threshold=0.99)
    dataset = make_dataset(config, _orders_logistics())
    result, _ = detect_composite(dataset, config)
    assert result == []


def test_unique_columns_are_pruned(default_config):
    config = _composite_config(default_config)
    frames = {
        "head": pd.DataFrame({
            "uid": range(20),
            "group": list("ab") * 10,
            "code": list("xy") * 10,
        }),
        "tail": pd.DataFrame({
            "uid": range(20),
            "segment": list("ab") * 10,
            "tag": list("xy") * 10,
        }),
    }
    dataset = make_dataset(config, frames)
    result, _ = detect_composite(dataset, config)
    for item in result:
        assert "uid" not in item["source_field"]
        assert "uid" not in item["target_field"]


def test_three_column_width_when_configured(default_config):
    config = _composite_config(default_config, max_width=3)
    frames = {
        "orders": pd.DataFrame({
            "region_code": ["R1", "R2", "R3"] * 3,
            "doc_no": ["10", "20", "30"] * 3,
            "batch": ["X", "Y", "Z"] * 3,
        }),
        "logistics": pd.DataFrame({
            "area_code": ["R1", "R2", "R3"] * 5,
            "waybill_no": ["10", "20", "30"] * 5,
            "lot_no": ["X", "Y", "Z"] * 5,
        }),
    }
    dataset = make_dataset(config, frames)
    result, _ = detect_composite(dataset, config)
    widths = {item["details"]["width"] for item in result}
    assert 3 in widths
    widest = max(result, key=lambda item: item["details"]["width"])
    assert widest["source_field"].count(FIELD_SEP) == 2
    # 默认 max_width=2 时不允许三列组合
    config_two = _composite_config(default_config)
    dataset_two = make_dataset(config_two, frames)
    result_two, _ = detect_composite(dataset_two, config_two)
    assert all(item["details"]["width"] == 2 for item in result_two)


def test_single_column_endpoint_not_duplicated(default_config):
    config = _composite_config(default_config)
    dataset = make_dataset(config, _orders_logistics())
    single = [
        make_association("orders", "region_code", "logistics", "area_code",
                         "value_overlap", 0.9, "value_overlap"),
        make_association("orders", "doc_no", "logistics", "waybill_no",
                         "value_overlap", 0.9, "value_overlap"),
    ]
    result, _ = detect_composite(dataset, config, single_associations=single)
    assert result == []
    # 仅覆盖一个成员列时，组合关系仍需输出
    partial = single[:1]
    result_partial, _ = detect_composite(
        dataset, config, single_associations=partial)
    assert len(result_partial) == 1


def test_degradation_caps_are_recorded(default_config):
    dataset = make_dataset(default_config, _orders_logistics())
    capped = {
        "max_evaluated_pairs": ("evaluated_pair_cap", 0),
        "max_candidate_groups": ("candidate_group_cap", 0),
        "max_eligible_columns": ("eligible_column_cap", 1),
        "max_table_rows": ("row_cap", 5),
    }
    for option, (reason, value) in capped.items():
        config = _composite_config(default_config, **{option: value})
        result, diagnostics = detect_composite(dataset, config)
        assert diagnostics["degraded"] is True
        assert any(event["reason"] == reason
                   for event in diagnostics["events"])
        assert result == []


def test_graph_ingests_composite_edge(default_config):
    config = _composite_config(default_config)
    dataset = make_dataset(config, _orders_logistics())
    result, _ = detect_composite(dataset, config)
    graph = build_graph(dataset, result)
    edges = [edge for edge in graph["edges"] if not edge.get("structural")]
    assert len(edges) == 1
    edge = edges[0]
    assert "composite_key" in edge["relation_types"]
    assert edge["source_field"] == "region_code,doc_no"
    assert graph["stats"]["by_relation_type"] == {"composite_key": 1}
    node_names = {node["name"] for node in graph["nodes"]
                  if node["node_type"] == "field"}
    assert "orders.region_code,doc_no" in node_names


def test_incremental_compare_with_legacy_baseline(default_config, tmp_path):
    config = _composite_config(default_config)
    dataset = make_dataset(config, _orders_logistics())
    result, _ = detect_composite(dataset, config)
    # 旧基线只有单列端点，格式与历史文件完全一致
    legacy = [{
        "source_table": "legacy_a", "source_field": "old_id",
        "target_table": "legacy_b", "target_field": "old_id",
        "confidence": 0.6, "relation_type": "custom",
    }]
    path = tmp_path / "history.json"
    import json
    path.write_text(json.dumps({"associations": legacy}), encoding="utf-8")
    history = load_history(str(path))
    diff = compare(result, history, threshold=0.05)
    assert diff["summary"]["added"] == 1
    assert diff["summary"]["removed"] == 1
    added = diff["added"][0]
    assert added["relation_type"] == "composite_key"
    assert FIELD_SEP in added["source_field"]
    assert diff["removed"][0]["source_table"] == "legacy_a"


def test_deterministic_ordering(default_config):
    config = _composite_config(default_config, max_width=3)
    frames = {
        "orders": pd.DataFrame({
            "region_code": ["R1", "R2", "R3"] * 3,
            "doc_no": ["10", "20", "30"] * 3,
            "batch": ["X", "Y", "Z"] * 3,
        }),
        "logistics": pd.DataFrame({
            "area_code": ["R1", "R2", "R3"] * 5,
            "waybill_no": ["10", "20", "30"] * 5,
            "lot_no": ["X", "Y", "Z"] * 5,
        }),
    }
    dataset = make_dataset(config, frames)
    first, _ = detect_composite(dataset, config)
    second, _ = detect_composite(dataset, config)
    keys = [(i["source_table"], i["source_field"],
             i["target_table"], i["target_field"]) for i in first]
    second_keys = [(i["source_table"], i["source_field"],
                    i["target_table"], i["target_field"]) for i in second]
    assert keys == second_keys
    # sort_associations 的确定性次序：置信度降序，端点升序兜底
    ordered = sorted(
        first,
        key=lambda item: (-item["confidence"], item["source_table"],
                          item["source_field"], item["target_table"],
                          item["target_field"]),
    )
    assert [item["id"] for item in first] == [item["id"] for item in ordered]


def test_report_shows_composite_and_degradation(default_config):
    config = _composite_config(default_config, max_eligible_columns=1)
    dataset = make_dataset(config, _orders_logistics())
    result, diagnostics = detect_composite(dataset, config)
    assert diagnostics["degraded"] is True
    graph = build_graph(dataset, result)
    text = build_markdown(dataset, result, graph, config,
                          composite_diagnostics=diagnostics)
    assert "## 6. 组合键关联清单" in text
    assert "降级提示" in text and "eligible_column_cap" in text
    assert "## 10. 审计说明" in text
    # 启用且有命中时，表格与度量列出现
    ok_config = _composite_config(default_config)
    ok_dataset = make_dataset(ok_config, _orders_logistics())
    ok_result, ok_diag = detect_composite(ok_dataset, ok_config)
    ok_graph = build_graph(ok_dataset, ok_result)
    ok_text = build_markdown(ok_dataset, ok_result, ok_graph, ok_config,
                             composite_diagnostics=ok_diag)
    assert "组合端点" in ok_text and "交集元组" in ok_text
    assert "region_code,doc_no" in ok_text


def test_report_keeps_legacy_sections_when_disabled(default_config):
    config = copy.deepcopy(default_config)
    assert config["composite"]["enabled"] is False
    dataset = make_dataset(config, _orders_logistics())
    graph = build_graph(dataset, [])
    text = build_markdown(dataset, [], graph, config)
    assert "组合键" not in text
    assert "## 6. 函数依赖清单" in text
    assert "## 7. 增量版本对比" in text
    assert "## 8. 审计说明" in text


def test_disabled_mode_emits_no_composite_artifacts(default_config):
    """兼容性契约：默认关闭时，规则文档与报告均不出现复合键痕迹。"""
    from tablelink.reporter import build_markdown, build_rules_payload
    config = copy.deepcopy(default_config)
    assert config["composite"]["enabled"] is False
    dataset = make_dataset(config, _orders_logistics())
    payload = build_rules_payload(dataset, [], config)
    assert "composite_diagnostics" not in payload
    assert all(a["relation_type"] != "composite_key"
               for a in payload["associations"])
    graph = build_graph(dataset, [])
    text = build_markdown(dataset, [], graph, config)
    assert "composite" not in text and "组合" not in text
