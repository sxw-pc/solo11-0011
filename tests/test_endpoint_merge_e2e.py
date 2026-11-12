"""端点归并端到端验收：统一端点、证据合并、旧基线、开关关闭与映射清单。"""
import hashlib, json, os
from pathlib import Path
from tablelink.incremental import compare, load_history
from tablelink.pipeline import run_pipeline
from tablelink.merge import build_plan, map_baseline, map_relationships
from tablelink.merge.rewrite import rewrite
from tablelink.loader import load_dataset
from tablelink.detector import detect_explicit, detect_fd, detect_overlap
from tablelink.detector.graph_common import merge_associations
from tests.conftest import ROOT, write_config
FOLDERS = ("source_a", "source_b", "source_c")
def _merge_config(tmp_path, default_config, enabled, baseline=""):
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = {
        "output.directory": str(tmp_path / "out"),
        "incremental.default_baseline": baseline,
        "merge.enabled": enabled,
    }
    config = write_config(tmp_path, default_config, **payload)
    import yaml
    path = Path(config)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["sources"]["csv_dirs"] = [
        str(ROOT / "fixtures" / "endpoint_merge" / folder) for folder in FOLDERS
    ]
    data["sources"]["sqlite_files"] = []
    data["explicit"]["custom_rules_path"] = ""
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return config
def _digest(directory, names):
    return {name: hashlib.sha256((Path(directory) / name).read_bytes()).hexdigest()
            for name in names}
def _detect(config, base_dir):
    dataset = load_dataset(config, base_dir)
    explicit = detect_explicit(dataset, config, base_dir)
    overlap = detect_overlap(dataset, config)
    functional = detect_fd(dataset, config, key_links=explicit + overlap)
    return dataset, merge_associations(explicit + overlap + functional)
def test_unified_endpoint_is_single_and_evidence_is_merged(tmp_path, default_config):
    config_path = _merge_config(tmp_path, default_config, True)
    result = run_pipeline(config_path=config_path, base_dir=str(ROOT),
                          use_default_baseline=False)
    payload = json.loads((tmp_path / "out" / "relations.json").read_text(encoding="utf-8"))
    assoc = payload["associations"]
    cluster = result.merge["clusters"]
    engineer = [item for item in cluster if item["unified_table"] == "engineer_info"][0]
    assert engineer["members"] == ["engineer_info", "engineer_info__csv", "info_engineer"]
    endpoints = {(item["source_table"], item["source_field"],
                  item["target_table"], item["target_field"]) for item in assoc}
    engineer_only = {endpoint for endpoint in endpoints if "engineer_info" in endpoint[:3:2]}
    sibling = {endpoint for endpoint in endpoints
               if any(member in endpoint[:3:2] for member in engineer["members"][1:])}
    assert not sibling, "归并后不应再出现原始后缀端点"
    rows = [item for item in assoc
            if item["source_table"] == "engineer_info"
            and item["target_table"] == "engineer_info"
            and item["source_field"] == "engineer_id"]
    assert len(rows) == 1, "同名表自关联应只剩一个统一端点"
    assert set(rows[0]["unified_from"]) >= {"engineer_info", "engineer_info__csv", "info_engineer"}
    assert rows[0]["evidence"], "证据应在归并后保留"
    assert len(rows[0]["detections"]) >= 2, "多来源检测明细应被合并而非覆盖"
    assert payload["endpoint_merge"]["stats"]["fallback_count"] == 0
    assert (tmp_path / "out" / "endpoint_map.json").is_file()
def test_old_baseline_aligns_after_merge(tmp_path, default_config):
    off = _merge_config(tmp_path / "off", default_config, False)
    run_pipeline(config_path=off, base_dir=str(ROOT), use_default_baseline=False)
    baseline = str(tmp_path / "off" / "out" / "relations.json")
    payload = json.loads(Path(baseline).read_text(encoding="utf-8"))
    assert any(item["source_table"] == "engineer_info__csv" for item in payload["associations"])
    on = _merge_config(tmp_path / "on", default_config, True)
    result = run_pipeline(config_path=on, base_dir=str(ROOT), baseline_path=baseline)
    summary = result.diff["summary"]
    assert summary == {"added": 0, "removed": 0,
                       "confidence_changed": 0, "unchanged": summary["unchanged"]}
    assert not result.diff["removed"]
def test_removed_only_when_really_gone(tmp_path, default_config):
    config = _merge_config(tmp_path, default_config, True)
    result = run_pipeline(config_path=config, base_dir=str(ROOT),
                          use_default_baseline=False)
    baseline = str(tmp_path / "out" / "relations.json")
    history = json.loads(Path(baseline).read_text(encoding="utf-8"))["associations"]
    history.append({"source_table": "legacy_device", "source_field": "device_id",
                    "target_table": "engineer_info", "target_field": "engineer_id",
                    "confidence": 0.6})
    path = tmp_path / "old.json"
    path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    rerun = run_pipeline(config_path=config, base_dir=str(ROOT), baseline_path=str(path))
    assert rerun.diff["summary"]["added"] == 0
    assert rerun.diff["summary"]["removed"] == 1
    assert rerun.diff["removed"][0]["source_table"] == "legacy_device"
def test_disabled_switch_byte_identical(tmp_path, default_config):
    config = _merge_config(tmp_path, default_config, False)
    run_pipeline(config_path=config, base_dir=str(ROOT), use_default_baseline=False)
    names = ("relations.json", "relations.yaml", "report.md", "graph.json", "graph.html")
    before = _digest(tmp_path / "out", names)
    run_pipeline(config_path=config, base_dir=str(ROOT), use_default_baseline=False)
    assert before == _digest(tmp_path / "out", names)
    payload = json.loads((tmp_path / "out" / "relations.json").read_text(encoding="utf-8"))
    assert "endpoint_merge" not in payload
    assert not (tmp_path / "out" / "endpoint_map.json").exists()
    assert [item["source_table"] for item in payload["associations"] if
            item["source_table"].startswith("engineer_info__")], "关开关时保留原始后缀端点"
def test_disabled_switch_matches_old_flow_on_default_data(tmp_path, default_config):
    """默认数据源上，关闭开关的产物应与未启用归并的旧流程一致。"""
    config = write_config(
        tmp_path, default_config,
        **{"output.directory": str(tmp_path / "out"),
           "incremental.default_baseline": ""},
    )
    result = run_pipeline(config_path=config, base_dir=str(ROOT),
                          use_default_baseline=False)
    assert result.merge is None
    payload = json.loads((tmp_path / "out" / "relations.json").read_text(encoding="utf-8"))
    assert payload["summary"]["association_count"] == len(result.associations)
    assert "endpoint_merge" not in payload
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "端点归并" not in report
def test_merge_is_byte_stable_and_mapping_explains_default(tmp_path, default_config):
    config = _merge_config(tmp_path, default_config, True)
    run_pipeline(config_path=config, base_dir=str(ROOT), use_default_baseline=False)
    names = ("relations.json", "relations.yaml", "report.md", "graph.json",
             "graph.html", "endpoint_map.json")
    before = _digest(tmp_path / "out", names)
    run_pipeline(config_path=config, base_dir=str(ROOT), use_default_baseline=False)
    assert before == _digest(tmp_path / "out", names)
    doc = json.loads((tmp_path / "out" / "endpoint_map.json").read_text(encoding="utf-8"))
    assert doc["strategy"]["identify"].startswith("ordered field-name set")
    for record in doc["endpoint_map"]:
        assert record["basis"]["normalized_name"]
        assert record["basis"]["field_set"]
        assert record["basis"]["inferred_primary_keys"]
        assert record["field_map"]
    merged = [item for item in doc["endpoint_map"]
              if item["original_table"] == "info_engineer"][0]
    assert merged["basis"]["value_guard"]["reason"] == "value_domain_verified"
    assert merged["unified_table"] == "engineer_info"
def test_merge_only_rewrites_in_memory_not_original():
    from tablelink.config import ConfigManager
    config = ConfigManager(str(ROOT / "config.yaml"), base_dir=str(ROOT)).load()
    config["merge"]["enabled"] = True
    dataset, current = _detect(config, str(ROOT))
    plan = build_plan(dataset, config)
    merged = map_relationships(current, plan)
    original_keys = {(item["source_table"], item["source_field"],
                      item["target_table"], item["target_field"]) for item in current}
    merged_keys = {(item["source_table"], item["source_field"],
                    item["target_table"], item["target_field"]) for item in merged}
    assert merged_keys <= original_keys
    assert merged == rewrite(current, plan)
