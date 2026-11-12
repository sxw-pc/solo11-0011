"""端点归并规划：名称归一召回、结构指纹判定、值域守卫与降级登记。"""
import hashlib
from .fingerprint import (
    canonical_table_name,
    representative,
    strip_source_suffix,
    table_fingerprint,
    value_guard,
)
def _opt(config, key, default):
    return (config or {}).get(key, default)
def _cluster_id(name):
    return "merged_" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
def _group_key(table, config):
    """召回键：剥离加载器来源后缀，并按可配置策略排序表名 token。"""
    return canonical_table_name(
        table,
        token_order=_opt(config, "token_order_insensitive", True),
        suffix_strip=_opt(config, "strip_source_suffix", True),
    )
def _compatible(left, right, config):
    """结构同构 = 字段集合 + 推断主键一致；随后再做主键值域守卫。"""
    left_fp = left["fingerprint"]
    right_fp = right["fingerprint"]
    if left_fp["field_keys"] != right_fp["field_keys"]:
        return False, {"available": False, "passed": False,
                       "reason": "field_set_mismatch", "jaccard": None}
    if left_fp["primary_key_keys"] != right_fp["primary_key_keys"]:
        return False, {"available": False, "passed": False,
                       "reason": "primary_key_mismatch", "jaccard": None}
    return True, value_guard(left["table"], right["table"], left_fp, config)
def _fallback(table, reason, against=None, detail=None, group=None):
    return {
        "original_table": table.name,
        "candidate_unified_table": group,
        "against": against,
        "reason": reason,
        "detail": dict(detail or {}),
    }
def _split_group(group_name, members, config):
    """簇内成员逐个校验；合并失败的成员保留为独立簇并登记降级原因。"""
    clusters = []
    fallbacks = []
    for table in members:
        entry = {"table": table, "fingerprint": table_fingerprint(table)}
        if not str(getattr(table, "source_name", "") or "").strip():
            fallbacks.append(_fallback(table, "source_missing", group=group_name))
            clusters.append({"entries": [entry], "guards": [], "isolated": True})
            continue
        joined = False
        blocked = None
        blocked_against = None
        for cluster in clusters:
            if cluster.get("isolated"):
                continue
            first = cluster["entries"][0]
            compatible, guard = _compatible(first, entry, config)
            if not compatible:
                blocked = blocked or guard
                blocked_against = blocked_against or first["table"].name
                continue
            if not guard.get("passed"):
                blocked = guard
                blocked_against = first["table"].name
                continue
            cluster["entries"].append(entry)
            cluster["guards"].append(dict(guard, against=first["table"].name,
                                          member=table.name))
            joined = True
            break
        if joined:
            continue
        clusters.append({"entries": [entry], "guards": []})
        if blocked:
            fallbacks.append(_fallback(
                table, blocked.get("reason", "not_merged"),
                against=blocked_against, detail=blocked, group=group_name,
            ))
    if len(members) > 1:
        for cluster in clusters:
            if len(cluster["entries"]) == 1 and not cluster.get("isolated"):
                table = cluster["entries"][0]["table"]
                if not any(item["original_table"] == table.name
                           for item in fallbacks):
                    fallbacks.append(_fallback(table, "kept_separate",
                                               group=group_name))
    return clusters, fallbacks
def _candidate_names(cluster, config):
    names = []
    for entry in cluster["entries"]:
        table = entry["table"]
        stripped = strip_source_suffix(
            table.name, table.source_type,
            _opt(config, "strip_source_suffix", True),
        )
        names.append(stripped or table.name)
    return sorted(set(names), key=lambda item: (item.lower(), item))
def _allocate_names(clusters, config):
    """统一端点命名：多成员簇取去后缀名，字典序最小；冲突追加固定序号。"""
    taken = set()
    for cluster in clusters:
        if len(cluster["entries"]) == 1:
            name = cluster["entries"][0]["table"].name
        else:
            name = _candidate_names(cluster, config)[0]
        base = name
        suffix = 2
        while name in taken:
            name = "{0}_{1}".format(base, suffix)
            suffix += 1
        cluster["name"] = name
        taken.add(name)
def _field_aliases(members):
    aliases = {}
    for table in members:
        for column in table.columns:
            aliases.setdefault(column["name"].lower(), set()).add(column["name"])
    return {key: sorted(values)[0] for key, values in sorted(aliases.items())}
def plan_merge(dataset, config):
    """计算归并计划；开关关闭时返回 None，调用方保持旧流程不变。"""
    if not _opt(config, "enabled", False):
        return None
    grouped = {}
    for name in sorted(dataset.tables):
        table = dataset.tables[name]
        grouped.setdefault(_group_key(table, config), []).append(table)
    clusters = []
    fallbacks = []
    for group_name in sorted(grouped):
        members = sorted(grouped[group_name],
                         key=lambda item: (item.name.lower(), item.name))
        parts, drops = _split_group(group_name, members, config)
        clusters.extend(parts)
        fallbacks.extend(drops)
    _allocate_names(clusters, config)
    unified = {}
    mapping = []
    for cluster in clusters:
        members = [entry["table"] for entry in cluster["entries"]]
        cluster["members"] = sorted(table.name for table in members)
        cluster["representative"] = representative(members)
        cluster["aliases"] = _field_aliases(members)
        cluster["id"] = _cluster_id(cluster["name"])
        cluster["mapping"] = []
        for entry in cluster["entries"]:
            table = entry["table"]
            guard = None
            if len(cluster["entries"]) == 1:
                guard = {"available": False, "passed": True, "jaccard": None,
                         "reason": "single_endpoint_no_pairwise_check"}
            else:
                for item in cluster["guards"]:
                    if item.get("member") == table.name:
                        guard = item
                        break
                if guard is None:
                    paired = sorted(item["against"] for item in cluster["guards"]
                                    if item.get("against") == table.name)
                    guard = {"available": True, "passed": True, "jaccard": None,
                             "reason": "anchor_for_merged_members",
                             "against": paired} if paired else {
                        "available": False, "passed": True, "jaccard": None,
                        "reason": "no_pairwise_record"}
            record = {
                "original_table": table.name,
                "original_source_type": table.source_type,
                "original_source_name": table.source_name,
                "unified_table": cluster["name"],
                "role": "anchor" if (len(cluster["entries"]) > 1 and guard.get("reason")
                                     == "anchor_for_merged_members") else "member",
                "basis": {
                    "normalized_name": _group_key(table, config),
                    "field_set": entry["fingerprint"]["fields"],
                    "inferred_primary_keys": entry["fingerprint"]["primary_keys"],
                    "structure_digest": entry["fingerprint"]["digest"],
                    "value_guard": guard,
                },
                "field_map": {
                    column["name"]: cluster["aliases"].get(
                        column["name"].lower(), column["name"])
                    for column in table.columns
                },
            }
            mapping.append(record)
            cluster["mapping"].append(record)
            unified[table.name] = cluster
    return {
        "config": config,
        "clusters": clusters,
        "unified": unified,
        "mapping": mapping,
        "fallbacks": fallbacks,
        "stats": {
            "cluster_count": len(clusters),
            "merged_endpoint_count": len(mapping),
            "multi_member_cluster_count": sum(
                1 for cluster in clusters if len(cluster["members"]) > 1),
            "fallback_count": len(fallbacks),
            "strategy": "structure_fingerprint_with_value_guard",
        },
    }
def mapping_document(plan):
    """构造可复核的归并映射清单；每条记录解释归并依据。"""
    if plan is None:
        return None
    return {
        "schema_version": "1.0",
        "enabled": True,
        "strategy": {
            "recall": "strip loader source suffix then sort table-name tokens",
            "identify": "ordered field-name set plus inferred primary keys",
            "guard": "primary-key value-domain Jaccard; rejects same-name/different-data",
            "fallback": "keep original endpoint, record reason, add report anomaly note",
            "naming": "shortest stripped member name, sorted tie-break, byte-stable",
        },
        "stats": dict(plan["stats"]),
        "clusters": [
            {
                "unified_table": cluster["name"],
                "unified_id": cluster["id"],
                "representative": cluster["representative"].name,
                "members": list(cluster["members"]),
                "field_aliases": dict(cluster["aliases"]),
                "basis": {
                    "field_set": cluster["entries"][0]["fingerprint"]["fields"],
                    "inferred_primary_keys":
                        cluster["entries"][0]["fingerprint"]["primary_keys"],
                    "structure_digest":
                        cluster["entries"][0]["fingerprint"]["digest"],
                    "value_guard": [
                        dict(item) for item in cluster["guards"]
                    ],
                },
            }
            for cluster in plan["clusters"]
        ],
        "endpoint_map": plan["mapping"],
        "fallbacks": plan["fallbacks"],
    }
