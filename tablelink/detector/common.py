"""检测器共用的值规范化、证据构造与排序工具。"""
import hashlib
import math
import pandas as pd
RELATION_PRIORITY = {
    "custom": 5,
    "explicit_fk": 4,
    "explicit_naming": 3,
    "value_overlap": 2,
    "functional_dependency": 1,
}
def normalize_value(value):
    """统一跨数据源比较口径；空值返回 None。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, str):
        value = value.strip()
        return value if value else None
    return str(value)
def value_map(table, field):
    """返回字段的 规范化值 -> 原始值 映射。"""
    if table.frame is None or field not in table.frame.columns:
        return {}
    mapping = {}
    for value in table.frame[field].dropna().tolist():
        key = normalize_value(value)
        if key is not None and key not in mapping:
            mapping[key] = value
    return mapping
def evidence_pairs(source_table, source_field, target_table, target_field, limit=5):
    """取两边值域交集中的前若干条匹配证据。"""
    left = value_map(source_table, source_field)
    right = value_map(target_table, target_field)
    shared = sorted(set(left).intersection(right))
    return [
        {
            "source_value": _json_scalar(left[key]),
            "target_value": _json_scalar(right[key]),
        }
        for key in shared[:limit]
    ], len(shared)
def _json_scalar(value):
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
def make_association(source_table, source_field, target_table, target_field,
                     relation_type, confidence, detection_source,
                     evidence=None, details=None):
    """构造统一关联对象，确保关键字段齐全。"""
    key = "{0}.{1}->{2}.{3}".format(source_table, source_field, target_table, target_field)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return {
        "id": "rel_" + digest,
        "source_table": source_table,
        "source_field": source_field,
        "target_table": target_table,
        "target_field": target_field,
        "relation_type": relation_type,
        "relation_types": [relation_type],
        "confidence": round(float(confidence), 4),
        "detection_sources": [detection_source],
        "evidence": list(evidence or []),
        "details": dict(details or {}),
    }
def association_key(item):
    return (
        item.get("source_table"), item.get("source_field"),
        item.get("target_table"), item.get("target_field"),
    )
def sort_associations(items):
    return sorted(
        items,
        key=lambda item: (
            -float(item.get("confidence", 0)),
            item.get("source_table", ""),
            item.get("source_field", ""),
            item.get("target_table", ""),
            item.get("target_field", ""),
            item.get("relation_type", ""),
        ),
    )
def field_pair_allowed(left_table, left_field, right_table, right_field, strict=True):
    from ..loader.base_loader import type_compatible
    left_meta = left_table.column(left_field)
    right_meta = right_table.column(right_field)
    if not left_meta or not right_meta:
        return False
    return type_compatible(left_meta["dtype"], right_meta["dtype"], strict=strict)
