"""主题域配置段的默认值与严格校验，风格与 tablelink.config 保持一致。"""
from ..exceptions import ConfigError
RELATION_TYPES = (
    "custom", "explicit_fk", "explicit_naming",
    "value_overlap", "functional_dependency",
)
DEFAULT_DOMAIN_CONFIG = {
    "enabled": False,
    "edge_weight_threshold": 0.55,
    "max_domain_size": 25,
    "bridge_min_domains": 2,
    "bridge_balance_ratio": 0.65,
    "relation_weights": {
        "custom": 1.0, "explicit_fk": 1.0, "explicit_naming": 0.9,
        "value_overlap": 0.7, "functional_dependency": 0.3,
    },
}
def _fail(path, key, message, hint):
    raise ConfigError(path, key, message, hint)
def validate_domain_config(section, config_path="<config>"):
    """校验 domain 配置段；非法时抛出带字段路径与修复建议的 ConfigError。"""
    if not isinstance(section, dict):
        _fail(config_path, "domain", "应为映射", "使用 YAML 的 domain: 下接 key: value 结构")
    unknown = sorted(set(section) - set(DEFAULT_DOMAIN_CONFIG))
    if unknown:
        _fail(config_path, "domain." + unknown[0], "未知配置项",
              "删除该项或检查拼写，可用项: " + ", ".join(DEFAULT_DOMAIN_CONFIG))
    def number(key, value, low, high=None):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _fail(config_path, key, "应为数字", "填写数值，不要加引号")
        if value < low or (high is not None and value > high):
            _fail(config_path, key,
                  "不能小于 {0}".format(low) if value < low else "不能大于 {0}".format(high),
                  "调整该值后重试")
        return value
    if not isinstance(section.get("enabled"), bool):
        _fail(config_path, "domain.enabled", "应为布尔值", "填写 true 或 false（不加引号）")
    number("domain.edge_weight_threshold", section.get("edge_weight_threshold"), 0.0, 1.0)
    number("domain.max_domain_size", section.get("max_domain_size"), 2)
    number("domain.bridge_min_domains", section.get("bridge_min_domains"), 2)
    number("domain.bridge_balance_ratio", section.get("bridge_balance_ratio"), 0.0, 1.0)
    weights = section.get("relation_weights")
    if not isinstance(weights, dict):
        _fail(config_path, "domain.relation_weights", "应为映射",
              "按关系类型填写权重，例如 value_overlap: 0.7")
    extra = sorted(set(weights) - set(RELATION_TYPES))
    if extra:
        _fail(config_path, "domain.relation_weights." + extra[0], "未知关系类型",
              "可选类型: " + ", ".join(RELATION_TYPES))
    total = 0.0
    for key in RELATION_TYPES:
        if key not in weights:
            _fail(config_path, "domain.relation_weights." + key, "缺少权重项",
                  "补全五类关系权重: " + ", ".join(RELATION_TYPES))
        total += number("domain.relation_weights." + key, weights[key], 0.0, 1.0)
    if total <= 0:
        _fail(config_path, "domain.relation_weights", "权重之和必须大于 0",
              "至少给一类关系设置正数权重")
    return section
def build_domain_settings(section):
    """把已校验配置转成聚类模块使用的扁平参数。"""
    return {
        "enabled": bool(section["enabled"]),
        "edge_weight_threshold": float(section["edge_weight_threshold"]),
        "max_domain_size": int(section["max_domain_size"]),
        "bridge_min_domains": int(section["bridge_min_domains"]),
        "bridge_balance_ratio": float(section["bridge_balance_ratio"]),
        "relation_weights": {key: float(section["relation_weights"][key])
                             for key in RELATION_TYPES},
    }
