"""组合键关联检测：候选剪枝、预算控制与降级记录。

组合空间随列数组合爆炸，本模块只负责用轻量元数据与单列信号
把候选压到硬预算内；真正的元组级度量在 metrics.py 中完成。
"""
from itertools import combinations
from ...loader.base_loader import type_compatible
from ..common import normalize_value


class Degradation:
    """记录预算触发情况，供报告向用户解释为何可能漏报。"""

    def record(self, reason, scope, detail):
        self.events.append({
            "reason": reason, "scope": scope, "detail": detail,
        })

    def __init__(self):
        self.events = []

    def as_dict(self):
        return {"degraded": bool(self.events), "events": list(self.events)}


def eligible_columns(table, config):
    """返回允许进入组合的列：排除空列、稀疏列、基数过低列与唯一列。

    含唯一列的组合在单列上即可确定关系，不属于组合键场景，
    直接剔除可同时实现剪枝与“不重复输出”语义。
    """
    section = config["composite"]
    result = []
    for column in table.columns:
        if column["dtype"] == "empty" or table.row_count == 0:
            continue
        if column["non_null_ratio"] < section["min_nonnull_ratio"]:
            continue
        if column["cardinality"] < 2:
            continue
        if column["cardinality"] >= table.row_count:
            continue
        result.append(column)
    return result


def column_value_set(table, field):
    """单列规范化值域，用于信号预筛，避免在组合阶段重复扫描。"""
    if table.frame is None or field not in table.frame.columns:
        return set()
    values = set()
    for raw in table.frame[field].dropna().tolist():
        key = normalize_value(raw)
        if key is not None:
            values.add(key)
    return values


def _compatible_rights(left, right_cols, strict):
    """与左列类型兼容的全部右列。"""
    return [
        right["name"] for right in right_cols
        if type_compatible(left["dtype"], right["dtype"], strict=strict)
    ]


def _signal_map(left_cols, right_cols, sets, config):
    """单列信号预筛：返回左列 -> 存在值域交集的右列集合。"""
    minimum = config["composite"]["min_signal_overlap"]
    strict = config["composite"]["strict_type"]
    mapping = {}
    for left in left_cols:
        hits = set()
        left_set = sets[left["name"]]
        for right in right_cols:
            if not type_compatible(left["dtype"], right["dtype"], strict=strict):
                continue
            if len(left_set & sets[right["name"]]) >= minimum:
                hits.add(right["name"])
        mapping[left["name"]] = hits
    return mapping


def build_candidates(left_table, right_table, config, degradation, scope):
    """生成两表间通过预筛的 (左列组合, 右列组合) 候选，受硬预算约束。

    每个候选至少包含一列命中单列信号；其余成员列只要求类型兼容。
    预算耗尽即停止并登记降级原因，宁可漏报也不跑挂。
    """
    section = config["composite"]
    left_cols = eligible_columns(left_table, config)
    right_cols = eligible_columns(right_table, config)
    if len(left_cols) > section["max_eligible_columns"] or \
            len(right_cols) > section["max_eligible_columns"]:
        degradation.record(
            "eligible_column_cap", scope,
            "合格列数 {0}/{1} 超过上限 {2}，跳过该表对".format(
                len(left_cols), len(right_cols),
                section["max_eligible_columns"]),
        )
        return []
    sets = {}
    for column in left_cols:
        sets[column["name"]] = column_value_set(left_table, column["name"])
    for column in right_cols:
        sets[column["name"]] = column_value_set(right_table, column["name"])
    signals = _signal_map(left_cols, right_cols, sets, config)
    if not any(signals.values()):
        return []
    compatibility = {
        left["name"]: _compatible_rights(
            left, right_cols, section["strict_type"])
        for left in left_cols
    }
    left_names = [column["name"] for column in left_cols]
    candidates = []
    group_count = 0
    for width in range(2, section["max_width"] + 1):
        for left_combo in combinations(left_names, width):
            if not any(signals.get(name) for name in left_combo):
                continue
            group_count += 1
            if group_count > section["max_candidate_groups"]:
                degradation.record(
                    "candidate_group_cap", scope,
                    "候选列组超过上限 {0}，宽度 {1} 的剩余组合未评估".format(
                        section["max_candidate_groups"], width),
                )
                return candidates
            for right_combo in _right_combos(left_combo, compatibility, width):
                if not _has_signal(left_combo, right_combo, signals):
                    continue
                if len(candidates) >= section["max_evaluated_pairs"]:
                    degradation.record(
                        "evaluated_pair_cap", scope,
                        "候选评估对达到上限 {0}，后续组合未评估".format(
                            section["max_evaluated_pairs"]),
                    )
                    return candidates
                candidates.append((list(left_combo), list(right_combo), 0))
    return candidates


def _right_combos(left_combo, compatibility, width):
    """枚举与左列组合逐位类型兼容的右列组合（有序配对，不重列）。"""
    pools = [compatibility.get(name, []) for name in left_combo]
    if any(not pool for pool in pools):
        return []

    def walk(index, chosen):
        if index == width:
            yield tuple(chosen)
            return
        for name in pools[index]:
            if name not in chosen:
                chosen.append(name)
                yield from walk(index + 1, chosen)
                chosen.pop()

    return list(walk(0, []))


def _has_signal(left_combo, right_combo, signals):
    """至少一对对应列命中单列值域信号。"""
    for left_name, right_name in zip(left_combo, right_combo):
        if right_name in signals.get(left_name, set()):
            return True
    return False
