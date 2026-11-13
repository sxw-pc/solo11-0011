"""Markdown 报告中的主题域分节渲染（仅在 domain.enabled 时挂载）。"""
def _table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(str(v) for v in row) + " |" for row in rows)
    return lines
def build_domain_section(result):
    """按域分节渲染：域概览、逐域明细、桥接表、未分组清单。"""
    stats = result["stats"]
    lines = [
        "", "## 8. 主题域自动划分", "",
        "- 主题域：{0} 个，归入域的表 {1} 张。".format(
            stats["domain_count"], stats["grouped_table_count"]),
        "- 跨域桥接表：{0} 张；未分组（孤立/弱连接）表：{1} 张。".format(
            stats["bridge_table_count"], stats["ungrouped_table_count"]),
        "- 表级强边阈值：权重 ≥ {0:.2f}；表级加权边共 {1} 条，其中强边 {2} 条。".format(
            result["settings"]["edge_weight_threshold"],
            stats["table_edge_count"], stats["strong_edge_count"]), "",
    ]
    lines.extend(_table(
        ["域编号", "建议名称", "核心表", "表数量", "域内强边", "域内累计权重"],
        [[d["domain_id"], d["name"], d["core_table"], d["table_count"],
          d["internal_edge_count"], "{0:.4f}".format(d["total_internal_weight"])]
         for d in result["domains"]]))
    for domain in result["domains"]:
        lines.extend(["", "### {0} {1}".format(domain["domain_id"], domain["name"]), "",
                      "- 核心表：`{0}`；成员表：{1}。".format(
                          domain["core_table"],
                          "、".join("`{0}`".format(n) for n in domain["tables"]))])
        tokens = domain["name_evidence"].get("token_frequency", [])
        if tokens:
            lines.append("- 命名依据（域内高频词）：{0}。".format(
                "、".join("{0}（{1} 表）".format(i["token"], i["table_count"])
                          for i in tokens)))
    lines.extend(["", "### 跨域桥接表", ""])
    if result["bridge_tables"]:
        rows = [[b["table"],
                 "、".join("{0}({1:.4f})".format(l["domain_id"], l["weight"])
                           for l in b["domain_links"]),
                 b["primary_domain_id"], b["reason"]] for b in result["bridge_tables"]]
        lines.extend(_table(["桥接表", "跨域权重依据", "首要关联域", "标注理由"], rows))
    else:
        lines.append("无。")
    lines.extend(["", "### 未分组清单（孤立表/弱连接表）", ""])
    if result["ungrouped_tables"]:
        lines.extend("- `{0}`：无达到阈值的表级强邻接，不归入任何主题域。".format(n)
                     for n in result["ungrouped_tables"])
    else:
        lines.append("无。")
    return lines
