"""检测层漂移：同一端点关联的关系类型、检测来源与置信度依据差异及回溯。"""
from .common import DETECTION_SECTIONS, combine_origins, index_by


def _assoc_changes(before, after):
    changes = {}
    for key in ("relation_type", "relation_types", "detection_sources", "detections"):
        if before.get(key) != after.get(key):
            changes[key] = {"before": before.get(key), "after": after.get(key)}
    delta = round(float(after.get("confidence", 0)) - float(before.get("confidence", 0)), 4)
    if delta:
        changes["confidence"] = {"before": before.get("confidence"),
                                 "after": after.get("confidence"), "delta": delta}
    if before.get("evidence_fingerprint") != after.get("evidence_fingerprint"):
        changes["evidence_changed"] = True
    if before.get("details_fingerprint") != after.get("details_fingerprint"):
        changes["details_changed"] = True
    return changes


def _endpoint_causes(item, ctx, table_sources):
    """把关联差异回溯到端点字段/表的变化事件，或来源文件内容变化。"""
    causes = []
    for role in ("source", "target"):
        table, field = item[role + "_table"], item[role + "_field"]
        point = "{0}.{1}".format(table, field)
        source_id = table_sources.get(table)
        if point in ctx["endpoints"]["removed"]:
            kind = "field_removed"
        elif point in ctx["endpoints"]["added"]:
            kind = "field_added"
        elif table in ctx["endpoints"]["removed"]:
            kind = "table_removed"
        elif table in ctx["endpoints"]["added"]:
            kind = "table_added"
        elif point in ctx["endpoints"]["changed"]:
            kind = "field_stats_changed"
        else:
            continue
        scope = "field" if kind.startswith("field") else "table"
        anchor = point if scope == "field" else table
        causes.append({"kind": kind, "endpoint": point, "table": table,
                       "field": field, "source_id": source_id,
                       "origin": ctx["origins"].get((scope, anchor), "unknown")})
    if not causes:
        for table in (item["source_table"], item["target_table"]):
            source_id = table_sources.get(table)
            signal = ctx["source_signals"].get(source_id) or {}
            if (signal.get("diff") or {}).get("content_changed"):
                causes.append({"kind": "source_data_changed",
                               "source_id": source_id, "origin": "data"})
    return causes


def _assoc_causes(item, ctx, table_sources):
    causes = _endpoint_causes(item, ctx, table_sources)
    sections = sorted(set(ctx["config_sections"]) & set(DETECTION_SECTIONS))
    if sections:
        causes.append({"kind": "config_change", "sections": sections,
                       "origin": "config"})
    if ctx["custom_rules_changed"]:
        causes.append({"kind": "custom_rules_change", "origin": "config"})
    if not causes:
        causes.append({"kind": "detector_behavior", "origin": "detector"})
    return causes


def diff_associations(old, new, ctx):
    """按端点对齐关联，输出新增/失效/变更三组差异，逐条携带归因与回溯。"""
    old_map = index_by(old.get("associations", []), "key")
    new_map = index_by(new.get("associations", []), "key")
    old_sources = {t["table"]: t.get("source_id") for t in old.get("tables", [])}
    new_sources = {t["table"]: t.get("source_id") for t in new.get("tables", [])}
    layer = {"added": [], "removed": [], "changed": []}
    for key in sorted(set(old_map) | set(new_map)):
        before, after = old_map.get(key), new_map.get(key)
        item = after or before
        entry = {"key": key, "source_table": item["source_table"],
                 "source_field": item["source_field"],
                 "target_table": item["target_table"],
                 "target_field": item["target_field"]}
        if before is None or after is None:
            sources = new_sources if after else old_sources
            entry["causes"] = _assoc_causes(item, ctx, sources)
            entry["origin"] = combine_origins([c["origin"] for c in entry["causes"]])
            entry["confidence"] = item.get("confidence")
            layer["added" if after else "removed"].append(entry)
            continue
        changes = _assoc_changes(before, after)
        if not changes:
            continue
        entry["changes"] = changes
        entry["causes"] = _assoc_causes(after, ctx, new_sources)
        entry["origin"] = combine_origins([c["origin"] for c in entry["causes"]])
        layer["changed"].append(entry)
    return layer
