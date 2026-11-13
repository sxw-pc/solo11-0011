"""显式关联检测：SQLite 外键、命名规则与人工自定义规则。"""
import os
import re
import yaml
from ..exceptions import ConfigError
from ..loader.fk_metadata import (
    action_confidence,
    join_fields,
    normalize_action,
    referred_key,
)
from .common import (
    _json_scalar,
    evidence_pairs,
    make_association,
    normalize_value,
    sort_associations,
    value_map,
)
_TOKEN_RE = re.compile(r"[^a-z0-9]+")
def _tokens(name):
    return [item for item in _TOKEN_RE.split(str(name).lower()) if item]
def _base_name(name):
    tokens = _tokens(name)
    if tokens and tokens[-1] == "id":
        tokens = tokens[:-1]
    return tokens[-1] if tokens else ""
def _synonym_score(left, right, synonym_map):
    left_base = _base_name(left)
    right_base = _base_name(right)
    if not left_base or not right_base:
        return 0.0
    if left_base == right_base:
        return 1.0
    for key, values in synonym_map.items():
        group = {str(key).lower()} | {str(item).lower() for item in values}
        if left_base in group and right_base in group:
            return 1.0
    return 0.0
def _key_fields(table):
    """识别目标表的主键列；CSV 用首个唯一 ID 列作为主键近似。"""
    if table.primary_keys:
        return [name for name in table.primary_keys if table.column(name)]
    candidates = []
    for index, column in enumerate(table.columns):
        name = column["name"]
        if not name.lower().endswith("_id"):
            continue
        if table.row_count and column["cardinality"] == table.row_count:
            candidates.append((index, name))
    return [candidates[0][1]] if candidates else []
def _tuple_map(table, fields):
    """复合键的 规范化元组 -> 原始元组 映射。"""
    if table.frame is None or any(field not in table.frame.columns for field in fields):
        return {}
    mapping = {}
    for row in table.frame[list(fields)].dropna().itertuples(index=False, name=None):
        key = tuple(normalize_value(value) for value in row)
        if all(value is not None for value in key) and key not in mapping:
            mapping[key] = row
    return mapping
def _composite_association(table, fk, target):
    """复合外键作为一条整体记录；列序与行为动作取自结构化外键描述。"""
    columns = list(fk["columns"])
    referred = list(fk["referred_columns"])
    left = _tuple_map(table, columns)
    right = _tuple_map(target, referred)
    shared = sorted(set(left).intersection(right))
    evidence = [{
        "source_value": [_json_scalar(value) for value in left[key]],
        "target_value": [_json_scalar(value) for value in right[key]],
    } for key in shared[:5]]
    return make_association(
        table.name, join_fields(columns), target.name, join_fields(referred),
        "explicit_fk", action_confidence(fk.get("on_delete"), fk.get("on_update")),
        "sqlite_foreign_key",
        evidence=evidence,
        details={
            "constraint": fk.get("name", ""),
            "composite": True,
            "source_fields": columns,
            "target_fields": referred,
            "referred_schema": fk.get("referred_schema"),
            "on_delete": normalize_action(fk.get("on_delete")),
            "on_update": normalize_action(fk.get("on_update")),
            "matched_values": len(shared),
            "message": "SQLite 原生复合外键约束",
        },
    )
def _warn_once(dataset, table, message):
    """外键异常降级为提示且不重复记录，不中止整轮检测。"""
    if not any(item["message"] == message and item["source"] == table.source_name
               for item in dataset.errors):
        dataset.add_error(table.source_name, message, kind="warning")
def _native_associations(dataset):
    result = []
    for table in dataset.tables.values():
        for fk in table.foreign_keys:
            target = dataset.tables.get(referred_key(fk)) or \
                dataset.tables.get(fk.get("referred_table") or "")
            if target is None:
                _warn_once(dataset, table, "外键 {0} 引用的表 {1} 未加载，已跳过该约束".format(
                    fk.get("name") or "<未命名>", referred_key(fk) or fk.get("referred_table")))
                continue
            columns = list(fk.get("columns") or [])
            referred = list(fk.get("referred_columns") or [])
            if len(columns) > 1:
                if len(columns) != len(referred):
                    _warn_once(dataset, table, "外键 {0} 的列数与目标列数不一致，已跳过该约束".format(
                        fk.get("name") or "<未命名>"))
                elif all(table.column(name) and target.column(ref)
                         for name, ref in zip(columns, referred)):
                    result.append(_composite_association(table, fk, target))
                continue
            for source_field, target_field in zip(columns, referred):
                if not table.column(source_field) or not target.column(target_field):
                    continue
                evidence, matched = evidence_pairs(
                    table, source_field, target, target_field, limit=5
                )
                result.append(make_association(
                    table.name, source_field, target.name, target_field,
                    "explicit_fk", 1.0, "sqlite_foreign_key",
                    evidence=evidence,
                    details={
                        "constraint": fk.get("name", ""),
                        "matched_values": matched,
                        "message": "SQLite 原生外键约束",
                    },
                ))
    return result
def _naming_associations(dataset, config):
    naming = config["explicit"]["naming"]
    if not naming["enabled"]:
        return []
    suffixes = [item.lower() for item in naming["suffixes"]]
    result = []
    for source in dataset.tables.values():
        for source_column in source.columns:
            source_field = source_column["name"]
            if not any(source_field.lower().endswith(item) for item in suffixes):
                continue
            for target in dataset.tables.values():
                if target.name == source.name:
                    continue
                for target_field in _key_fields(target):
                    if not _is_naming_match(source_field, target.name, target_field,
                                            naming["synonym_map"]):
                        continue
                    evidence, matched = evidence_pairs(
                        source, source_field, target, target_field,
                        limit=config["overlap"]["evidence_limit"],
                    )
                    source_values = value_map(source, source_field)
                    ratio = matched / len(source_values) if source_values else 0.0
                    if matched < naming["min_matched_values"] or \
                            ratio < naming["min_overlap_ratio"]:
                        continue
                    exact = source_field.lower() == target_field.lower()
                    table_match = _base_name(source_field) in _tokens(target.name)
                    confidence = naming["confidence"]
                    if table_match:
                        confidence = max(confidence, naming["table_name_confidence"])
                    result.append(make_association(
                        source.name, source_field, target.name, target_field,
                        "explicit_naming", confidence, "naming_rule",
                        evidence=evidence,
                        details={
                            "rule": "same_field" if exact else "table_or_synonym",
                            "matched_values": matched,
                            "match_ratio": round(ratio, 4),
                            "message": "字段命名规则命中且存在值域交集",
                        },
                    ))
    return result
def _is_naming_match(source_field, target_table, target_field, synonym_map):
    if source_field.lower() == target_field.lower():
        return True
    if _base_name(source_field) in _tokens(target_table):
        return True
    return _synonym_score(source_field, target_field, synonym_map) >= 1.0
def _load_custom_rules(path, dataset):
    if not path:
        return []
    if not os.path.isfile(path):
        raise ConfigError(path, "explicit.custom_rules_path", "自定义规则文件不存在", "填写存在的 YAML 路径或留空")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(path, "<yaml>", "自定义规则解析失败: {0}".format(exc), "检查 YAML 缩进与字段")
    rules = payload.get("rules") if isinstance(payload, dict) else None
    if not isinstance(rules, list):
        raise ConfigError(path, "rules", "rules 必须是列表", "按示例编写 rules: []")
    result = []
    for index, rule in enumerate(rules):
        prefix = "rules[{0}]".format(index)
        if not isinstance(rule, dict):
            raise ConfigError(path, prefix, "规则必须是映射", "检查列表项的缩进")
        source = _split_field_rule(path, prefix, rule.get("source"), dataset)
        target = _split_field_rule(path, prefix, rule.get("target"), dataset)
        confidence = rule.get("confidence", 1.0)
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) \
                or not 0 <= confidence <= 1:
            raise ConfigError(path, prefix + ".confidence", "置信度应在 0~1", "填写 0.0 到 1.0 的数字")
        table, field = source
        target_table, target_field = target
        evidence, matched = evidence_pairs(table, field, target_table, target_field, limit=5)
        result.append(make_association(
            table.name, field, target_table.name, target_field,
            "custom", float(confidence), "custom_rule",
            evidence=evidence,
            details={
                "rule_index": index,
                "declared_relation": str(rule.get("relation", "reference")),
                "note": str(rule.get("note", "")),
                "matched_values": matched,
                "message": "人工规则，优先级最高",
            },
        ))
    return result
def _split_field_rule(path, prefix, value, dataset):
    if not isinstance(value, str) or value.count(".") != 1:
        raise ConfigError(path, prefix + ".source/target", "字段引用格式应为 表名.字段名", "例如 device_base.device_id")
    table_name, field_name = value.split(".", 1)
    table = dataset.tables.get(table_name)
    if table is None:
        raise ConfigError(path, prefix, "表 {0} 不存在".format(table_name), "检查表名拼写")
    if not table.column(field_name):
        raise ConfigError(path, prefix, "字段 {0} 不存在".format(field_name), "检查字段名拼写")
    return table, field_name
def detect_explicit(dataset, config, base_dir=None):
    """返回全部显式关联；自定义规则缺失或非法时抛出 ConfigError。"""
    result = _native_associations(dataset)
    result.extend(_naming_associations(dataset, config))
    custom_path = config["explicit"].get("custom_rules_path")
    if custom_path:
        if not os.path.isabs(custom_path):
            custom_path = os.path.join(base_dir or os.getcwd(), custom_path)
        result.extend(_load_custom_rules(custom_path, dataset))
    return sort_associations(result)
