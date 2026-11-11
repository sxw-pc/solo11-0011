"""显式关联检测单元测试。"""
import copy, pandas as pd
import pytest
from tablelink.detector import detect_explicit
from tablelink.exceptions import ConfigError
from tests.conftest import ROOT, make_dataset
def test_native_naming_and_custom_sources(explicit_associations):
    sources = {source for item in explicit_associations for source in item["detection_sources"]}
    assert {"sqlite_foreign_key", "naming_rule", "custom_rule"} <= sources
    native = [item for item in explicit_associations if item["relation_type"] == "explicit_fk"]
    assert len(native) == 2 and all(item["confidence"] == 1.0 for item in native)
    custom = [item for item in explicit_associations if item["relation_type"] == "custom"]
    assert any(item["source_table"] == "maintain_record" for item in custom)
    assert all(item["evidence"] or item["details"]["note"] for item in custom)
def test_naming_disabled_and_no_custom(default_dataset, default_config, explicit_associations):
    config = copy.deepcopy(default_config)
    config["explicit"]["naming"]["enabled"] = False
    config["explicit"]["custom_rules_path"] = None
    result = detect_explicit(default_dataset, config, str(ROOT))
    assert len(result) == 2
    assert all(item["relation_type"] == "explicit_fk" for item in result)
def test_synonym_naming_match(default_config):
    config = copy.deepcopy(default_config)
    config["explicit"]["custom_rules_path"] = None
    dataset = make_dataset(config, {
        "device_base": pd.DataFrame({"device_id": ["D1", "D2", "D3", "D4", "D5"]}),
        "sensor_extra": pd.DataFrame({"sensor_id": ["D1", "D2", "D3", "D4", "D5"], "v": range(5)}),
    })
    result = detect_explicit(dataset, config, str(ROOT))
    assert any(item["source_table"] == "sensor_extra" and item["source_field"] == "sensor_id" and
               item["target_table"] == "device_base" for item in result)
def _write_rule(tmp_path, content):
    path = tmp_path / "rules.yaml"
    path.write_text(content, encoding="utf-8")
    return str(path)
def _rule_config(config, path):
    copied = copy.deepcopy(config)
    copied["explicit"]["custom_rules_path"] = path
    return copied
@pytest.mark.parametrize("content,message", [
    ("rules: not-a-list\n", "必须是列表"), ("rules:\n  - source: no_dot\n    target: device_base.device_id\n", "格式"),
    ("rules:\n  - source: missing.device_id\n    target: device_base.device_id\n", "不存在"), ("rules:\n  - source: device_base.device_id\n    target: device_base.nope\n", "不存在"),
    ("rules:\n  - source: device_base.device_id\n    target: alarm_info.device_id\n    confidence: 3\n", "0~1"),
])
def test_custom_rule_validation(tmp_path, default_dataset, default_config, content, message):
    path = _write_rule(tmp_path, content)
    with pytest.raises(ConfigError) as exc:
        detect_explicit(default_dataset, _rule_config(default_config, path), str(ROOT))
    assert message in str(exc.value)
def test_custom_rule_missing_and_bad_yaml(tmp_path, default_dataset, default_config):
    with pytest.raises(ConfigError):
        detect_explicit(default_dataset, _rule_config(default_config, str(tmp_path / "none.yaml")), str(ROOT))
    path = _write_rule(tmp_path, "rules: [\n")
    with pytest.raises(ConfigError) as exc:
        detect_explicit(default_dataset, _rule_config(default_config, path), str(ROOT))
    assert "解析失败" in str(exc.value)
def test_custom_rule_without_overlap_kept(tmp_path, default_dataset, default_config):
    path = _write_rule(tmp_path, "rules:\n  - source: device_base.device_id\n    target: alarm_info.alarm_level\n")
    result = detect_explicit(default_dataset, _rule_config(default_config, path), str(ROOT))
    custom = [item for item in result if item["detection_sources"] == ["custom_rule"]]
    assert custom and custom[0]["evidence"] == []
