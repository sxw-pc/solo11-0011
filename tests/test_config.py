"""配置合并、校验与热加载测试。"""
import copy, os
import pytest, yaml
from tablelink.config import ConfigManager, DEFAULT_CONFIG, validate_config
from tablelink.exceptions import ConfigError
def _write(tmp_path, payload):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return path
def _merge(base, extra):
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base
def test_manager_cache_reload_and_resolve(tmp_path):
    path = _write(tmp_path, {"overlap": {"threshold": 0.70}})
    manager = ConfigManager(str(path), base_dir=str(tmp_path))
    first = manager.load()
    assert first["overlap"]["threshold"] == 0.70
    first["overlap"]["threshold"] = 0.1
    assert manager.load()["overlap"]["threshold"] == 0.70
    path.write_text(path.read_text(encoding="utf-8").replace("0.7", "0.55"), encoding="utf-8")
    os.utime(path, ns=(path.stat().st_atime_ns + 1000, path.stat().st_mtime_ns + 1000))
    assert manager.reload_if_changed() is True
    assert manager.load()["overlap"]["threshold"] == 0.55
    assert manager.reload_if_changed() is False
    assert manager.resolve("output") == str(tmp_path / "output")
    assert manager.resolve(str(tmp_path / "x")) == str(tmp_path / "x")
    assert manager.resolve(None) is None
    assert ConfigManager(None).load() == DEFAULT_CONFIG
    assert ConfigManager(None).reload_if_changed() is False
def test_missing_and_bad_files(tmp_path):
    with pytest.raises(ConfigError) as exc:
        ConfigManager(str(tmp_path / "none.yaml")).load()
    assert exc.value.key == "<file>" and exc.value.hint
    path = tmp_path / "bad.yaml"
    path.write_text("overlap: [\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        ConfigManager(str(path)).load()
    assert "YAML" in str(exc.value)
    path.write_text("[1]\n", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        ConfigManager(str(path)).load()
    assert "根节点" in str(exc.value)
def test_reload_change_and_removed(tmp_path):
    path = _write(tmp_path, {"project": {"name": "A"}})
    manager = ConfigManager(str(path))
    manager.load()
    path.write_text(yaml.safe_dump({"project": {"name": "B"}}), encoding="utf-8")
    os.utime(path, ns=(path.stat().st_atime_ns + 2000, path.stat().st_mtime_ns + 2000))
    assert manager.reload_if_changed()
    assert manager.load()["project"]["name"] == "B"
    path.unlink()
    with pytest.raises(ConfigError):
        manager.reload_if_changed()
@pytest.mark.parametrize("payload,message", [
({"project": None}, "应为映射"), ({"bogus": 1}, "未知配置项"),
({"project": {"name": ""}}, "非空字符串"), ({"sources": {"csv_dirs": [], "sqlite_files": []}}, "至少需要"),
({"sources": {"csv_encodings": []}}, "编码候选"), ({"sources": {"csv_encodings": ["not-an-encoding"]}}, "未知编码"),
({"sources": {"include_tables": "x"}}, "字符串列表"), ({"explicit": {"naming": None}}, "应为映射"),
({"explicit": {"naming": {"enabled": "yes"}}}, "布尔值"), ({"explicit": {"naming": {"suffixes": []}}}, "不能为空"),
({"explicit": {"naming": {"confidence": 2}}}, "不能大于"), ({"explicit": {"custom_rules_path": 1}}, "非空字符串"),
({"overlap": {"threshold": -1}}, "不能小于"), ({"overlap": {"weights": {"value": 0, "name": 0, "synonym": 0}}}, "权重之和"),
({"overlap": {"weights": {"value": 0, "name": 0, "synonym": 0, "x": 1}}}, "未知配置项"), ({"fd": {"enabled": 1}}, "布尔值"),
({"fd": {"min_rows": 0}}, "不能小于"), ({"incremental": {"default_baseline": 3}}, "非空字符串"),
({"output": {"directory": ""}}, "非空字符串"), ({"report": {"high_confidence": 1.1}}, "不能大于"),
({"web": {"host": "0.0.0.0"}}, "回环地址"), ({"web": {"port": 0}}, "不能小于"),
({"overlap": {"max_pairs": "all"}}, "应为数字"),
])
def test_schema_validation(payload, message):
    with pytest.raises(ConfigError) as exc:
        validate_config(_merge(copy.deepcopy(DEFAULT_CONFIG), payload), "unit.yaml")
    assert message in str(exc.value)
    assert exc.value.path == "unit.yaml"
