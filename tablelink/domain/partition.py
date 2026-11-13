"""确定性加权聚类：表级加权边、并查集、切分、桥接表、域命名与结果组装。

两阶段算法（保证桥接表不会先把多个域粘成一个连通分量）：
1. 在强边无向图上对每个候选表独立评估：临时摘除它后做并查集，只保留成员
   数 >=2 的域级分量（摘除核心表导致叶子坍缩的单点分量不计，避免误伤域内
   枢纽）；强邻接覆盖 >=bridge_min_domains 个域级分量即为边界表，一律不进
   域，其中次强分量达到最强分量 bridge_balance_ratio 比例的标为桥接表，
   其余弱边界表进未分组清单。所有候选共享同一参考全图，结果与遍历顺序无关。
2. 摘除全部边界表后做单链并查集，超大分量按最弱内边确定性切分；成员 >=2
   的分量成为主题域，单点表进未分组。全程无随机数，并列按名称字典序裁决。
"""
import re
from .config import build_domain_settings
_TOKEN_RE = re.compile(r"[a-z0-9]+|[一-鿿]+")
_STOP_TOKENS = {"info", "base", "record", "table", "data", "list", "detail",
                "log", "tmp", "temp", "rel", "map", "item"}
def id_by_domain(index):
    return "domain_{0:02d}".format(index + 1)
def aggregate_table_edges(associations, relation_weights):
    """字段级关联折叠为无向表级加权边，权重 = sum(置信度 × 关系类型权重)。"""
    totals, meta = {}, {}
    for item in associations:
        left, right = item.get("source_table"), item.get("target_table")
        if not left or not right or left == right:
            continue
        pair = tuple(sorted((left, right)))
        relation_type = item.get("relation_type", "unknown")
        totals[pair] = totals.get(pair, 0.0) + float(
            item.get("confidence", 0.0)) * float(relation_weights.get(relation_type, 0.0))
        entry = meta.setdefault(pair, {"types": set(), "count": 0})
        entry["types"].add(relation_type)
        entry["count"] += 1
    return [{
        "left": pair[0], "right": pair[1], "weight": round(totals[pair], 4),
        "relation_types": sorted(meta[pair]["types"]),
        "association_count": meta[pair]["count"],
    } for pair in sorted(totals)]
def suggest_domain_name(members, core_table, top_n=5):
    """高频词优先命名，词频并列按 token 字典序裁决；无可用词回退核心表名。"""
    counts = {}
    for table in members:
        for token in set(_TOKEN_RE.findall(str(table).lower())):
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(((t, c) for t, c in counts.items()
                     if t not in _STOP_TOKENS and not t.isdigit()),
                    key=lambda pair: (-pair[1], pair[0]))
    evidence = {"core_table": core_table,
                "token_frequency": [{"token": t, "table_count": c}
                                    for t, c in ranked[:top_n]]}
    if ranked:
        evidence.update(name_basis="high_frequency_token", matched_tables=ranked[0][1])
        return ranked[0][0], evidence
    evidence.update(name_basis="core_table", matched_tables=1)
    return core_table, evidence
def _components(nodes, edges):
    """并查集：返回成员按名称排序的连通分量（按首成员字典序）。"""
    parent = {name: name for name in nodes}
    def find(name):
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name
    for left, right in edges:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[max(root_left, root_right)] = min(root_left, root_right)
    groups = {}
    for name in sorted(nodes):
        groups.setdefault(find(name), []).append(name)
    return sorted(groups.values(), key=lambda members: members[0])
def _split_component(members, internal, max_size):
    """超大分量按最弱内边反复切分；同权重取字典序最大边，全程确定性。"""
    pieces, internal = [sorted(members)], list(internal)
    while any(len(piece) > max_size for piece in pieces):
        target = next(piece for piece in pieces if len(piece) > max_size)
        member_set = set(target)
        candidates = [e for e in internal
                      if e["left"] in member_set and e["right"] in member_set]
        cut = sorted(candidates, key=lambda e: (e["weight"], e["left"], e["right"]))[0]
        internal = [e for e in internal if e is not cut]
        sub_edges = [(e["left"], e["right"]) for e in internal
                     if e["left"] in member_set and e["right"] in member_set]
        divided = _components(target, sub_edges)
        pieces = [p for p in pieces if p is not target] + divided
        pieces.sort(key=lambda piece: piece[0])
    return pieces
def _initial_components(nodes, strong_edges, max_size):
    result = []
    for members in _components(nodes, [(e["left"], e["right"]) for e in strong_edges]):
        member_set = set(members)
        internal = [e for e in strong_edges
                    if e["left"] in member_set and e["right"] in member_set]
        result.extend(_split_component(members, internal, max_size)
                      if len(members) > max_size else [sorted(members)])
    return sorted(result, key=lambda members: members[0])
def _neighbor_weights(candidate, strong_edges, comp_of, active_set):
    per_component = {}
    for edge in strong_edges:
        if edge["left"] == candidate:
            other = edge["right"]
        elif edge["right"] == candidate:
            other = edge["left"]
        else:
            continue
        comp = comp_of.get(other) if other in active_set else None
        if comp is not None:
            per_component[comp] = round(per_component.get(comp, 0.0) + edge["weight"], 4)
    return per_component
def _identify_boundary_tables(nodes, strong_edges, min_domains, balance_ratio):
    """独立评估每个候选，返回 (桥接表->分量权重, 弱边界表集合)。"""
    bridges, weak_boundary = {}, set()
    for candidate in sorted(nodes):
        active = [name for name in nodes if name != candidate]
        active_set = set(active)
        edges = [(e["left"], e["right"]) for e in strong_edges
                 if e["left"] in active_set and e["right"] in active_set]
        components = [m for m in _components(active, edges) if len(m) > 1]
        comp_of = {table: idx for idx, members in enumerate(components)
                   for table in members}
        per_component = _neighbor_weights(candidate, strong_edges, comp_of, active_set)
        if len(per_component) < min_domains:
            continue
        ordered = sorted(per_component.values(), reverse=True)
        if ordered[1] >= ordered[0] * balance_ratio:
            bridges[candidate] = per_component
        else:
            weak_boundary.add(candidate)
    return bridges, weak_boundary
def _domain_payload(index, members, strong_edges):
    member_set = set(members)
    internal = [e for e in strong_edges
                if e["left"] in member_set and e["right"] in member_set]
    strength = {}
    for edge in internal:
        strength[edge["left"]] = round(strength.get(edge["left"], 0.0) + edge["weight"], 4)
        strength[edge["right"]] = round(strength.get(edge["right"], 0.0) + edge["weight"], 4)
    core = sorted(members, key=lambda name: (-strength.get(name, 0.0), name))[0]
    name, token_stats = suggest_domain_name(members, core)
    return {
        "domain_id": id_by_domain(index), "name": name, "core_table": core,
        "tables": sorted(members), "table_count": len(members),
        "internal_edge_count": len(internal),
        "total_internal_weight": round(sum(e["weight"] for e in internal), 4),
        "name_evidence": token_stats,
    }
def partition_domains(all_tables, associations, settings):
    """执行完整确定性划分；all_tables 为数据集内全部表名（含孤立表）。"""
    relation_weights, threshold = settings["relation_weights"], settings["edge_weight_threshold"]
    table_edges = aggregate_table_edges(associations, relation_weights)
    nodes = sorted(all_tables)
    strong_edges = sorted((e for e in table_edges if e["weight"] >= threshold),
                          key=lambda e: (-e["weight"], e["left"], e["right"]))
    bridges, weak_boundary = _identify_boundary_tables(
        nodes, strong_edges, settings["bridge_min_domains"],
        settings["bridge_balance_ratio"])
    kept_set = set(nodes) - set(bridges) - weak_boundary
    kept_edges = [e for e in strong_edges
                  if e["left"] in kept_set and e["right"] in kept_set]
    components = _initial_components(sorted(kept_set), kept_edges, settings["max_domain_size"])
    domains = [sorted(m) for m in components if len(m) > 1]
    comp_of = {table: idx for idx, members in enumerate(domains) for table in members}
    payload_domains = [_domain_payload(idx, members, kept_edges)
                       for idx, members in enumerate(domains)]
    bridge_payload, demoted = [], []
    for table in sorted(bridges):
        per_domain = {}
        for edge in strong_edges:
            if edge["left"] != table and edge["right"] != table:
                continue
            other = edge["right"] if edge["left"] == table else edge["left"]
            comp = comp_of.get(other)
            if comp is not None:
                per_domain[comp] = round(per_domain.get(comp, 0.0) + edge["weight"], 4)
        links = [{"domain_id": id_by_domain(comp), "weight": weight}
                 for comp, weight in sorted(per_domain.items(),
                                            key=lambda item: (-item[1], item[0]))]
        if len(links) < settings["bridge_min_domains"]:
            demoted.append(table)
            continue
        bridge_payload.append({
            "table": table, "role": "bridge", "domain_links": links,
            "primary_domain_id": links[0]["domain_id"],
            "reason": "强邻接覆盖 {0} 个主题域，次强域权重 {1:.4f} 达到最强域的 {2:.0%} 阈值".format(
                len(links), links[1]["weight"], settings["bridge_balance_ratio"]),
        })
    singleton = [m[0] for m in components if len(m) == 1]
    ungrouped = sorted(set(singleton) | weak_boundary | set(demoted))
    return {
        "enabled": True,
        "settings": {
            "edge_weight_threshold": threshold, "max_domain_size": settings["max_domain_size"],
            "bridge_min_domains": settings["bridge_min_domains"],
            "bridge_balance_ratio": settings["bridge_balance_ratio"],
            "relation_weights": dict(sorted(relation_weights.items())),
        },
        "domains": payload_domains, "bridge_tables": bridge_payload,
        "ungrouped_tables": ungrouped,
        "stats": {
            "domain_count": len(payload_domains),
            "grouped_table_count": sum(len(m) for m in domains),
            "bridge_table_count": len(bridge_payload),
            "ungrouped_table_count": len(ungrouped),
            "table_edge_count": len(table_edges), "strong_edge_count": len(strong_edges),
        },
    }
def annotate_graph(graph, result):
    """把域身份写入图节点，并在图数据顶层挂载 domain 段；返回同一图字典。"""
    if not result or not result.get("enabled"):
        return graph
    role_of = {item["table"]: item for item in result["bridge_tables"]}
    domain_id_of, domain_name_of = {}, {}
    core_tables = {domain["core_table"] for domain in result["domains"]}
    for domain in result["domains"]:
        for table in domain["tables"]:
            domain_id_of[table] = domain["domain_id"]
            domain_name_of[table] = domain["name"]
    ungrouped = set(result["ungrouped_tables"])
    for node in graph.get("nodes", []):
        table = node.get("table")
        if node.get("node_type") != "table":
            node["domain_id"] = domain_id_of.get(table)
            node["domain_role"] = "member" if table in domain_id_of else None
            continue
        if table in role_of:
            node["domain_id"], node["domain_role"] = None, "bridge"
        elif table in domain_id_of:
            node["domain_id"] = domain_id_of[table]
            node["domain_role"] = "core" if table in core_tables else "member"
        else:
            node["domain_id"] = None
            node["domain_role"] = "ungrouped" if table in ungrouped else None
        node["domain_name"] = domain_name_of.get(table)
    graph["domain"] = result
    return graph
