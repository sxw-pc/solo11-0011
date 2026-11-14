"""YAML 配置加载、Schema 校验、默认值与热加载。"""
import copy
import os
import threading
import yaml
from .exceptions import ConfigError
DEFAULT_CONFIG = {
    "project": {"name": "表链测绘仪", "version": "1.0.0"},
    "sources": {
        "csv_dirs": ["fixtures/mock_csv"],
        "sqlite_files": ["fixtures/mock_sqlite/env_monitor.db"],
        "csv_encodings": ["utf-8-sig", "utf-8", "gbk"],
        "include_tables": [],
        "exclude_tables": ["tmp_*", "temp_*", "sqlite_*"],
        "exclude_fields": [],
    },
    "explicit": {
        "naming": {
            "enabled": True,
            "suffixes": ["_id"],
            "min_overlap_ratio": 0.3,
            "min_matched_values": 3,
            "confidence": 0.84,
            "table_name_confidence": 0.90,
            "synonym_map": {
                "device": ["sensor", "equipment", "terminal"],
                "room": ["area", "zone", "site"],
                "engineer": ["technician", "staff"],
                "alarm": ["alert", "warning"],
            },
        },
        "custom_rules_path": "fixtures/custom_rules/user_rules.yaml",
    },
    "overlap": {
        "threshold": 0.70,
        "same_table": False,
        "min_matched_values": 3,
        "max_cardinality_ratio": 0.80,
        "allow_reference_high_cardinality": True,
        "min_nonnull_ratio": 0.20,
        "strict_type": True,
        "weights": {"value": 0.60, "name": 0.25, "synonym": 0.15},
        "max_pairs": 5000,
        "evidence_limit": 5,
    },
    "fd": {
        "enabled": True,
        "min_rows": 10,
        "confidence_threshold": 0.90,
        "complete_threshold": 0.999,
        "max_source_cardinality_ratio": 1.0,
        "max_target_cardinality_ratio": 0.50,
        "cross_table": True,
        "max_per_table": 8,
    },
    "incremental": {
        "confidence_delta_threshold": 0.05,
        "default_baseline": "fixtures/expected_output/history_relations.json",
    },
    "output": {
        "directory": "output",
        "rules_json": "relations.json",
        "rules_yaml": "relations.yaml",
        "report_md": "report.md",
        "graph_html": "graph.html",
        "graph_json": "graph.json",
    },
    "report": {"high_confidence": 0.90},
    "web": {
        "host": "127.0.0.1",
        "port": 5000,
        "debug": False,
        "auto_reload": True,
    },
}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
def _merge(base, override):
    result = copy.deepcopy(base)
    if override is None:
        return result
    if not isinstance(override, dict):
        raise ConfigError("<config>", "", "配置根节点必须是映射", "检查 YAML 缩进")
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result
def _fail(path, key, message, hint):
    raise ConfigError(path, key, message, hint)
def _keys(path, section, prefix, allowed):
    unknown = sorted(set(section) - set(allowed))
    if unknown:
        _fail(path, prefix + unknown[0], "未知配置项", "删除该项或检查拼写，可用项: " + ", ".join(allowed))
def _dict(path, key, value):
    if not isinstance(value, dict):
        _fail(path, key, "应为映射", "使用 YAML 的 key: value 结构")
    return value
def _string(path, key, value, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        _fail(path, key, "应为非空字符串", "使用引号包裹字符串")
    return value
def _boolean(path, key, value):
    if not isinstance(value, bool):
        _fail(path, key, "应为布尔值", "填写 true 或 false（不加引号）")
    return value
def _number(path, key, value, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(path, key, "应为数字", "填写数值，不要加引号")
    if low is not None and value < low:
        _fail(path, key, "不能小于 {0}".format(low), "调高该值后重试")
    if high is not None and value > high:
        _fail(path, key, "不能大于 {0}".format(high), "调低该值后重试")
    return value
def _string_list(path, key, value, allow_empty=True):
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        _fail(path, key, "应为字符串列表", "使用 YAML 列表，例如 [\"a.csv\"]")
    if not allow_empty and not value:
        _fail(path, key, "不能为空列表", "至少填写一个可用路径")
    return value
def _walk(config, key):
    value = config
    for part in key.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value
_FIELD_RULES = [
    ("project.name", _string, ()), ("project.version", _string, ()),
    ("explicit.naming.enabled", _boolean, ()),
    ("explicit.naming.suffixes", _string_list, (False,)),
    ("explicit.naming.min_overlap_ratio", _number, (0, 1)),
    ("explicit.naming.min_matched_values", _number, (1,)),
    ("explicit.naming.confidence", _number, (0, 1)),
    ("explicit.naming.table_name_confidence", _number, (0, 1)),
    ("overlap.threshold", _number, (0, 1)), ("overlap.same_table", _boolean, ()),
    ("overlap.allow_reference_high_cardinality", _boolean, ()),
    ("overlap.strict_type", _boolean, ()),
    ("overlap.min_matched_values", _number, (1,)),
    ("overlap.max_cardinality_ratio", _number, (0, 1)),
    ("overlap.min_nonnull_ratio", _number, (0, 1)),
    ("overlap.max_pairs", _number, (1,)), ("overlap.evidence_limit", _number, (1,)),
    ("overlap.weights.value", _number, (0, 1)),
    ("overlap.weights.name", _number, (0, 1)),
    ("overlap.weights.synonym", _number, (0, 1)),
    ("fd.enabled", _boolean, ()), ("fd.cross_table", _boolean, ()),
    ("fd.min_rows", _number, (1,)), ("fd.confidence_threshold", _number, (0, 1)),
    ("fd.complete_threshold", _number, (0, 1)),
    ("fd.max_source_cardinality_ratio", _number, (0, 1)),
    ("fd.max_target_cardinality_ratio", _number, (0, 1)),
    ("fd.max_per_table", _number, (1,)),
    ("incremental.confidence_delta_threshold", _number, (0, 1)),
    ("report.high_confidence", _number, (0, 1)),
    ("web.host", _string, ()), ("web.port", _number, (1, 65535)),
    ("web.debug", _boolean, ()), ("web.auto_reload", _boolean, ()),
]
def validate_config(config, path="<default>"):
    """校验完整配置；不合法时抛出带位置和修复建议的 ConfigError。"""
    _dict(path, "", config)
    _keys(path, config, "", DEFAULT_CONFIG.keys())
    for section in DEFAULT_CONFIG:
        _dict(path, section, config.get(section))
        _keys(path, config[section], section + ".", DEFAULT_CONFIG[section].keys())
    naming = _dict(path, "explicit.naming", config["explicit"].get("naming"))
    _keys(path, naming, "explicit.naming.", DEFAULT_CONFIG["explicit"]["naming"].keys())
    weights = _dict(path, "overlap.weights", config["overlap"].get("weights"))
    _keys(path, weights, "overlap.weights.", ("value", "name", "synonym"))
    src = config["sources"]
    for key in DEFAULT_CONFIG["sources"]:
        _string_list(path, "sources." + key, src.get(key))
    for key, validator, args in _FIELD_RULES:
        validator(path, key, _walk(config, key), *args)
    if not src.get("csv_dirs") and not src.get("sqlite_files"):
        _fail(path, "sources", "至少需要配置一个 CSV 目录或 SQLite 文件", "填写 csv_dirs 或 sqlite_files")
    if not src.get("csv_encodings"):
        _fail(path, "sources.csv_encodings", "编码候选不能为空", "至少保留 utf-8")
    for enc in src["csv_encodings"]:
        try:
            "".encode(enc)
        except LookupError:
            _fail(path, "sources.csv_encodings", "未知编码 {0}".format(enc), "使用 utf-8 或 gbk")
    for left, values in _dict(path, "explicit.naming.synonym_map", naming.get("synonym_map")).items():
        _string(path, "explicit.naming.synonym_map key", left)
        _string_list(path, "explicit.naming.synonym_map." + left, values)
    for key in ("explicit.custom_rules_path", "incremental.default_baseline"):
        value = _walk(config, key)
        if value is not None:
            _string(path, key, value, allow_empty=True)
    if sum(_walk(config, "overlap.weights." + key) for key in ("value", "name", "synonym")) <= 0:
        _fail(path, "overlap.weights", "权重之和必须大于 0", "至少给一个维度设置正数权重")
    for key in DEFAULT_CONFIG["output"]:
        _string(path, "output." + key, config["output"].get(key))
    if _walk(config, "web.host") not in _LOOPBACK_HOSTS:
        _fail(path, "web.host", "仅允许回环地址", "填写 127.0.0.1、localhost 或 ::1")
    return config
class ConfigManager:
    """管理配置加载与基于文件签名的热加载。"""
    def __init__(self, path=None, base_dir=None, auto_reload=True):
        self.path = os.path.abspath(path) if path else None
        self.base_dir = os.path.abspath(base_dir or os.getcwd())
        self.auto_reload = auto_reload
        self._config = None
        self._signature = None
        self._lock = threading.RLock()
    def _signature_of_path(self):
        if not self.path:
            return None
        try:
            stat = os.stat(self.path)
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)
    def load(self, force=False):
        with self._lock:
            if self._config is not None and not force:
                return copy.deepcopy(self._config)
            raw = {}
            if self.path:
                if not os.path.isfile(self.path):
                    _fail(self.path, "<file>", "配置文件不存在", "检查 --config 路径或复制内置 config.yaml")
                try:
                    with open(self.path, "r", encoding="utf-8") as handle:
                        raw = yaml.safe_load(handle) or {}
                except yaml.YAMLError as exc:
                    _fail(self.path, "<yaml>", "YAML 解析失败: {0}".format(exc), "检查缩进、冒号和引号")
                except OSError as exc:
                    _fail(self.path, "<file>", "无法读取配置: {0}".format(exc), "检查文件权限")
            merged = _merge(DEFAULT_CONFIG, raw)
            validate_config(merged, self.path or "<default>")
            self._config = merged
            self._signature = self._signature_of_path()
            return copy.deepcopy(merged)
    def reload_if_changed(self):
        with self._lock:
            if not self.path or not self.auto_reload:
                return False
            signature = self._signature_of_path()
            if signature is None:
                _fail(self.path, "<file>", "配置文件已不可访问", "恢复配置文件或重新指定 --config")
            if signature != self._signature:
                self.load(force=True)
                return True
            return False
    def resolve(self, value):
        if value is None:
            return None
        if os.path.isabs(value):
            return os.path.abspath(value)
        return os.path.abspath(os.path.join(self.base_dir, value))
