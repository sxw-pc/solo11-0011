"""来源层漂移：来源文件、表与字段三级差异识别及数据/配置归因。"""
from ..loader.base_loader import type_compatible
from .common import (
    NON_NULL_SIGNIFICANT,
    STATE_CONFIG_SIGNAL,
    STATE_DATA_SIGNAL,
    combine_origins,
    index_by,
)


def _source_brief(entry):
    return {
        "source_id": entry["source_id"],
        "path": entry.get("path"),
        "state": entry.get("state"),
        "error": entry.get("error"),
    }


def diff_sources(old, new):
    """比对来源文件清单，返回差异分组与每个来源的变化信号。"""
    old_map = index_by(old.get("sources", []), "source_id")
    new_map = index_by(new.get("sources", []), "source_id")
    added, removed, changed, signals = [], [], [], {}
    for source_id in sorted(set(old_map) | set(new_map)):
        before, after = old_map.get(source_id), new_map.get(source_id)
        if before is None:
            added.append(_source_brief(after))
            signals[source_id] = {"event": "added"}
        elif after is None:
            removed.append(_source_brief(before))
            signals[source_id] = {"event": "removed"}
        else:
            diff = {}
            if before.get("state") != after.get("state"):
                diff["state"] = {"before": before.get("state"),
                                 "after": after.get("state")}
            if before.get("fingerprint") != after.get("fingerprint"):
                diff["content_changed"] = True
            if before.get("encoding") != after.get("encoding"):
                diff["encoding"] = {"before": before.get("encoding"),
                                    "after": after.get("encoding")}
            if before.get("error") != after.get("error"):
                diff["error"] = {"before": before.get("error"),
                                 "after": after.get("error")}
            if diff:
                changed.append({"source_id": source_id, "path": after.get("path"),
                                "changes": diff})
                signals[source_id] = {"event": "changed", "diff": diff}
    return {"added": added, "removed": removed, "changed": changed}, signals


def origin_for(source_id, source_signals, config_sections):
    """来源层条目归因：文件指纹/状态变化为数据侧，sources 段变化为配置侧。"""
    origins = set()
    signal = source_signals.get(source_id)
    if signal:
        if signal["event"] in ("added", "removed"):
            origins.add("data")
        else:
            diff = signal.get("diff") or {}
            if diff.get("content_changed"):
                origins.add("data")
            state = diff.get("state") or {}
            for value in (state.get("before"), state.get("after")):
                if value in STATE_DATA_SIGNAL:
                    origins.add("data")
                elif value in STATE_CONFIG_SIGNAL:
                    origins.add("config")
    if "sources" in config_sections:
        origins.add("config")
    return combine_origins(sorted(origins)) if origins else "unknown"


def table_cause(source_id, source_signals, config_sections):
    signal = source_signals.get(source_id)
    if signal:
        if signal["event"] == "added":
            return "source_added"
        if signal["event"] == "removed":
            return "source_removed"
        diff = signal.get("diff") or {}
        state = diff.get("state") or {}
        if state.get("after") in ("error", "missing"):
            return "source_degraded"
        if state.get("before") in ("error", "missing"):
            return "source_recovered"
        if diff.get("content_changed"):
            return "source_content_changed"
    if "sources" in config_sections:
        return "config_filter"
    return "unexplained"


def _field_changes(old, new):
    changes = {}
    if old.get("dtype") != new.get("dtype"):
        changes["dtype"] = {
            "before": old.get("dtype"),
            "after": new.get("dtype"),
            "compatible": type_compatible(old.get("dtype"), new.get("dtype"),
                                          strict=True),
        }
    before_nn = float(old.get("non_null_ratio") or 0)
    after_nn = float(new.get("non_null_ratio") or 0)
    if before_nn != after_nn:
        changes["non_null_ratio"] = {
            "before": old.get("non_null_ratio"),
            "after": new.get("non_null_ratio"),
            "delta": round(after_nn - before_nn, 4),
            "significant": abs(after_nn - before_nn) >= NON_NULL_SIGNIFICANT,
        }
    for key in ("cardinality", "unique_ratio"):
        if old.get(key) != new.get(key):
            changes[key] = {"before": old.get(key), "after": new.get(key)}
    if old.get("value_fingerprint") != new.get("value_fingerprint"):
        changes["content_changed"] = True
    return changes


def diff_tables(old, new, source_signals, config_sections):
    """比对表与字段；返回差异分组、端点变化索引与归因映射。"""
    old_map = index_by(old.get("tables", []), "table")
    new_map = index_by(new.get("tables", []), "table")
    layer = {"tables_added": [], "tables_removed": [], "fields_added": [],
             "fields_removed": [], "fields_changed": []}
    endpoints = {"added": set(), "removed": set(), "changed": set()}
    origins = {}
    for name in sorted(set(old_map) | set(new_map)):
        before, after = old_map.get(name), new_map.get(name)
        if before is None or after is None:
            entry = after or before
            source_id = entry.get("source_id")
            origin = origin_for(source_id, source_signals, config_sections)
            brief = {"table": name, "source_id": source_id, "origin": origin,
                     "cause": table_cause(source_id, source_signals, config_sections)}
            layer["tables_added" if after else "tables_removed"].append(brief)
            endpoints["added" if after else "removed"].add(name)
            origins[("table", name)] = origin
            continue
        source_id = after.get("source_id") or before.get("source_id")
        origin = origin_for(source_id, source_signals, config_sections)
        old_fields = index_by(before.get("fields", []), "field")
        new_fields = index_by(after.get("fields", []), "field")
        for field in sorted(set(old_fields) | set(new_fields)):
            old_f, new_f = old_fields.get(field), new_fields.get(field)
            point = "{0}.{1}".format(name, field)
            if old_f is None or new_f is None:
                item = new_f or old_f
                brief = {"table": name, "field": field, "endpoint": point,
                         "source_id": source_id, "dtype": item.get("dtype"),
                         "origin": origin,
                         "cause": table_cause(source_id, source_signals,
                                              config_sections)}
                layer["fields_added" if new_f else "fields_removed"].append(brief)
                endpoints["added" if new_f else "removed"].add(point)
                origins[("field", point)] = origin
            else:
                changes = _field_changes(old_f, new_f)
                if changes:
                    layer["fields_changed"].append({
                        "table": name, "field": field, "endpoint": point,
                        "source_id": source_id, "origin": origin,
                        "changes": changes,
                    })
                    endpoints["changed"].add(point)
                    origins[("field", point)] = origin
    return layer, endpoints, origins
