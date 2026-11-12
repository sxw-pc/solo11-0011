"""端点归并单元测试：召回、指纹、值域守卫、降级与确定性。"""
import copy
from tablelink.config import ConfigManager
from tablelink.loader import BaseLoader, Dataset
from tablelink.merge import build_plan, document
from tablelink.merge.fingerprint import (
    canonical_table_name,
    strip_source_suffix,
    table_fingerprint,
    value_guard,
)
from tablelink.merge.rewrite import endpoint
from tests.conftest import ROOT, make_dataset
def _merge_config(config):
    copied = copy.deepcopy(config)
    copied["merge"].update({"enabled": True})
    return copied
def _dataset(config, folder, name_filter=None):
    from tablelink.loader import CSVDirectoryLoader
    loader = CSVDirectoryLoader(config, str(ROOT / "fixtures" / "endpoint_merge" / folder))
    dataset = Dataset()
    loader.load(dataset)
    if name_filter:
        dataset.tables = {k: v for k, v in dataset.tables.items() if name_filter(k)}
    return dataset
def test_normalization_and_fingerprint():
    config = ConfigManager(str(ROOT / "config.yaml"), base_dir=str(ROOT)).load()
    loader = BaseLoader(config)
    first = loader.make_table("info_engineer", _frame("engineer_id", ["E1", "E2"]), "a.csv",
                              source_type="csv")
    second = loader.make_table("engineer_info", _frame("engineer_id", ["E1", "E2"]), "b.csv",
                              source_type="csv")
    assert table_fingerprint(first)["digest"] == table_fingerprint(second)["digest"]
    assert canonical_table_name(first) == canonical_table_name(second) == "engineer_info"
    assert strip_source_suffix("engineer_info__csv_2", "csv") == "engineer_info"
    assert strip_source_suffix("engineer_info__csv_2", "csv", enabled=False) == "engineer_info__csv_2"
    renamed = loader.make_table("engineer_info__csv", _frame("engineer_id", ["E1", "E2"]),
                              "a.csv", source_type="csv")
    assert canonical_table_name(renamed) == "engineer_info"
def _frame(field, values, **extra):
    import pandas as pd
    payload = {field: values}
    for key, items in extra.items():
        payload[key] = items
    return pd.DataFrame(payload)
def test_value_guard_rejects_disjoint_and_accepts_overlap(default_config):
    config = copy.deepcopy(default_config)
    config["merge"].update({"enabled": True, "value_jaccard_threshold": 0.5})
    dataset = make_dataset(config, {
        "左": _frame("engineer_id", ["E1", "E2", "E3", "E4"], engineer_name=list("甲乙丙丁")),
        "右": _frame("engineer_id", ["E1", "E2", "E3", "E5"], engineer_name=list("甲丙丁戊")),
        "异": _frame("engineer_id", ["X1", "X2", "X3", "X4"], engineer_name=list("子丑寅卯")),
    })
    fingerprint = table_fingerprint(dataset.tables["左"])
    guard = value_guard(dataset.tables["左"], dataset.tables["右"], fingerprint, config["merge"])
    assert guard["passed"] and guard["jaccard"] == 0.6
    guard = value_guard(dataset.tables["左"], dataset.tables["异"], fingerprint, config["merge"])
    assert not guard["passed"] and guard["reason"] == "value_domain_too_low"
def test_guard_skips_when_verification_disabled(default_config):
    config = copy.deepcopy(default_config)
    config["merge"].update({"enabled": True, "verify_values": False})
    dataset = make_dataset(config, {
        "左": _frame("engineer_id", ["E1", "E2", "E3"]),
        "右": _frame("engineer_id", ["X1", "X2", "X3"]),
    })
    guard = value_guard(dataset.tables["左"], dataset.tables["右"],
                        table_fingerprint(dataset.tables["左"]), config["merge"])
    assert guard["passed"] and guard["reason"] == "value_guard_disabled"
def test_plan_merges_duplicate_and_token_variant(default_config):
    config = _merge_config(default_config)
    dataset = _dataset(config, "source_a")
    second = _dataset(config, "source_b")
    third = _dataset(config, "source_c")
    for name in sorted(second.tables):
        dataset.add_table(second.tables[name])
    for name in sorted(third.tables):
        dataset.add_table(third.tables[name])
    plan = build_plan(dataset, config)
    clusters = {item["name"]: item for item in plan["clusters"]}
    engineer = clusters["engineer_info"]
    assert engineer["members"] == ["engineer_info", "engineer_info__csv", "info_engineer"]
    assert engineer["representative"].row_count == 4
    assert plan["stats"]["multi_member_cluster_count"] == 1
    assert not plan["fallbacks"]
    doc = document(plan)
    record = [item for item in doc["endpoint_map"] if item["original_table"] == "info_engineer"][0]
    assert record["unified_table"] == "engineer_info"
    assert record["basis"]["inferred_primary_keys"] == ["engineer_id"]
def test_plan_is_deterministic_across_runs(default_config):
    config = _merge_config(default_config)
    first = document(build_plan(_dataset(config, "source_a"), config))
    again = document(build_plan(_dataset(config, "source_a"), config))
    assert first == again
def test_fallback_on_missing_source_and_mismatch(default_config):
    config = _merge_config(default_config)
    dataset = _dataset(config, "source_a")
    for folder in ("degraded", "disjoint"):
        extra = _dataset(config, folder)
        for name in sorted(extra.tables):
            dataset.add_table(extra.tables[name])
    plan = build_plan(dataset, config)
    reasons = {item["reason"] for item in plan["fallbacks"]}
    assert "field_set_mismatch" in reasons
    assert "value_domain_too_low" in reasons
    bad = dataset.tables["engineer_info__csv_2"]
    assert bad.name not in [name for item in plan["clusters"]
                            if len(item["members"]) > 1 for name in item["members"]]
    bad.source_name = ""
    plan = build_plan(dataset, config)
    assert any(item["reason"] == "source_missing" for item in plan["fallbacks"])
def test_disabled_switch_returns_no_plan(default_config):
    config = copy.deepcopy(default_config)
    config["merge"]["enabled"] = False
    assert build_plan(_dataset(config, "source_a"), config) is None
