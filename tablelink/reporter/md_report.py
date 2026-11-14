"""Markdown 分析报告生成。"""
from collections import Counter
def _cell(value):
    if value is None:
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ")
def _field_ref(table, field):
    return "`{0}.{1}`".format(table, field)
def _direction(item):
    return "{0} → {1}".format(
        _field_ref(item["source_table"], item["source_field"]),
        _field_ref(item["target_table"], item["target_field"]),
    )
def _evidence(item, limit=3):
    values = []
    for sample in (item.get("evidence") or [])[:limit]:
        values.append("{0}→{1}".format(
            _cell(sample.get("source_value")), _cell(sample.get("target_value"))
        ))
    return "; ".join(values) if values else "无值域样例"
def _source_text(item):
    return ", ".join(item.get("detection_sources", [])) or "-"
def _table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(value) for value in row) + " |")
    return lines
def _assoc_rows(items):
    return [
        [
            item["relation_type"],
            _direction(item),
            "{0:.4f}".format(item["confidence"]),
            _source_text(item),
            _evidence(item),
        ]
        for item in items
    ]
def _isolated_tables(dataset, associations):
    involved = set()
    for item in associations:
        involved.add(item["source_table"])
        involved.add(item["target_table"])
    return [name for name in sorted(dataset.tables) if name not in involved]
def _anomalies(dataset, associations, config):
    notes = []
    for item in dataset.errors:
        notes.append("加载提示：{0}（{1}）".format(
            _cell(item.get("message")), _cell(item.get("source"))
        ))
    empty_tables = [name for name, table in dataset.tables.items() if table.row_count == 0]
    if empty_tables:
        notes.append("空表：{0}，已参与结构读取但不参与有效关联统计。".format(
            ", ".join("`{0}`".format(name) for name in empty_tables)
        ))
    empty_fields = []
    for name, table in dataset.tables.items():
        for column in table.columns:
            if column["dtype"] == "empty":
                empty_fields.append("{0}.{1}".format(name, column["name"]))
    if empty_fields:
        notes.append("全空字段：{0}，值域检测已跳过。".format(
            ", ".join("`{0}`".format(item) for item in empty_fields)
        ))
    isolated = _isolated_tables(dataset, associations)
    if isolated:
        notes.append("孤立表：{0}，图中已自动过滤其表节点。".format(
            ", ".join("`{0}`".format(name) for name in isolated)
        ))
    low = [item for item in associations if item["confidence"] < config["report"]["high_confidence"]]
    if low:
        notes.append("待确认关联 {0} 条，置信度低于 {1:.2f}，建议抽样复核证据。".format(
            len(low), config["report"]["high_confidence"]
        ))
    no_evidence = [item for item in associations if len(item.get("evidence") or []) < 3]
    if no_evidence:
        notes.append("证据样例少于 3 条的关联 {0} 条，人工规则可能未命中足够值域样例。".format(
            len(no_evidence)
        ))
    directions = {}
    for item in associations:
        directions[(item["source_table"], item["source_field"],
                    item["target_table"], item["target_field"])] = item
    reciprocal = []
    for key, item in directions.items():
        reverse = (key[2], key[3], key[0], key[1])
        if reverse in directions and key < reverse:
            reciprocal.append("{0} 与反向关联".format(_direction(item)))
    if reciprocal:
        notes.append("检测到双向关联 {0} 组，例如：{1}。请按业务口径确认方向。".format(
            len(reciprocal), "；".join(reciprocal[:5])
        ))
    return notes or ["未发现异常项。"]
def build_markdown(dataset, associations, graph, config, diff=None, overlap_diagnostics=None):
    """生成确定性的 Markdown 报告文本。"""
    explicit_like = [item for item in associations
                     if item["relation_type"] != "functional_dependency"]
    high_threshold = config["report"]["high_confidence"]
    high = [item for item in explicit_like if item["confidence"] >= high_threshold]
    low = [item for item in explicit_like if item["confidence"] < high_threshold]
    fds = [item for item in associations
           if item["relation_type"] == "functional_dependency"]
    relation_counts = Counter(item["relation_type"] for item in associations)
    source_counts = Counter(
        source for item in associations for source in item.get("detection_sources", [])
    )
    lines = [
        "# 表链测绘仪分析报告",
        "",
        "> 本报告由本地离线检测生成，不含任何网络请求。",
        "> 所有关联均附检测来源、置信度依据与值域证据，可逐条复核。",
        "",
        "## 1. 数据集概览",
        "",
        "- 数据表：{0} 张".format(len(dataset.tables)),
        "- 字段：{0} 个".format(sum(len(table.columns) for table in dataset.tables.values())),
        "- 总行数：{0}".format(sum(table.row_count for table in dataset.tables.values())),
        "- 数据源：{0}".format(", ".join(dataset.sources) or "无"),
        "- 关联边：{0} 条（去重后）".format(len(associations)),
        "",
    ]
    lines.extend(_table(
        ["表名", "来源类型", "行数", "字段数"],
        [[name, table.source_type, table.row_count, len(table.columns)]
         for name, table in sorted(dataset.tables.items())],
    ))
    lines.extend(["", "## 2. 关联类型统计", ""])
    stat_rows = [[key, value] for key, value in sorted(relation_counts.items())]
    lines.extend(_table(["关系类型", "数量"], stat_rows))
    lines.extend(["", "按检测来源统计：", ""])
    lines.extend(_table(
        ["检测来源", "贡献关联数"],
        [[key, value] for key, value in sorted(source_counts.items())],
    ))
    lines.extend([
        "",
        "图谱节点：{0} 个表节点，{1} 个字段节点。".format(
            graph["stats"]["table_count"], graph["stats"]["field_count"]
        ),
        "",
        "## 3. 高置信度关联清单",
        "",
        "阈值：置信度 ≥ {0:.2f}。".format(high_threshold),
        "",
    ])
    if high:
        lines.extend(_table(["类型", "方向", "置信度", "检测来源", "证据样例"], _assoc_rows(high)))
    else:
        lines.append("未发现达到阈值的高置信度关联。")
    lines.extend(["", "## 4. 待确认低置信度关联", ""])
    if low:
        lines.extend(_table(["类型", "方向", "置信度", "检测来源", "证据样例"], _assoc_rows(low)))
    else:
        lines.append("没有低于高置信度阈值的显式或值域关联。")
    lines.extend(["", "## 5. 异常关联提示", ""])
    for note in _anomalies(dataset, associations, config):
        lines.append("- " + note)
    lines.extend(["", "## 6. 函数依赖清单", ""])
    if fds:
        rows = []
        for item in fds:
            details = item.get("details", {})
            rows.append([
                _direction(item),
                details.get("scope", "-"),
                details.get("dependency", "-"),
                "{0:.4f}".format(item["confidence"]),
                "{0}/{1}".format(
                    details.get("matched_rows", "-"), details.get("valid_rows", "-")
                ),
                _evidence(item),
            ])
        lines.extend(_table(
            ["函数依赖", "范围", "类别", "置信度", "一致/有效行", "证据样例"], rows
        ))
    else:
        lines.append("未发现满足阈值的函数依赖。")
    lines.extend(["", "## 7. 增量版本对比", ""])
    if diff is None:
        lines.append("本次未提供历史关联规则文件。")
    else:
        summary = diff["summary"]
        lines.append("- 新增关联：{0} 条".format(summary["added"]))
        lines.append("- 历史关联失效：{0} 条".format(summary["removed"]))
        lines.append("- 置信度变化超过 {0:.2f}：{1} 条".format(
            diff["threshold"], summary["confidence_changed"]
        ))
        lines.append("- 未变化：{0} 条".format(summary["unchanged"]))
        for title, key in (("新增关联", "added"), ("失效关联", "removed")):
            lines.extend(["", "### {0}".format(title), ""])
            items = diff.get(key, [])
            if items:
                lines.extend(_table(
                    ["类型", "方向", "置信度", "检测来源"],
                    [[item.get("relation_type", "-"), _direction(item),
                      "{0:.4f}".format(item["confidence"]),
                      ", ".join(item.get("detection_sources", []))] for item in items],
                ))
            else:
                lines.append("无。")
        lines.extend(["", "### 置信度变化", ""])
        items = diff.get("confidence_changed", [])
        if items:
            lines.extend(_table(
                ["方向", "原置信度", "现置信度", "变化"],
                [[_direction(item), "{0:.4f}".format(item["previous_confidence"]),
                  "{0:.4f}".format(item["confidence"]),
                  "{0:+.4f}".format(item["confidence_delta"])] for item in items],
            ))
        else:
            lines.append("无。")
    cfg = config["overlap"]
    lines.extend([
        "",
        "## 8. 审计说明",
        "",
        "- 值域关联：Jaccard 权重 {0}，名称相似度权重 {1}，同义词权重 {2}，阈值 {3:.2f}。".format(
            cfg["weights"]["value"], cfg["weights"]["name"],
            cfg["weights"]["synonym"], cfg["threshold"]
        ),
        "- 高基数字段阈值：基数 > 行数的 {0:.0%}；引用型 `_id` 字段可豁免。".format(
            cfg["max_cardinality_ratio"]
        ),
        "- 稀疏字段阈值：非空率 < {0:.0%} 时跳过。".format(cfg["min_nonnull_ratio"]),
    ])
    norm = cfg.get("normalization") or {}
    if norm.get("enabled"):
        lines.append(
            "- 跨来源规范化：救援模式启用，仅在原始置信度未达阈值时尝试；"
            "有效 Jaccard = 规范化 Jaccard × 链信任度（字段覆盖率 ≥ {0:.0%}，"
            "规范化 Jaccard ≥ {1:.2f}）。".format(
                norm["min_side_coverage"], norm["min_normalized_jaccard"]
            )
        )
        rescued = [
            item for item in associations
            if (item.get("details") or {}).get("normalization", {}).get("applied")
        ]
        if rescued:
            lines.append(
                "- 规范化救援命中 {0} 条关联；各关联证据记录了原始/规范化交集与采用链。".format(
                    len(rescued)
                )
            )
        degraded = (overlap_diagnostics or {}).get("degraded") or []
        if degraded:
            names = "、".join(
                "`{0}.{1}`（{2}，覆盖率 {3:.0%}）".format(
                    item["table"], item["field"], item["chain"], item["coverage"]
                )
                for item in degraded[:10]
            )
            lines.append(
                "- 规范化降级 {0} 项，坏值或形态无法推断，已回退原始值域比较：{1}".format(
                    len(degraded), names
                )
            )
    lines.extend([
        "- 函数依赖：最小样本 {0} 行，一致率 ≥ {1:.2f} 纳入；≥ {2:.3f} 记为完全依赖。".format(
            config["fd"]["min_rows"], config["fd"]["confidence_threshold"],
            config["fd"]["complete_threshold"]
        ),
        "- 自定义规则优先于自动检测；同端点关联去重后保留最高置信度并记录全部来源。",
        "- 本项目无网络请求、无遥测、无外部资源引用。",
        "",
    ])
    return "\n".join(lines)
