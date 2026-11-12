"""统一端点重写：关联、基线、证据与置信度的重新计算与稳定命名。"""
import hashlib
from ..detector.graph_common import merge_associations
def endpoint(cluster, field):
    return cluster["name"], cluster["aliases"].get(str(field).lower(), field)
def association_id(item):
    key = "{0}.{1}->{2}.{3}".format(
        item["source_table"], item["source_field"],
        item["target_table"], item["target_field"],
    )
    return "rel_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
def _key(item):
    return (item.get("source_table"), item.get("source_field"),
            item.get("target_table"), item.get("target_field"))
def _evidence_union(rewritten, limit=12):
    """按重写后的端点收集全部证据；同值对去重，保留首次出现顺序。"""
    grouped = {}
    for item in rewritten:
        pairs = grouped.setdefault(_key(item), [])
        seen = {pair[0] for pair in pairs}
        for sample in item.get("evidence") or []:
            key = (str(sample.get("source_value")), str(sample.get("target_value")))
            if key not in seen:
                pairs.append((key, dict(sample)))
                seen.add(key)
    return {key: [sample for _, sample in values[:limit]]
            for key, values in grouped.items()}
def _origin_tables(rewritten):
    """每个统一端点键对应的原始来源表，用于说明合并了哪些端点。"""
    grouped = {}
    for item in rewritten:
        origin = item.get("original_endpoint") or {}
        tables = grouped.setdefault(_key(item), set())
        for prefix in ("source_table", "target_table"):
            original = origin.get(prefix)
            if original:
                tables.add(original)
            tables.add(item.get(prefix, ""))
    return {key: sorted(name for name in names if name)
            for key, names in grouped.items()}
def rewrite(associations, plan):
    """把原始端点上的关联重写到统一端点，再按新端点重新合并与重算。"""
    if not plan:
        return list(associations)
    rewritten = []
    for item in associations:
        source_table = item.get("source_table")
        target_table = item.get("target_table")
        copied = dict(item)
        origin = {
            "source_table": source_table,
            "source_field": item.get("source_field"),
            "target_table": target_table,
            "target_field": item.get("target_field"),
        }
        changed = False
        if source_table in plan["unified"]:
            copied["source_table"], copied["source_field"] = endpoint(
                plan["unified"][source_table], item["source_field"])
            changed = changed or (copied["source_table"], copied["source_field"]) != (
                origin["source_table"], origin["source_field"])
        if target_table in plan["unified"]:
            copied["target_table"], copied["target_field"] = endpoint(
                plan["unified"][target_table], item["target_field"])
            changed = changed or (copied["target_table"], copied["target_field"]) != (
                origin["target_table"], origin["target_field"])
        if changed:
            copied["original_endpoint"] = origin
            copied["id"] = ""
        rewritten.append(copied)
    unions = _evidence_union(rewritten)
    origins = _origin_tables(rewritten)
    merged = merge_associations(rewritten)
    for item in merged:
        item["id"] = association_id(item)
        if unions.get(_key(item)):
            item["evidence"] = unions[_key(item)]
        item["unified"] = True
        item["unified_from"] = origins.get(_key(item), [])
        item["merged_detection_count"] = len(item.get("detections", []))
        details = dict(item.get("details") or {})
        details["unified_confidence_basis"] = (
            "max over {0} merged detections; all evidence retained".format(
                len(item.get("detections", [])))
        )
        item["details"] = details
    return merged
def history(records, plan):
    """旧基线端点映射到统一端点；旧版记录按原始端点写也能对齐。"""
    if not plan:
        return list(records)
    mapped = []
    for item in records:
        copied = dict(item)
        origin = {
            "source_table": item.get("source_table"),
            "source_field": item.get("source_field"),
            "target_table": item.get("target_table"),
            "target_field": item.get("target_field"),
        }
        changed = False
        if item.get("source_table") in plan["unified"]:
            copied["source_table"], copied["source_field"] = endpoint(
                plan["unified"][item["source_table"]], item["source_field"])
            changed = changed or (copied["source_table"], copied["source_field"]) != (
                origin["source_table"], origin["source_field"])
        if item.get("target_table") in plan["unified"]:
            copied["target_table"], copied["target_field"] = endpoint(
                plan["unified"][item["target_table"]], item["target_field"])
            changed = changed or (copied["target_table"], copied["target_field"]) != (
                origin["target_table"], origin["target_field"])
        if changed:
            copied["baseline_endpoint"] = origin
        mapped.append(copied)
    return merge_associations(mapped)
