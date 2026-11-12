"""结构漂移审计的人可读 Markdown 报告；输出确定、无时间戳。"""
_ORIGIN_TEXT = {
    "data": "数据变化", "config": "配置变化", "detector": "检测规则变化",
    "mixed": "混合因素", "unknown": "未知", "none": "无",
}
_STATUS_TEXT = {
    "drift_detected": "检测到结构漂移",
    "no_drift": "无结构漂移",
    "baseline_initialized": "已建立基线（首次运行，未执行比对）",
    "baseline_reset": "已重建基线（历史快照不可用）",
}
_CAUSE_TEXT = {
    "field_removed": "字段消失", "field_added": "字段新增",
    "table_removed": "表消失", "table_added": "表新增",
    "field_stats_changed": "字段统计突变",
    "source_data_changed": "来源文件内容变化",
    "config_change": "检测配置变化", "custom_rules_change": "自定义规则变化",
    "detector_behavior": "检测规则行为变化",
    "source_added": "来源文件新增", "source_removed": "来源文件消失",
    "source_degraded": "来源文件降级", "source_recovered": "来源文件恢复",
    "source_content_changed": "来源文件内容变化",
    "config_filter": "来源过滤配置变化", "unexplained": "未归因",
}
_SUMMARY_ROWS = (
    ("sources_added", "来源文件新增"), ("sources_removed", "来源文件消失"),
    ("sources_changed", "来源文件变化"), ("tables_added", "表新增"),
    ("tables_removed", "表消失"), ("fields_added", "字段新增"),
    ("fields_removed", "字段消失"), ("fields_changed", "字段统计变化"),
    ("associations_added", "关系新增"), ("associations_removed", "关系失效"),
    ("associations_changed", "关系变更"), ("degraded_sources", "降级来源"),
)


def _origin(origin):
    return _ORIGIN_TEXT.get(origin, origin)


def _cause(cause):
    text = _CAUSE_TEXT.get(cause["kind"], cause["kind"])
    if cause.get("endpoint"):
        text += " " + cause["endpoint"]
    if cause.get("source_id"):
        text += "（来源 {0}）".format(cause["source_id"])
    if cause.get("sections"):
        text += "（段落：{0}）".format(", ".join(cause["sections"]))
    return text


def _item_cause(item):
    cause = item.get("cause")
    if cause:
        return "；原因：" + _CAUSE_TEXT.get(cause, cause)
    causes = item.get("causes") or []
    if causes:
        return "；回溯：" + "；".join(_cause(entry) for entry in causes)
    return ""


def _fmt_delta(value):
    return "{0:+.4f}".format(value)


def _field_change_text(changes):
    parts = []
    dtype = changes.get("dtype")
    if dtype:
        note = "兼容" if dtype["compatible"] else "类型兼容性破坏"
        parts.append("类型 {0}→{1}（{2}）".format(dtype["before"], dtype["after"], note))
    non_null = changes.get("non_null_ratio")
    if non_null:
        flag = "，突变" if non_null["significant"] else ""
        parts.append("非空率 {0}→{1}（Δ{2}{3}）".format(
            non_null["before"], non_null["after"], _fmt_delta(non_null["delta"]), flag))
    for key, label in (("cardinality", "基数"), ("unique_ratio", "唯一率")):
        if key in changes:
            parts.append("{0} {1}→{2}".format(label, changes[key]["before"],
                                              changes[key]["after"]))
    if changes.get("content_changed"):
        parts.append("值内容变化")
    return "；".join(parts)


def _assoc_change_text(changes):
    parts = []
    for key, label in (("relation_type", "关系类型"), ("relation_types", "关系类型集"),
                       ("detection_sources", "检测来源"), ("detections", "检测明细")):
        if key in changes:
            parts.append("{0} {1}→{2}".format(label, changes[key]["before"],
                                              changes[key]["after"]))
    if "confidence" in changes:
        conf = changes["confidence"]
        parts.append("置信度 {0}→{1}（Δ{2}）".format(
            conf["before"], conf["after"], _fmt_delta(conf["delta"])))
    if changes.get("evidence_changed"):
        parts.append("匹配证据变化")
    if changes.get("details_changed"):
        parts.append("置信度依据变化")
    return "；".join(parts)


def _lines_for(items, render, empty="无"):
    if not items:
        return ["- " + empty]
    return [render(item) for item in items]


def build_audit_markdown(audit):
    """把审计文档渲染为确定性 Markdown 报告。"""
    summary = audit["summary"]
    config = audit["config_change"]
    lines = [
        "# 结构漂移审计报告",
        "",
        "- 审计状态：{0}".format(_STATUS_TEXT.get(audit["status"], audit["status"])),
        "- 总体归因：{0}".format(_origin(audit["origin"])),
        "- 基线快照：{0}".format((audit.get("baseline") or {}).get("snapshot_id") or "无"),
        "- 当前快照：{0}".format((audit.get("current") or {}).get("snapshot_id") or "无"),
    ]
    if config["changed"]:
        detail = []
        if config["sections"]:
            detail.append("配置段：" + ", ".join(config["sections"]))
        if config["custom_rules_changed"]:
            detail.append("自定义规则文件变化")
        lines.append("- 配置变化：是（{0}）".format("；".join(detail)))
    else:
        lines.append("- 配置变化：否")
    if config["tool_version_changed"]:
        lines.append("- 检测工具版本：{0} → {1}".format(
            (audit.get("baseline") or {}).get("tool_version"),
            (audit.get("current") or {}).get("tool_version")))
    lines += ["", "## 概览", "", "| 类别 | 数量 |", "| --- | --- |"]
    lines += ["| {0} | {1} |".format(label, summary[key]) for key, label in _SUMMARY_ROWS]
    source = audit["source_layer"]
    lines += ["", "## 来源层变化", "", "### 来源文件"]
    files = (source["sources"]["added"] + source["sources"]["removed"] +
             source["sources"]["changed"])
    lines += _lines_for(files, lambda item: "- `{0}`：{1}".format(
        item["source_id"], _source_change_text(item)))
    lines += ["", "### 表变化"]
    tables = ([(item, "新增") for item in source["tables_added"]] +
              [(item, "消失") for item in source["tables_removed"]])
    lines += _lines_for(tables, lambda pair: (
        "- {0} `{1}`（来源 {2}；归因：{3}{4}）".format(
            pair[1], pair[0]["table"], pair[0].get("source_id"),
            _origin(pair[0]["origin"]), _item_cause(pair[0]))))
    lines += ["", "### 字段新增 / 消失"]
    fields = ([(item, "新增") for item in source["fields_added"]] +
              [(item, "消失") for item in source["fields_removed"]])
    lines += _lines_for(fields, lambda pair: (
        "- {0} `{1}`（类型 {2}；来源 {3}；归因：{4}{5}）".format(
            pair[1], pair[0]["endpoint"], pair[0].get("dtype"),
            pair[0].get("source_id"), _origin(pair[0]["origin"]),
            _item_cause(pair[0]))))
    lines += ["", "### 字段统计突变"]
    lines += _lines_for(source["fields_changed"], lambda item: (
        "- `{0}`：{1}（来源 {2}；归因：{3}）".format(
            item["endpoint"], _field_change_text(item["changes"]),
            item.get("source_id"), _origin(item["origin"]))))
    detection = audit["detection_layer"]
    lines += ["", "## 检测层变化", "", "### 失效关系"]
    lines += _lines_for(detection["removed"], lambda item: (
        "- `{0}`（原置信度 {1}；归因：{2}{3}）".format(
            item["key"], item.get("confidence"), _origin(item["origin"]),
            _item_cause(item))))
    lines += ["", "### 新增关系"]
    lines += _lines_for(detection["added"], lambda item: (
        "- `{0}`（置信度 {1}；归因：{2}{3}）".format(
            item["key"], item.get("confidence"), _origin(item["origin"]),
            _item_cause(item))))
    lines += ["", "### 关系变更"]
    lines += _lines_for(detection["changed"], lambda item: (
        "- `{0}`：{1}（归因：{2}{3}）".format(
            item["key"], _assoc_change_text(item["changes"]),
            _origin(item["origin"]), _item_cause(item))))
    lines += ["", "## 降级来源"]
    lines += _lines_for(audit["degraded_sources"], lambda item: (
        "- `{0}`：{1} —— {2}".format(item["source_id"], item["state"],
                                     item.get("error") or "无错误信息")))
    if audit.get("notes"):
        lines += ["", "## 备注"]
        lines += ["- " + note for note in audit["notes"]]
    return "\n".join(lines) + "\n"


def _source_change_text(item):
    changes = item.get("changes")
    if not changes:
        return "状态 {0}".format(item.get("state"))
    parts = []
    if changes.get("state"):
        parts.append("状态 {0}→{1}".format(changes["state"]["before"],
                                           changes["state"]["after"]))
    if changes.get("content_changed"):
        parts.append("文件内容变化")
    if changes.get("encoding"):
        parts.append("编码 {0}→{1}".format(changes["encoding"]["before"],
                                           changes["encoding"]["after"]))
    if changes.get("error"):
        parts.append("错误：{0}".format(changes["error"]["after"] or "已恢复"))
    return "；".join(parts)
