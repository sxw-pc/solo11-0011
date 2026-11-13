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
    normalized = dict(item)
    for side in ("source", "target"):
        values = normalized.get(side + "_fields")
        if not normalized.get(side + "_field") \
                and isinstance(values, (list, tuple)) and values:
            normalized[side + "_field"] = "+".join(str(value) for value in values)
    required = ("source_table", "source_field", "target_table", "target_field")
    missing = [key for key in required if not normalized.get(key)]
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
def _fields(item, side):
    """取关联某一侧的列清单；复合记录来自字段列表或拼接端点。"""
    details = item.get("details") or {}
    values = item.get(side + "_fields") or details.get(side + "_fields")
    if isinstance(values, (list, tuple)) and values:
        return [str(value) for value in values]
    field = str(item.get(side + "_field") or "")
    return field.split("+") if "+" in field else [field]
def _signature(item):
    """列对集合签名：与列序无关，用于识别复合记录的历史形态。"""
    sources, targets = _fields(item, "source"), _fields(item, "target")
    if not sources or not targets or len(sources) != len(targets):
        return None
    return (item.get("source_table"), item.get("target_table"),
            frozenset(zip(sources, targets)))
def _absorb_historical_forms(pending_current, pending_history, history_map):
    """把旧基线中无列序的复合记录（整体或拆分形态）归并到当前复合记录。

    归并只看列对集合是否精确覆盖：覆盖关系成立时，当前复合记录与尚未
    匹配的历史记录都视为未变化；已被精确匹配的历史记录不参与计数。
    """
    absorbed_current, absorbed_history = set(), set()
    for key, item in pending_current.items():
        signature = _signature(item)
        if signature is None or len(signature[2]) < 2:
            continue
        group = []
        for hkey, hitem in history_map.items():
            hsig = _signature(hitem)
            if hsig and hsig[:2] == signature[:2] and hsig[2] <= signature[2]:
                group.append(hkey)
        if group and frozenset().union(*(_signature(history_map[hkey])[2]
                                         for hkey in group)) == signature[2]:
            absorbed_current.add(key)
            absorbed_history.update(hkey for hkey in group
                                    if hkey in pending_history)
    return absorbed_current, absorbed_history
def compare(current, history, threshold=0.05):
    """输出新增、失效、置信度变化超过阈值的三类清单。"""
    current_map = {_key(item): item for item in current}
    history_map = {_key(item): item for item in history}
    added = []
    removed = []
    changed = []
    unchanged = 0
    pending_current = {}
    pending_history = {}
    for key in sorted(set(current_map) | set(history_map)):
        if key not in history_map:
            pending_current[key] = current_map[key]
        elif key not in current_map:
            pending_history[key] = history_map[key]
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
    absorbed_current, absorbed_history = _absorb_historical_forms(
        pending_current, pending_history, history_map)
    unchanged += len(absorbed_current)
    for key in sorted(set(pending_current) - absorbed_current):
        added.append(_copy(pending_current[key], "added"))
    for key in sorted(set(pending_history) - absorbed_history):
        removed.append(_copy(pending_history[key], "removed"))
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
