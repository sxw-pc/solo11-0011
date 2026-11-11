"""隐式值域关联检测：Jaccard 重叠、名称相似度与同义词加权。"""
from difflib import SequenceMatcher
from ..loader.base_loader import type_compatible
from .common import evidence_pairs, make_association, normalize_value, sort_associations
_ID_FIELD_CACHE = "_tablelink_id_names"
def _name_similarity(left, right):
    left_key = left.lower().replace("_", "")
    right_key = right.lower().replace("_", "")
    return SequenceMatcher(None, left_key, right_key).ratio()
def _base_token(name):
    tokens = [item for item in name.lower().split("_") if item]
    if tokens and tokens[-1] == "id":
        tokens = tokens[:-1]
    return tokens[-1] if tokens else ""
def _synonym_score(left, right, synonym_map):
    left_base = _base_token(left)
    right_base = _base_token(right)
    if left_base and left_base == right_base:
        return 1.0
    for key, values in synonym_map.items():
        group = {str(key).lower()} | {str(item).lower() for item in values}
        if left_base in group and right_base in group:
            return 1.0
    return 0.0
def _field_sets(dataset):
    sets = {}
    for table in dataset.tables.values():
        if table.frame is None:
            continue
        for column in table.columns:
            keys = set()
            for value in table.frame[column["name"]].dropna().tolist():
                key = normalize_value(value)
                if key is not None:
                    keys.add(key)
            sets[(table.name, column["name"])] = keys
    return sets
def _high_cardinality_exempt(dataset, table, column, id_names):
    if not column["name"].lower().endswith("_id"):
        return False
    name = column["name"].lower()
    return any(owner != table.name and name in names for owner, names in id_names.items())
def _id_name_index(dataset):
    result = {}
    for table in dataset.tables.values():
        result[table.name] = {col["name"].lower() for col in table.columns}
    return result
def _eligible(dataset, table, column, config, id_names):
    overlap = config["overlap"]
    if column["dtype"] == "empty" or table.row_count == 0:
        return False
    if column["non_null_ratio"] < overlap["min_nonnull_ratio"]:
        return False
    if column["cardinality"] < overlap["min_matched_values"]:
        return False
    high_cardinality = column["cardinality"] > overlap["max_cardinality_ratio"] * table.row_count
    if high_cardinality:
        exempt = overlap["allow_reference_high_cardinality"] and \
            _high_cardinality_exempt(dataset, table, column, id_names)
        if not exempt:
            return False
    return True
def _orientation(left, right, left_table, right_table):
    if left_table.row_count == 0 or right_table.row_count == 0:
        return True
    left_unique = left["cardinality"] == left_table.row_count
    right_unique = right["cardinality"] == right_table.row_count
    if left_unique and not right_unique:
        return False
    if right_unique and not left_unique:
        return True
    if left_table.name == right_table.name:
        return left["name"] <= right["name"]
    return (left_table.name, left["name"]) <= (right_table.name, right["name"])
def _confidence(jaccard, name_score, synonym_score, weights):
    total = float(weights["value"] + weights["name"] + weights["synonym"])
    weighted = (
        jaccard * float(weights["value"])
        + name_score * float(weights["name"])
        + synonym_score * float(weights["synonym"])
    )
    return round(weighted / total, 4)
def detect_overlap(dataset, config):
    """对全量字段两两比较，输出达到阈值的隐式关联。"""
    overlap = config["overlap"]
    weights = overlap["weights"]
    synonym_map = config["explicit"]["naming"]["synonym_map"]
    id_names = _id_name_index(dataset)
    sets = _field_sets(dataset)
    candidates = []
    for table in dataset.tables.values():
        for column in table.columns:
            if _eligible(dataset, table, column, config, id_names):
                candidates.append((table, column))
    result = []
    compared = 0
    for index, (left_table, left) in enumerate(candidates):
        for right_table, right in candidates[index + 1:]:
            if left_table.name == right_table.name and not overlap["same_table"]:
                continue
            if not type_compatible(
                    left["dtype"], right["dtype"], strict=overlap["strict_type"]):
                continue
            if compared >= overlap["max_pairs"]:
                return sort_associations(result)
            compared += 1
            left_set = sets.get((left_table.name, left["name"]), set())
            right_set = sets.get((right_table.name, right["name"]), set())
            if not left_set or not right_set:
                continue
            union = left_set | right_set
            shared = left_set & right_set
            if len(shared) < overlap["min_matched_values"]:
                continue
            jaccard = len(shared) / len(union)
            name_score = _name_similarity(left["name"], right["name"])
            synonym_score = _synonym_score(left["name"], right["name"], synonym_map)
            confidence = _confidence(jaccard, name_score, synonym_score, weights)
            if confidence < overlap["threshold"]:
                continue
            if _orientation(left, right, left_table, right_table):
                source_table, source, target_table, target = left_table, left, right_table, right
            else:
                source_table, source, target_table, target = right_table, right, left_table, left
            evidence, matched = evidence_pairs(
                source_table, source["name"], target_table, target["name"],
                limit=overlap["evidence_limit"],
            )
            if len(evidence) < overlap["min_matched_values"]:
                continue
            result.append(make_association(
                source_table.name, source["name"], target_table.name, target["name"],
                "value_overlap", confidence, "value_overlap",
                evidence=evidence,
                details={
                    "jaccard": round(jaccard, 4),
                    "name_similarity": round(name_score, 4),
                    "synonym_score": synonym_score,
                    "weights": dict(weights),
                    "matched_values": matched,
                    "confidence_basis": "加权和: 值域 {0} / 名称 {1} / 同义词 {2}".format(
                        weights["value"], weights["name"], weights["synonym"]
                    ),
                },
            ))
    return sort_associations(result)
