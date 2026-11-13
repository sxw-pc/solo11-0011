"""YAML 配置加载、Schema 校验、默认值与热加载。"""
import copy
import os
import threading
import yaml
from .domain.config import DEFAULT_DOMAIN_CONFIG, validate_domain_config
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
    "domain": copy.deepcopy(DEFAULT_DOMAIN_CONFIG),
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
def validate_config(config, path="<default>"):
    """校验完整配置；不合法时抛出带位置和修复建议的 ConfigError。"""
    _dict(path, "", config)
    _keys(path, config, "", DEFAULT_CONFIG.keys())
    for section in ("project", "sources", "explicit", "overlap", "fd",
                    "incremental", "output", "report", "domain", "web"):
        _dict(path, section, config.get(section))
    _keys(path, config["project"], "project.", ("name", "version"))
    _string(path, "project.name", config["project"].get("name"))
    _string(path, "project.version", config["project"].get("version"))
    src = config["sources"]
    _keys(path, src, "sources.", DEFAULT_CONFIG["sources"].keys())
    for key in ("csv_dirs", "sqlite_files", "csv_encodings", "include_tables", "exclude_tables", "exclude_fields"):
        _string_list(path, "sources." + key, src.get(key))
    if not src.get("csv_dirs") and not src.get("sqlite_files"):
        _fail(path, "sources", "至少需要配置一个 CSV 目录或 SQLite 文件", "填写 csv_dirs 或 sqlite_files")
    if not src.get("csv_encodings"):
        _fail(path, "sources.csv_encodings", "编码候选不能为空", "至少保留 utf-8")
    for enc in src["csv_encodings"]:
        try:
            "".encode(enc)
        except LookupError:
            _fail(path, "sources.csv_encodings", "未知编码 {0}".format(enc), "使用 utf-8 或 gbk")
    exp = config["explicit"]
    _keys(path, exp, "explicit.", DEFAULT_CONFIG["explicit"].keys())
    naming = _dict(path, "explicit.naming", exp.get("naming"))
    _keys(path, naming, "explicit.naming.", DEFAULT_CONFIG["explicit"]["naming"].keys())
    _boolean(path, "explicit.naming.enabled", naming.get("enabled"))
    _string_list(path, "explicit.naming.suffixes", naming.get("suffixes"), allow_empty=False)
    _number(path, "explicit.naming.min_overlap_ratio", naming.get("min_overlap_ratio"), 0, 1)
    _number(path, "explicit.naming.min_matched_values", naming.get("min_matched_values"), 1)
    _number(path, "explicit.naming.confidence", naming.get("confidence"), 0, 1)
    _number(path, "explicit.naming.table_name_confidence", naming.get("table_name_confidence"), 0, 1)
    syn = _dict(path, "explicit.naming.synonym_map", naming.get("synonym_map"))
    for left, values in syn.items():
        _string(path, "explicit.naming.synonym_map key", left)
        _string_list(path, "explicit.naming.synonym_map." + left, values)
    custom = exp.get("custom_rules_path")
    if custom is not None:
        _string(path, "explicit.custom_rules_path", custom, allow_empty=True)
    ov = config["overlap"]
    _keys(path, ov, "overlap.", DEFAULT_CONFIG["overlap"].keys())
    _number(path, "overlap.threshold", ov.get("threshold"), 0, 1)
    _boolean(path, "overlap.same_table", ov.get("same_table"))
    _boolean(path, "overlap.allow_reference_high_cardinality", ov.get("allow_reference_high_cardinality"))
    _boolean(path, "overlap.strict_type", ov.get("strict_type"))
    _number(path, "overlap.min_matched_values", ov.get("min_matched_values"), 1)
    _number(path, "overlap.max_cardinality_ratio", ov.get("max_cardinality_ratio"), 0, 1)
    _number(path, "overlap.min_nonnull_ratio", ov.get("min_nonnull_ratio"), 0, 1)
    _number(path, "overlap.max_pairs", ov.get("max_pairs"), 1)
    _number(path, "overlap.evidence_limit", ov.get("evidence_limit"), 1)
    weights = _dict(path, "overlap.weights", ov.get("weights"))
    _keys(path, weights, "overlap.weights.", ("value", "name", "synonym"))
    total = 0.0
    for key in ("value", "name", "synonym"):
        total += _number(path, "overlap.weights." + key, weights.get(key), 0, 1)
    if total <= 0:
        _fail(path, "overlap.weights", "权重之和必须大于 0", "至少给一个维度设置正数权重")
    fd = config["fd"]
    _keys(path, fd, "fd.", DEFAULT_CONFIG["fd"].keys())
    _boolean(path, "fd.enabled", fd.get("enabled"))
    _boolean(path, "fd.cross_table", fd.get("cross_table"))
    _number(path, "fd.min_rows", fd.get("min_rows"), 1)
    _number(path, "fd.confidence_threshold", fd.get("confidence_threshold"), 0, 1)
    _number(path, "fd.complete_threshold", fd.get("complete_threshold"), 0, 1)
    _number(path, "fd.max_source_cardinality_ratio", fd.get("max_source_cardinality_ratio"), 0, 1)
    _number(path, "fd.max_target_cardinality_ratio", fd.get("max_target_cardinality_ratio"), 0, 1)
    _number(path, "fd.max_per_table", fd.get("max_per_table"), 1)
    inc = config["incremental"]
    _keys(path, inc, "incremental.", DEFAULT_CONFIG["incremental"].keys())
    _number(path, "incremental.confidence_delta_threshold", inc.get("confidence_delta_threshold"), 0, 1)
    if inc.get("default_baseline") is not None:
        _string(path, "incremental.default_baseline", inc.get("default_baseline"), allow_empty=True)
    out = config["output"]
    _keys(path, out, "output.", DEFAULT_CONFIG["output"].keys())
    _string(path, "output.directory", out.get("directory"))
    for key in ("rules_json", "rules_yaml", "report_md", "graph_html", "graph_json"):
        _string(path, "output." + key, out.get(key))
    rep = config["report"]
    _keys(path, rep, "report.", DEFAULT_CONFIG["report"].keys())
    _number(path, "report.high_confidence", rep.get("high_confidence"), 0, 1)
    validate_domain_config(config["domain"], path)
    web = config["web"]
    _keys(path, web, "web.", DEFAULT_CONFIG["web"].keys())
    host = _string(path, "web.host", web.get("host"))
    if host not in _LOOPBACK_HOSTS:
        _fail(path, "web.host", "仅允许回环地址", "填写 127.0.0.1、localhost 或 ::1")
    _number(path, "web.port", web.get("port"), 1, 65535)
    _boolean(path, "web.debug", web.get("debug"))
    _boolean(path, "web.auto_reload", web.get("auto_reload"))
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
