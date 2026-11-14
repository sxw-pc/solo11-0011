"""函数依赖检测：哈希分组校验、完全/部分依赖与跨表依赖。"""
from .common import _json_scalar, make_association, sort_associations
def _meta(table, field):
    for column in table.columns:
        if column["name"] == field:
            return column
    return None
def _valid_frame(table, source_field, target_field):
    if table.frame is None:
        return None
    if source_field not in table.frame.columns or target_field not in table.frame.columns:
        return None
    return table.frame[[source_field, target_field]].dropna()
def _intra_dependency(table, source, target, config):
    frame = _valid_frame(table, source, target)
    if frame is None or len(frame) < config["fd"]["min_rows"]:
        return None
    grouped = frame.groupby(source, sort=False)[target].nunique()
    if grouped.empty:
        return None
    totals = frame.groupby(source, sort=False).size()
    bad_rows = int(totals[grouped > 1].sum())
    matched_rows = int(len(frame))
    confidence = (matched_rows - bad_rows) / matched_rows if matched_rows else 0.0
    if confidence < config["fd"]["confidence_threshold"]:
        return None
    evidence = []
    for value, group in frame.groupby(source, sort=False):
        targets = group[target].dropna().unique()
        if len(targets) == 1:
            evidence.append({"source_value": _json_scalar(value),
                             "target_value": _json_scalar(targets[0])})
        if len(evidence) >= 5:
            break
    complete = confidence >= config["fd"]["complete_threshold"]
    return make_association(
        table.name, source, table.name, target,
        "functional_dependency", confidence, "functional_dependency",
        evidence=evidence,
        details={
            "scope": "same_table",
            "valid_rows": matched_rows,
            "matched_rows": matched_rows - bad_rows,
            "source_cardinality": int(frame[source].nunique()),
            "target_cardinality": int(frame[target].nunique()),
            "dependency": "complete" if complete else "partial",
            "confidence_basis": "一致行数 / 有效行数 = {0} / {1}".format(
                matched_rows - bad_rows, matched_rows),
        },
    )
def _source_candidates(dataset, table, config):
    result = []
    for column in table.columns:
        cardinality = column["cardinality"]
        if cardinality < 2:
            continue
        if cardinality > config["fd"]["max_source_cardinality_ratio"] * table.row_count:
            continue
        if cardinality == table.row_count:
            others = [
                other for name, other in dataset.tables.items()
                if name != table.name and other.column(column["name"])
            ]
            if not others:
                continue
        result.append(column)
    return result
def _intra_table(dataset, table, config):
    result = []
    for source in _source_candidates(dataset, table, config):
        for target in table.columns:
            if source["name"] == target["name"]:
                continue
            if target["dtype"] == "empty" or target["cardinality"] < 2:
                continue
            tcard = target["cardinality"]
            if tcard > source["cardinality"]:
                continue
            if tcard > config["fd"]["max_target_cardinality_ratio"] * table.row_count:
                continue
            item = _intra_dependency(table, source["name"], target["name"], config)
            if item:
                result.append(item)
    return result
def _cross_link(dataset, link, config):
    source_table = dataset.tables.get(link.get("source_table"))
    target_table = dataset.tables.get(link.get("target_table"))
    if not source_table or not target_table or source_table is target_table:
        return []
    key_source = link["source_field"]
    key_target = link["target_field"]
    if source_table.frame is None or target_table.frame is None:
        return []
    if key_source not in source_table.frame.columns or key_target not in target_table.frame.columns:
        return []
    mapping = {}
    for key, group in target_table.frame.groupby(key_target, sort=False):
        values = group.drop(columns=[key_target]).dropna(how="all")
        mapping[key] = {
            column: set(values[column].dropna().tolist()) for column in values.columns
        }
    result = []
    for target in target_table.columns:
        target_field = target["name"]
        if target_field == key_target or target["dtype"] == "empty" or \
                target["cardinality"] < 2:
            continue
        if target["cardinality"] > config["fd"]["max_target_cardinality_ratio"] * \
                target_table.row_count:
            continue
        matched = 0
        consistent = 0
        evidence = []
        for row in source_table.frame[[key_source]].dropna().itertuples(index=False):
            key = row[0]
            if key not in mapping:
                continue
            matched += 1
            values = mapping[key].get(target_field, set())
            if len(values) == 1:
                consistent += 1
                seen_values = {item["source_value"] for item in evidence}
                if len(evidence) < 5 and _json_scalar(key) not in seen_values:
                    value = next(iter(values))
                    evidence.append({
                        "source_value": _json_scalar(key),
                        "target_value": _json_scalar(value),
                    })
        if matched < config["fd"]["min_rows"]:
            continue
        confidence = consistent / matched if matched else 0.0
        if confidence < config["fd"]["confidence_threshold"]:
            continue
        complete = confidence >= config["fd"]["complete_threshold"]
        result.append(make_association(
            source_table.name, key_source, target_table.name, target_field,
            "functional_dependency", confidence, "functional_dependency",
            evidence=evidence,
            details={
                "scope": "cross_table",
                "via": "{0}.{1}".format(target_table.name, key_target),
                "valid_rows": matched,
                "matched_rows": consistent,
                "source_cardinality": int(source_table.frame[key_source].nunique()),
                "target_cardinality": target["cardinality"],
                "dependency": "complete" if complete else "partial",
                "confidence_basis": "跨表连接后一致行数 / 匹配行数 = {0} / {1}".format(
                    consistent, matched),
            },
        ))
    return result
def _cap_per_table(items, limit):
    grouped = {}
    for item in items:
        grouped.setdefault(item["source_table"], []).append(item)
    result = []
    for table_name in sorted(grouped):
        rows = grouped[table_name]
        rows.sort(key=lambda item: (
            -item["confidence"],
            -abs(item["details"].get("source_cardinality", 0) - item["details"].get("target_cardinality", 0)),
            item["target_table"], item["target_field"],
        ))
        result.extend(rows[:limit])
    return result
def detect_fd(dataset, config, key_links=None):
    """检测单表内和跨表函数依赖；key_links 用于确定跨表连接路径。"""
    if not config["fd"]["enabled"]:
        return []
    result = []
    for table in dataset.tables.values():
        if table.row_count < config["fd"]["min_rows"]:
            continue
        result.extend(_intra_table(dataset, table, config))
    if config["fd"]["cross_table"]:
        seen = set()
        for link in key_links or []:
            key = (
                link.get("source_table"), link.get("source_field"),
                link.get("target_table"), link.get("target_field"),
            )
            if key in seen:
                continue
            seen.add(key)
            result.extend(_cross_link(dataset, link, config))
    result = _cap_per_table(result, config["fd"]["max_per_table"])
    return sort_associations(result)
