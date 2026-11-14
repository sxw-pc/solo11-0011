"""隐式值域关联检测：Jaccard 重叠、名称相似度、同义词加权与跨来源规范化救援。"""
from difflib import SequenceMatcher
from ..loader.base_loader import type_compatible
from .common import (
    evidence_from_maps, evidence_pairs, make_association, normalize_value,
    sort_associations, value_map,
)
from .value_normalizer import NormalizationCache, chain_trust, detect_chains
_ID_FIELD_CACHE = "_tablelink_id_names"
_DETECT_SAMPLE = 200
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
def _field_chains(candidates, norm_config):
    """按字段名与值形态推断可用规范化链；每个字段只推断一次并缓存。"""
    chains = {}
    for table, column in candidates:
        values = []
        for value in table.frame[column["name"]].dropna().tolist()[:_DETECT_SAMPLE]:
            key = normalize_value(value)
            if key is not None:
                values.append(key)
        chains[(table.name, column["name"])] = detect_chains(column["name"], values, norm_config)
    return chains
def _best_normalized_pair(left_table, left, right_table, right, chains, cache,
                          norm_config, name_score, synonym_score, weights, overlap, sets):
    """两侧分别试跑规范化链，返回按链信任度折算后置信度最高的组合。"""
    best = None
    left_key = (left_table.name, left["name"])
    right_key = (right_table.name, right["name"])
    for left_chain in [None] + chains.get(left_key, []):
        left_entry = {"keys": sets[left_key], "map": None} if left_chain is None \
            else cache.get(left_table, left["name"], left_chain)
        if left_entry is None:
            continue
        for right_chain in [None] + chains.get(right_key, []):
            if left_chain is None and right_chain is None:
                continue
            right_entry = {"keys": sets[right_key], "map": None} if right_chain is None \
                else cache.get(right_table, right["name"], right_chain)
            if right_entry is None:
                continue
            shared = left_entry["keys"] & right_entry["keys"]
            if len(shared) < overlap["min_matched_values"]:
                continue
            jaccard = len(shared) / len(left_entry["keys"] | right_entry["keys"])
            if jaccard < norm_config["min_normalized_jaccard"]:
                continue
            trust = (chain_trust(left_chain, norm_config) if left_chain else 1.0) * \
                (chain_trust(right_chain, norm_config) if right_chain else 1.0)
            effective = jaccard * trust
            confidence = _confidence(effective, name_score, synonym_score, weights)
            if best is None or confidence > best["confidence"]:
                best = {
                    "confidence": confidence, "effective_jaccard": effective,
                    "normalized_jaccard": jaccard, "trust": trust, "matched": len(shared),
                    "left_chain": left_chain, "right_chain": right_chain,
                    "left_entry": left_entry, "right_entry": right_entry,
                }
    return best
def _normalized_details(normalized, source_is_left, jaccard, raw_confidence,
                        name_score, synonym_score, weights, matched, shared_raw):
    source_chain = normalized["left_chain"] if source_is_left else normalized["right_chain"]
    target_chain = normalized["right_chain"] if source_is_left else normalized["left_chain"]
    return {
        "jaccard": round(normalized["effective_jaccard"], 4),
        "name_similarity": round(name_score, 4),
        "synonym_score": synonym_score,
        "weights": dict(weights),
        "matched_values": matched,
        "confidence_basis": "加权和: 值域 {0} / 名称 {1} / 同义词 {2}；值域经规范化链信任度折算".format(
            weights["value"], weights["name"], weights["synonym"]
        ),
        "normalization": {
            "applied": True,
            "source_chain": source_chain or "identity",
            "target_chain": target_chain or "identity",
            "chain_trust": round(normalized["trust"], 4),
            "raw_matched": shared_raw,
            "normalized_matched": normalized["matched"],
            "raw_jaccard": round(jaccard, 4),
            "normalized_jaccard": round(normalized["normalized_jaccard"], 4),
            "effective_jaccard": round(normalized["effective_jaccard"], 4),
            "confidence_raw": raw_confidence,
            "confidence_gain": round(normalized["confidence"] - raw_confidence, 4),
        },
    }
def detect_overlap(dataset, config, diagnostics=None):
    """对全量字段两两比较，输出达到阈值的隐式关联。

    启用 overlap.normalization 时，原始置信度未达阈值的候选对进入规范化
    救援路径；字段降级与缓存规模等诊断信息写入 diagnostics。
    """
    overlap = config["overlap"]
    weights = overlap["weights"]
    norm_config = overlap.get("normalization") or {}
    norm_enabled = bool(norm_config.get("enabled"))
    synonym_map = config["explicit"]["naming"]["synonym_map"]
    id_names = _id_name_index(dataset)
    sets = _field_sets(dataset)
    candidates = []
    for table in dataset.tables.values():
        for column in table.columns:
            if _eligible(dataset, table, column, config, id_names):
                candidates.append((table, column))
    chains = _field_chains(candidates, norm_config) if norm_enabled else {}
    cache = NormalizationCache(norm_config, diagnostics) if norm_enabled else None
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
            name_score = _name_similarity(left["name"], right["name"])
            synonym_score = _synonym_score(left["name"], right["name"], synonym_map)
            jaccard = len(shared) / len(union)
            confidence = _confidence(jaccard, name_score, synonym_score, weights)
            raw_confidence = confidence
            normalized = None
            if len(shared) >= overlap["min_matched_values"] and confidence >= overlap["threshold"]:
                pass
            elif norm_enabled:
                normalized = _best_normalized_pair(
                    left_table, left, right_table, right, chains, cache, norm_config,
                    name_score, synonym_score, weights, overlap, sets,
                )
                if normalized is None or normalized["confidence"] < overlap["threshold"]:
                    continue
                confidence = normalized["confidence"]
            else:
                continue
            if _orientation(left, right, left_table, right_table):
                source_table, source, target_table, target = left_table, left, right_table, right
            else:
                source_table, source, target_table, target = right_table, right, left_table, left
            if normalized is None:
                evidence, matched = evidence_pairs(
                    source_table, source["name"], target_table, target["name"],
                    limit=overlap["evidence_limit"],
                )
                details = {
                    "jaccard": round(jaccard, 4),
                    "name_similarity": round(name_score, 4),
                    "synonym_score": synonym_score,
                    "weights": dict(weights),
                    "matched_values": matched,
                    "confidence_basis": "加权和: 值域 {0} / 名称 {1} / 同义词 {2}".format(
                        weights["value"], weights["name"], weights["synonym"]
                    ),
                }
                if norm_enabled:
                    details["normalization"] = {
                        "applied": False, "reason": "raw_passed", "raw_matched": len(shared),
                    }
            else:
                source_is_left = source is left
                source_chain = normalized["left_chain"] if source_is_left else normalized["right_chain"]
                target_chain = normalized["right_chain"] if source_is_left else normalized["left_chain"]
                source_entry = normalized["left_entry"] if source_is_left else normalized["right_entry"]
                target_entry = normalized["right_entry"] if source_is_left else normalized["left_entry"]
                source_map = source_entry["map"] if source_chain else \
                    value_map(source_table, source["name"])
                target_map = target_entry["map"] if target_chain else \
                    value_map(target_table, target["name"])
                evidence, matched = evidence_from_maps(
                    source_map, target_map, limit=overlap["evidence_limit"],
                )
                details = _normalized_details(
                    normalized, source_is_left, jaccard, raw_confidence,
                    name_score, synonym_score, weights, matched, len(shared),
                )
                if diagnostics is not None:
                    diagnostics["rescued"] = diagnostics.get("rescued", 0) + 1
            if len(evidence) < overlap["min_matched_values"]:
                continue
            result.append(make_association(
                source_table.name, source["name"], target_table.name, target["name"],
                "value_overlap", confidence, "value_overlap",
                evidence=evidence,
                details=details,
            ))
    if diagnostics is not None and norm_enabled:
        diagnostics["cache_entries"] = cache.size
    return sort_associations(result)
