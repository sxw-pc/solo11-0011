"""端点归并对外入口：开关、计划、重写、映射清单与统计。"""
from .engine import mapping_document, plan_merge
from .rewrite import history, rewrite
def merged_endpoints(config):
    """返回归并配置；关闭时 None，调用方保持旧流程字节级不变。"""
    section = (config or {}).get("merge")
    if not section or not section.get("enabled"):
        return None
    return section
def build_plan(dataset, config):
    section = merged_endpoints(config)
    if section is None:
        return None
    return plan_merge(dataset, section)
def map_relationships(associations, plan):
    return rewrite(associations, plan)
def map_baseline(records, plan):
    return history(records, plan)
def document(plan):
    return mapping_document(plan)
def anomaly_notes(plan, limit=6):
    """把降级项转成报告异常关联提示的可读条目。"""
    if not plan or not plan["fallbacks"]:
        return []
    reasons = {
        "source_missing": "来源缺失",
        "field_set_mismatch": "字段集合不一致",
        "primary_key_mismatch": "推断主键不一致",
        "value_domain_too_low": "主键值域交集不足",
        "kept_separate": "结构不同保持独立",
        "not_merged": "未满足归并条件",
    }
    notes = []
    for item in plan["fallbacks"][:limit]:
        label = reasons.get(item["reason"], item["reason"])
        against = item.get("against")
        text = "端点归并降级：{0} 保留原始端点（{1}）".format(
            item["original_table"], label
        )
        if against:
            text += "，未并入 {0}".format(against)
        notes.append(text)
    if len(plan["fallbacks"]) > limit:
        notes.append("端点归并降级：另有 {0} 项未展开，详见映射清单 fallbacks。".format(
            len(plan["fallbacks"]) - limit))
    return notes
