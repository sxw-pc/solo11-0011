"""快照比对编排：汇总来源层与检测层差异，输出结构化漂移审计文档。"""
from .assoc_diff import diff_associations
from .common import AUDIT_FORMAT, AUDIT_VERSION, combine_origins
from .source_diff import diff_sources, diff_tables


def _config_change(old, new):
    old_sections = (old.get("config") or {}).get("sections") or {}
    new_sections = (new.get("config") or {}).get("sections") or {}
    sections = sorted(
        name for name in set(old_sections) | set(new_sections)
        if old_sections.get(name) != new_sections.get(name)
    )
    return {
        "changed": bool(sections) or
                   (old.get("config") or {}).get("custom_rules") !=
                   (new.get("config") or {}).get("custom_rules"),
        "sections": sections,
        "custom_rules_changed": (old.get("config") or {}).get("custom_rules") !=
                                (new.get("config") or {}).get("custom_rules"),
        "tool_version_changed": (old.get("generator") or {}).get("tool_version") !=
                                (new.get("generator") or {}).get("tool_version"),
    }


def _degraded(snapshot):
    return [
        {"source_id": item["source_id"], "path": item.get("path"),
         "state": item.get("state"), "error": item.get("error")}
        for item in snapshot.get("sources", [])
        if item.get("state") in ("error", "missing")
    ]


def _zero_summary():
    return {"sources_added": 0, "sources_removed": 0, "sources_changed": 0,
            "tables_added": 0, "tables_removed": 0, "fields_added": 0,
            "fields_removed": 0, "fields_changed": 0, "associations_added": 0,
            "associations_removed": 0, "associations_changed": 0,
            "degraded_sources": 0}


def _empty_source_layer():
    return {"sources": {"added": [], "removed": [], "changed": []},
            "tables_added": [], "tables_removed": [], "fields_added": [],
            "fields_removed": [], "fields_changed": []}


def empty_audit(status, snapshot, note):
    """无可用基线时的审计文档：结构完整、差异为空，明确标注未比对。"""
    audit = {
        "audit_format": AUDIT_FORMAT,
        "audit_version": AUDIT_VERSION,
        "status": status,
        "baseline": None,
        "current": {"snapshot_id": snapshot.get("snapshot_id"),
                    "tool_version": (snapshot.get("generator") or {}).get("tool_version")},
        "config_change": {"changed": False, "sections": [],
                          "custom_rules_changed": False,
                          "tool_version_changed": False},
        "origin": "none",
        "summary": _zero_summary(),
        "source_layer": _empty_source_layer(),
        "detection_layer": {"added": [], "removed": [], "changed": []},
        "degraded_sources": _degraded(snapshot),
        "notes": [note],
    }
    audit["summary"]["degraded_sources"] = len(audit["degraded_sources"])
    return audit


def compare_snapshots(old, new):
    """比对基线与当前快照，输出结构化漂移审计文档。"""
    config = _config_change(old, new)
    sources, source_signals = diff_sources(old, new)
    tables, endpoints, origins = diff_tables(old, new, source_signals,
                                             config["sections"])
    ctx = {"endpoints": endpoints, "origins": origins,
           "source_signals": source_signals,
           "config_sections": config["sections"],
           "custom_rules_changed": config["custom_rules_changed"]}
    detection = diff_associations(old, new, ctx)
    source_layer = dict(tables)
    source_layer["sources"] = sources
    summary = _zero_summary()
    summary.update({
        "sources_added": len(sources["added"]),
        "sources_removed": len(sources["removed"]),
        "sources_changed": len(sources["changed"]),
        "tables_added": len(tables["tables_added"]),
        "tables_removed": len(tables["tables_removed"]),
        "fields_added": len(tables["fields_added"]),
        "fields_removed": len(tables["fields_removed"]),
        "fields_changed": len(tables["fields_changed"]),
        "associations_added": len(detection["added"]),
        "associations_removed": len(detection["removed"]),
        "associations_changed": len(detection["changed"]),
    })
    degraded = _degraded(new)
    summary["degraded_sources"] = len(degraded)
    entries = (tables["tables_added"] + tables["tables_removed"] +
               tables["fields_added"] + tables["fields_removed"] +
               tables["fields_changed"] + detection["added"] +
               detection["removed"] + detection["changed"])
    notes = []
    if config["tool_version_changed"]:
        notes.append("检测工具版本发生变化，无其他信号的差异可能来自检测规则实现更新")
    if degraded:
        notes.append("存在降级来源文件，其表/字段缺失可能由加载失败引起")
    return {
        "audit_format": AUDIT_FORMAT,
        "audit_version": AUDIT_VERSION,
        "status": "drift_detected" if entries else "no_drift",
        "baseline": {"snapshot_id": old.get("snapshot_id"),
                     "tool_version": (old.get("generator") or {}).get("tool_version")},
        "current": {"snapshot_id": new.get("snapshot_id"),
                    "tool_version": (new.get("generator") or {}).get("tool_version")},
        "config_change": config,
        "origin": combine_origins([e["origin"] for e in entries]) if entries else "none",
        "summary": summary,
        "source_layer": source_layer,
        "detection_layer": detection,
        "degraded_sources": degraded,
        "notes": notes,
    }
