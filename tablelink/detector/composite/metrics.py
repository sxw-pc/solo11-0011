"""组合键关联检测入口：元组级交集度量、置信度与证据构造。

置信度语义（权重可在 config.composite.weights 配置，默认加权和）：
- coverage   引用侧组合值落在被引用侧值域中的比例（参照完整性强度）；
- jaccard    两侧组合值域的 Jaccard 交集比例；
- uniqueness 组合接近唯一键的程度，取两侧组合基数/行数的较小者；
- naming     各对应列的名称相似度均值。
总分 = 加权和 / 权重总和，四舍五入到 4 位小数；达到 composite.threshold
且交集元组数不少于 min_matched_tuples 才输出。
"""
from difflib import SequenceMatcher
from ..common import make_association, normalize_value, sort_associations
from .pruning import Degradation, build_candidates

FIELD_SEP = ","


def _name_similarity(left, right):
    left_key = left.lower().replace("_", "")
    right_key = right.lower().replace("_", "")
    return SequenceMatcher(None, left_key, right_key).ratio()


def tuple_value_set(table, fields, row_cap):
    """构造多列规范化元组的值域；行数超限时返回 None 触发降级。"""
    if table.frame is None or table.row_count > row_cap:
        return None
    result = set()
    frames = table.frame[fields].dropna()
    for row in frames.itertuples(index=False, name=None):
        key = tuple(normalize_value(value) for value in row)
        if all(part is not None for part in key):
            result.add(key)
    return result


def _evidence(left_set, right_set, limit):
    shared = sorted(left_set & right_set)
    return [
        {"source_value": list(key), "target_value": list(key)}
        for key in shared[:limit]
    ], len(shared)


def _confidence(coverage, jaccard, uniqueness, naming, weights):
    total = float(sum(weights.values()))
    weighted = (
        coverage * weights["coverage"]
        + jaccard * weights["jaccard"]
        + uniqueness * weights["uniqueness"]
        + naming * weights["naming"]
    )
    return round(weighted / total, 4)


def _existing_single_keys(associations):
    """已有单列关联的表对与列对，用于禁止重复输出。

    列对统一按规范化表对顺序记录（小表名在前），与候选侧对齐。
    """
    table_pairs, column_pairs = set(), set()
    for item in associations or []:
        if FIELD_SEP in item.get("source_field", ""):
            continue
        first, second = sorted((item["source_table"], item["target_table"]))
        table_pairs.add((first, second))
        if item["source_table"] == first:
            left_field, right_field = item["source_field"], item["target_field"]
        else:
            left_field, right_field = item["target_field"], item["source_field"]
        column_pairs.add(((first, second), left_field, right_field))
    return table_pairs, column_pairs


def _evaluate(left_table, right_table, left_fields, right_fields, config,
              degradation, scope, row_cap):
    left_set = tuple_value_set(left_table, left_fields, row_cap)
    right_set = tuple_value_set(right_table, right_fields, row_cap)
    if left_set is None or right_set is None:
        degradation.record(
            "row_cap", scope,
            "表行数超过 max_table_rows={0}，未做元组级评估".format(row_cap),
        )
        return None
    if not left_set or not right_set:
        return None
    # 定向：值域较小的引用侧作为左值，保证覆盖率语义与表遍历顺序无关
    if len(left_set) > len(right_set):
        left_table, right_table = right_table, left_table
        left_fields, right_fields = right_fields, left_fields
        left_set, right_set = right_set, left_set
    shared = left_set & right_set
    section = config["composite"]
    if len(shared) < section["min_matched_tuples"]:
        return None
    coverage = len(shared) / len(left_set)
    jaccard = len(shared) / len(left_set | right_set)
    uniqueness = min(
        len(left_set) / max(left_table.row_count, 1),
        len(right_set) / max(right_table.row_count, 1),
    )
    naming = sum(
        _name_similarity(a, b) for a, b in zip(left_fields, right_fields)
    ) / len(left_fields)
    confidence = _confidence(
        coverage, jaccard, uniqueness, naming, section["weights"]
    )
    if confidence < section["threshold"]:
        return None
    evidence, matched = _evidence(left_set, right_set,
                                  section["evidence_limit"])
    return {
        "confidence": confidence, "evidence": evidence, "matched": matched,
        "coverage": round(coverage, 4), "jaccard": round(jaccard, 4),
        "uniqueness": round(uniqueness, 4), "naming": round(naming, 4),
        "left_cardinality": len(left_set), "right_cardinality": len(right_set),
        "source_table": left_table, "source_fields": list(left_fields),
        "target_table": right_table, "target_fields": list(right_fields),
    }


def detect_composite(dataset, config, single_associations=None):
    """检测两列（可配置放宽到三列）组合构成的表间引用关系。

    返回 (associations, diagnostics)；diagnostics 携带降级原因，
    由流水线写入报告与规则文档。
    """
    section = config["composite"]
    degradation = Degradation()
    if not section["enabled"]:
        return [], degradation.as_dict()
    table_pairs_seen, column_pairs = _existing_single_keys(single_associations)
    tables = sorted(dataset.tables.values(), key=lambda item: item.name)
    result = []
    evaluated = 0
    for index, left_table in enumerate(tables):
        for right_table in tables[index + 1:]:
            scope = "{0} <-> {1}".format(left_table.name, right_table.name)
            pair = (left_table.name, right_table.name)
            candidates = build_candidates(
                left_table, right_table, config, degradation, scope,
            )
            if pair in table_pairs_seen:
                candidates = _filter_known_columns(
                    candidates, left_table.name, right_table.name, column_pairs,
                )
            for left_fields, right_fields, _hits in candidates:
                evaluated += 1
                metrics = _evaluate(
                    left_table, right_table, left_fields, right_fields,
                    config, degradation, scope, section["max_table_rows"],
                )
                if metrics is None:
                    continue
                result.append(_build_association(metrics, section))
    diagnostics = degradation.as_dict()
    diagnostics["evaluated_pairs"] = evaluated
    diagnostics["emitted_relations"] = len(result)
    return sort_associations(result), diagnostics


def _filter_known_columns(candidates, left_name, right_name, column_pairs):
    """表对已有单列关联时，剔除全部成员列均已被单列覆盖的候选。"""
    pair = tuple(sorted((left_name, right_name)))
    known = {(a, b) for (table_pair, a, b) in column_pairs
             if table_pair == pair}
    kept = []
    for left_fields, right_fields, hits in candidates:
        mapped = set(zip(left_fields, right_fields))
        if not mapped or not mapped.issubset(known):
            kept.append((left_fields, right_fields, hits))
    return kept


def _build_association(metrics, section):
    source_table = metrics["source_table"]
    target_table = metrics["target_table"]
    source_fields = metrics["source_fields"]
    target_fields = metrics["target_fields"]
    return make_association(
        source_table.name, FIELD_SEP.join(source_fields),
        target_table.name, FIELD_SEP.join(target_fields),
        "composite_key", metrics["confidence"], "composite_detection",
        evidence=metrics["evidence"],
        details={
            "composite": True,
            "source_fields": list(source_fields),
            "target_fields": list(target_fields),
            "field_separator": FIELD_SEP,
            "width": len(source_fields),
            "matched_tuples": metrics["matched"],
            "coverage_ratio": metrics["coverage"],
            "jaccard": metrics["jaccard"],
            "uniqueness": metrics["uniqueness"],
            "naming_similarity": metrics["naming"],
            "source_tuple_cardinality": metrics["left_cardinality"],
            "target_tuple_cardinality": metrics["right_cardinality"],
            "threshold": section["threshold"],
            "confidence_basis": (
                "加权和: 覆盖率 {0} / Jaccard {1} / 唯一度 {2} / 名称 {3}"
            ).format(section["weights"]["coverage"],
                     section["weights"]["jaccard"],
                     section["weights"]["uniqueness"],
                     section["weights"]["naming"]),
        },
    )
