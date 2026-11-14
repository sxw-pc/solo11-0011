"""跨来源规范化：救援命中、降级、缓存、优先级、配置校验与产物可复现测试。"""
import copy, hashlib, json
from pathlib import Path
import pandas as pd
import pytest, yaml
from tablelink.config import DEFAULT_CONFIG, validate_config
from tablelink.detector import detect_overlap
from tablelink.detector.common import make_association
from tablelink.detector.graph_common import merge_associations
from tablelink.detector.value_normalizer import apply_chain, detect_chains
from tablelink.exceptions import ConfigError
from tablelink.pipeline import run_pipeline
from tests.conftest import ROOT, make_dataset, write_config
def _enabled(default_config):
    config = copy.deepcopy(default_config)
    config["overlap"]["normalization"]["enabled"] = True
    return config
def _pair(result, source, source_field, target, target_field):
    return [item for item in result if {
        item["source_table"], item["source_field"], item["target_table"], item["target_field"],
    } == {source, source_field, target, target_field}]
def _phone_frames():
    numbers = ["1381234000{0}".format(i) for i in range(8)]
    dashed = ["{0}-{1}-{2}".format(n[:3], n[3:7], n[7:]) for n in numbers] * 2
    spaced = ["{0} {1} {2}".format(n[:3], n[3:7], n[7:]) for n in numbers] * 2
    return (
        pd.DataFrame({"user_id": ["U{0}".format(i) for i in range(16)], "contact_phone": dashed}),
        pd.DataFrame({"order_id": ["O{0}".format(i) for i in range(16)], "phone": spaced}),
    )
def test_normalizer_primitives(default_config):
    norm = default_config["overlap"]["normalization"]
    assert apply_chain("case_fold", "AbC") == "abc"
    assert apply_chain("strip_delimiters", "138-1234-5678") == "13812345678"
    assert apply_chain("strip_delimiters", "+86 138 1234 5678") == "13812345678"
    assert apply_chain("case_fold+strip_delimiters", "AB-CD") == "abcd"
    assert apply_chain("numeric_unit", "¥1,234.50") == "1234.5"
    assert apply_chain("numeric_unit", "1.5万") == "15000"
    assert apply_chain("date_unify", "2024/1/5") == "2024-01-05"
    assert apply_chain("date_unify", "2024年1月5日") == "2024-01-05"
    assert apply_chain("date_unify", "2023-02-30") is None
    assert apply_chain("strip_delimiters", "乱码★-//") is None
    values = ["138-1234-000{0}".format(i) for i in range(8)]
    assert detect_chains("contact_phone", values, norm) == ["strip_delimiters"]
    assert detect_chains("event_date", ["2024/1/{0}".format(i) for i in range(1, 9)], norm) == ["date_unify"]
def test_phone_formats_rescued_with_chain_evidence(default_config):
    users, orders = _phone_frames()
    dataset = make_dataset(default_config, {"users": users, "orders": orders})
    assert _pair(detect_overlap(dataset, default_config), "users", "contact_phone", "orders", "phone") == []
    config = _enabled(default_config)
    diagnostics = {}
    result = detect_overlap(dataset, config, diagnostics=diagnostics)
    hits = _pair(result, "users", "contact_phone", "orders", "phone")
    assert len(hits) == 1 and diagnostics["rescued"] == 1
    norm = hits[0]["details"]["normalization"]
    assert norm["applied"] is True and norm["raw_matched"] == 0
    assert norm["normalized_matched"] == 8 and norm["normalized_jaccard"] == 1.0
    assert norm["source_chain"] == norm["target_chain"] == "strip_delimiters"
    assert norm["effective_jaccard"] == round(norm["normalized_jaccard"] * norm["chain_trust"], 4)
    assert norm["confidence_gain"] > 0 and hits[0]["confidence"] >= config["overlap"]["threshold"]
    assert {item["source_value"] for item in hits[0]["evidence"]} == {
        "138 1234 000{0}".format(i) for i in range(5)
    }
def test_amount_and_date_formats_rescued(default_config):
    config = _enabled(default_config)
    left = pd.DataFrame({"amount": ["¥1,200.50", "¥3,000.00", "¥850.00", "¥99.90"] * 2})
    right = pd.DataFrame({"amount": ["1,200.50", "3,000.00", "850.00", "99.90"] * 2})
    dates_a = pd.DataFrame({"event_date": ["2024/01/0{0}".format(i) for i in range(1, 9)] * 2})
    dates_b = pd.DataFrame({"event_date": ["2024-01-0{0}".format(i) for i in range(1, 9)] * 2})
    dataset = make_dataset(config, {"a": left, "b": right, "da": dates_a, "db": dates_b})
    result = detect_overlap(dataset, config)
    amount = _pair(result, "a", "amount", "b", "amount")[0]["details"]["normalization"]
    assert amount["source_chain"] == amount["target_chain"] == "numeric_unit"
    day = _pair(result, "da", "event_date", "db", "event_date")[0]["details"]["normalization"]
    assert day["source_chain"] == "date_unify" and day["target_chain"] == "identity"
def test_garbage_column_degrades_without_error(default_config):
    config = _enabled(default_config)
    good = ["ab-1234-0{0}".format(i) for i in range(6)]
    bad = ["乱码★-//", "◆◆--**", "／／＊＊", "✕✕--//"]
    left = pd.DataFrame({"scrap_code": (good + bad) * 2})
    right = pd.DataFrame({"scrap_code": (["cd-9876-0{0}".format(i) for i in range(6)] + bad) * 2})
    dataset = make_dataset(config, {"ga": left, "gb": right})
    diagnostics = {}
    result = detect_overlap(dataset, config, diagnostics=diagnostics)
    degraded = {(d["table"], d["field"], d["chain"]) for d in diagnostics["degraded"]}
    assert ("ga", "scrap_code", "strip_delimiters") in degraded
    assert ("gb", "scrap_code", "strip_delimiters") in degraded
    assert _pair(result, "ga", "scrap_code", "gb", "scrap_code") == []
def test_chain_cache_bounds_cost(default_config):
    config = _enabled(default_config)
    users, orders = _phone_frames()
    third = pd.DataFrame({"phone": ["{0}-{1}-{2}".format(n[:3], n[3:7], n[7:])
                                    for n in ["1381234000{0}".format(i) for i in range(8)]] * 2})
    dataset = make_dataset(config, {"users": users, "orders": orders, "third": third})
    diagnostics = {}
    result = detect_overlap(dataset, config, diagnostics=diagnostics)
    assert diagnostics["cache_entries"] == 3
    assert diagnostics["rescued"] == 2
    raw_hit = _pair(result, "users", "contact_phone", "third", "phone")[0]
    assert raw_hit["details"]["normalization"]["applied"] is False
def test_custom_rule_priority_kept(default_config):
    config = _enabled(default_config)
    users, orders = _phone_frames()
    dataset = make_dataset(config, {"users": users, "orders": orders})
    overlap = detect_overlap(dataset, config)
    custom = make_association("orders", "phone", "users", "contact_phone",
                              "custom", 1.0, "custom_rule")
    merged = merge_associations(overlap + [custom])
    top = _pair(merged, "users", "contact_phone", "orders", "phone")[0]
    assert top["relation_type"] == "custom" and top["confidence"] == 1.0
    assert set(top["detection_sources"]) == {"custom_rule", "value_overlap"}
@pytest.mark.parametrize("payload,message", [
    ({"overlap": {"normalization": {"enabled": "yes"}}}, "布尔值"),
    ({"overlap": {"normalization": {"min_side_coverage": 2}}}, "不能大于"),
    ({"overlap": {"normalization": {"min_normalized_jaccard": -0.1}}}, "不能小于"),
    ({"overlap": {"normalization": {"bogus": 1}}}, "未知配置项"),
    ({"overlap": {"normalization": {"normalizers": {"bogus": {"enabled": True, "trust": 1}}}}}, "未知配置项"),
    ({"overlap": {"normalization": {"normalizers": {"case_fold": {"trust": 1.5}}}}}, "不能大于"),
    ({"overlap": {"normalization": {"normalizers": {"date_unify": {"enabled": 1}}}}}, "布尔值"),
])
def test_normalization_schema_validation(payload, message):
    def merge(base, extra):
        for key, value in extra.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                merge(base[key], value)
            else:
                base[key] = value
    config = copy.deepcopy(DEFAULT_CONFIG)
    merge(config, payload)
    with pytest.raises(ConfigError) as exc:
        validate_config(config, "unit.yaml")
    assert message in str(exc.value)
def _write_phone_csvs(directory):
    directory.mkdir(parents=True, exist_ok=True)
    users, orders = _phone_frames()
    users.to_csv(directory / "users.csv", index=False)
    orders.to_csv(directory / "orders.csv", index=False)
def _pipeline_config(tmp_path, default_config, name, normalization):
    config = copy.deepcopy(default_config)
    config["sources"]["csv_dirs"] = [str(tmp_path / name / "csv")]
    config["sources"]["sqlite_files"] = []
    config["explicit"]["custom_rules_path"] = ""
    config["output"]["directory"] = str(tmp_path / name / "out")
    config["incremental"]["default_baseline"] = ""
    if normalization is None:
        del config["overlap"]["normalization"]
    else:
        config["overlap"]["normalization"]["enabled"] = normalization
    path = tmp_path / name / "config.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return str(path)
def _digests(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(Path(directory).iterdir())}
def test_pipeline_outputs_reproducible(tmp_path, default_config):
    _write_phone_csvs(tmp_path / "on" / "csv")
    _write_phone_csvs(tmp_path / "off" / "csv")
    _write_phone_csvs(tmp_path / "absent" / "csv")
    on = _pipeline_config(tmp_path, default_config, "on", True)
    off = _pipeline_config(tmp_path, default_config, "off", False)
    absent = _pipeline_config(tmp_path, default_config, "absent", None)
    first = run_pipeline(config_path=on, base_dir=str(ROOT), use_default_baseline=False)
    before = _digests(tmp_path / "on" / "out")
    again = run_pipeline(config_path=on, base_dir=str(ROOT), use_default_baseline=False)
    assert _digests(tmp_path / "on" / "out") == before
    run_pipeline(config_path=off, base_dir=str(ROOT), use_default_baseline=False)
    off_before = _digests(tmp_path / "off" / "out")
    run_pipeline(config_path=off, base_dir=str(ROOT), use_default_baseline=False)
    assert _digests(tmp_path / "off" / "out") == off_before
    run_pipeline(config_path=absent, base_dir=str(ROOT), use_default_baseline=False)
    assert _digests(tmp_path / "off" / "out") == _digests(tmp_path / "absent" / "out")
    assert _digests(tmp_path / "on" / "out") != _digests(tmp_path / "off" / "out")
    associations = json.loads((tmp_path / "on" / "out" / "relations.json").read_text(encoding="utf-8"))["associations"]
    hits = _pair(associations, "users", "contact_phone", "orders", "phone")
    assert hits and hits[0]["details"]["normalization"]["source_chain"] == "strip_delimiters"
    report = (tmp_path / "on" / "out" / "report.md").read_text(encoding="utf-8")
    assert "跨来源规范化" in report and "规范化救援命中 1 条" in report
    html = (tmp_path / "on" / "out" / "graph.html").read_text(encoding="utf-8")
    assert "跨来源规范化" in html and "strip_delimiters" in html
    off_associations = json.loads((tmp_path / "off" / "out" / "relations.json").read_text(encoding="utf-8"))["associations"]
    assert _pair(off_associations, "users", "contact_phone", "orders", "phone") == []
    assert first.overlap_diagnostics["rescued"] == 1 and again.overlap_diagnostics["rescued"] == 1
