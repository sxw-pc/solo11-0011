"""端点归并的结构指纹、来源后缀/名称 token 归一与主键值域守卫。"""
import hashlib
import json
import re
from ..detector.common import normalize_value
_TOKEN_RE = re.compile(r"[^a-z0-9]+")
def name_tokens(name):
    return [item for item in _TOKEN_RE.split(str(name).lower()) if item]
def strip_source_suffix(name, source_type, enabled=True):
    """去除加载器为重名表追加的 __<source_type>[_N] 后缀。"""
    if not enabled:
        return str(name)
    pattern = re.compile(r"__{0}(_\d+)?$".format(re.escape(str(source_type).lower())),
                         re.IGNORECASE)
    return pattern.sub("", str(name))
def canonical_table_name(table, token_order=True, suffix_strip=True):
    """与来源、token 顺序无关的候选统一表名；非 ASCII 名回退小写原名。"""
    base = strip_source_suffix(table.name, table.source_type, suffix_strip)
    tokens = name_tokens(base)
    if not tokens:
        return str(base).strip().lower()
    return "_".join(sorted(tokens) if token_order else tokens)
def infer_primary_keys(table):
    """优先原生主键；CSV 用首个唯一 _id 列作主键近似。"""
    if table.primary_keys:
        return sorted(name for name in table.primary_keys if table.column(name))
    if table.row_count == 0:
        return []
    ids = [c["name"] for c in table.columns if c["name"].lower().endswith("_id")
           and c["cardinality"] == table.row_count]
    if ids:
        return [ids[0]]
    unique = [c["name"] for c in table.columns if c["cardinality"] == table.row_count]
    return [unique[0]] if len(unique) == 1 else []
def table_fingerprint(table):
    """结构指纹 = 字段名有序集合 + 推断主键，用于稳定可复现的同构判定。"""
    fields = sorted(column["name"] for column in table.columns)
    primary = sorted(infer_primary_keys(table))
    payload = json.dumps({"fields": fields, "primary_keys": primary},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "fields": fields,
        "field_keys": [name.lower() for name in fields],
        "primary_keys": primary,
        "primary_key_keys": [name.lower() for name in primary],
        "digest": hashlib.sha1(payload.encode("utf-8")).hexdigest(),
    }
def _actual_column(table, key):
    for name in table.column_names():
        if name.lower() == key:
            return name
    return None
def _value_set(table, field):
    column = _actual_column(table, field.lower())
    if table.frame is None or column is None or column not in table.frame.columns:
        return None
    return {normalize_value(value) for value in table.frame[column].dropna().tolist()} - {None}
def value_guard(left, right, fingerprint, config):
    """用共同主键字段的值域交集校验结构同构，防止同名异构表误合并。"""
    guard = {"available": True, "passed": False, "reason": "", "jaccard": None}
    if not config.get("verify_values", True):
        return dict(guard, passed=True, reason="value_guard_disabled")
    keys = sorted(set(fingerprint["primary_key_keys"]))
    if not keys:
        return dict(guard, available=False, passed=True, reason="no_inferred_primary_key")
    shared_total = union_total = 0
    for key in keys:
        left_values, right_values = _value_set(left, key), _value_set(right, key)
        if not left_values or not right_values:
            return dict(guard, available=False, passed=True,
                        reason="empty_or_missing_key_values")
        shared_total += len(left_values & right_values)
        union_total += len(left_values | right_values)
    jaccard = round(shared_total / union_total, 4) if union_total else 0.0
    passed = (shared_total >= int(config.get("min_matched_values", 3))
              and jaccard >= float(config.get("value_jaccard_threshold", 0.5)))
    return dict(guard, passed=passed, jaccard=jaccard, shared_values=shared_total,
                key_fields=keys,
                reason="value_domain_verified" if passed else "value_domain_too_low")
def representative(tables):
    """确定性代表表：优先有数据的表，再按名称排序。"""
    ordered = sorted(tables, key=lambda item: (-int(item.row_count), item.name.lower(), item.name))
    return ordered[0] if ordered else None
