"""历史关联规则加载与增量差分。"""
import json
import os
import yaml
from .exceptions import IncrementalError
def _key(item):
    return (
        item.get("source_table"), item.get("source_field"),
        item.get("target_table"), item.get("target_field"),
    )
def _normalize(item, index):
    if not isinstance(item, dict):
        raise IncrementalError("历史规则第 {0} 项不是映射".format(index))
    required = ("source_table", "source_field", "target_table", "target_field")
    missing = [key for key in required if not item.get(key)]
    if missing:
        raise IncrementalError(
            "历史规则第 {0} 项缺少字段: {1}".format(index, ", ".join(missing))
        )
    try:
        confidence = float(item.get("confidence", 0))
    except (TypeError, ValueError):
        raise IncrementalError("历史规则第 {0} 项置信度不是数字".format(index))
    if not 0 <= confidence <= 1:
        raise IncrementalError("历史规则第 {0} 项置信度不在 0~1".format(index))
    normalized = dict(item)
    normalized["confidence"] = confidence
    normalized.setdefault("relation_type", "unknown")
    normalized.setdefault("relation_types", [normalized["relation_type"]])
    normalized.setdefault("detection_sources", ["history"])
    normalized.setdefault("evidence", [])
    normalized.setdefault("details", {})
    return normalized
def load_history(path):
    """读取 JSON 或 YAML 历史规则，返回按端点去重后的关联列表。"""
    if not path or not os.path.isfile(path):
        raise IncrementalError("历史规则文件不存在: {0}".format(path))
    try:
        with open(path, "r", encoding="utf-8") as handle:
            if str(path).lower().endswith(".json"):
                payload = json.load(handle)
            else:
                payload = yaml.safe_load(handle)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise IncrementalError("历史规则解析失败: {0}".format(exc))
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict) and isinstance(payload.get("associations"), list):
        items = payload["associations"]
    else:
        raise IncrementalError("历史规则需包含 associations 列表")
    merged = {}
    for index, raw in enumerate(items):
        item = _normalize(raw, index)
        key = _key(item)
        if key not in merged or item["confidence"] > merged[key]["confidence"]:
            merged[key] = item
    return sorted(merged.values(), key=lambda item: _key(item))
def _copy(item, change):
    result = dict(item)
    result["change"] = change
    return result
def compare(current, history, threshold=0.05):
    """输出新增、失效、置信度变化超过阈值的三类清单。"""
    current_map = {_key(item): item for item in current}
    history_map = {_key(item): item for item in history}
    added = []
    removed = []
    changed = []
    unchanged = 0
    for key in sorted(set(current_map) | set(history_map)):
        if key not in history_map:
            added.append(_copy(current_map[key], "added"))
        elif key not in current_map:
            removed.append(_copy(history_map[key], "removed"))
        else:
            now = current_map[key]
            before = history_map[key]
            delta = round(float(now.get("confidence", 0)) - before["confidence"], 4)
            if abs(delta) > threshold:
                item = _copy(now, "confidence_changed")
                item["previous_confidence"] = before["confidence"]
                item["confidence_delta"] = delta
                changed.append(item)
            else:
                unchanged += 1
    added.sort(key=_key)
    removed.sort(key=_key)
    changed.sort(key=_key)
    return {
        "threshold": threshold,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "confidence_changed": len(changed),
            "unchanged": unchanged,
        },
        "added": added,
        "removed": removed,
        "confidence_changed": changed,
    }
def tag_current(current, diff):
    """给当前关联写入 change 标记，供 JSON/YAML 与图表使用。"""
    tags = {}
    for item in diff.get("added", []):
        tags[_key(item)] = ("added", None)
    for item in diff.get("confidence_changed", []):
        tags[_key(item)] = ("confidence_changed", item.get("confidence_delta"))
    result = []
    for item in current:
        copied = dict(item)
        change, delta = tags.get(_key(item), (None, None))
        copied["change"] = change
        if delta is not None:
            copied["change_delta"] = delta
        result.append(copied)
    return result
