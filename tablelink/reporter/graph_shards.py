"""按关系类型家族拆分图谱边数据；分片名、顺序与数量均为确定性。"""
import json
import os
from .rule_exporter import write_text

FAMILIES = ("explicit", "overlap", "fd", "contains")
RELATION_FAMILY = {
    "value_overlap": "overlap",
    "functional_dependency": "fd",
    "contains": "contains",
}
def family_of_type(relation_type):
    """关系类型到稳定家族名；未知类型归入 explicit，与前端默认着色一致。"""
    return RELATION_FAMILY.get(relation_type, "explicit")
def edge_families(edge):
    types = edge.get("relation_types") or [edge.get("relation_type")]
    return {family_of_type(item) for item in types if item}
def _sort_key(edge):
    return (bool(edge.get("structural", False)),
            -float(edge.get("confidence", 0) or 0), str(edge.get("id", "")))
def bucket_edges(graph):
    buckets = {name: [] for name in FAMILIES}
    for edge in graph.get("edges", []):
        for name in edge_families(edge):
            buckets[name].append(edge)
    for edges in buckets.values():
        edges.sort(key=_sort_key)
    return buckets
def shard_filename(html_path, family):
    base = os.path.splitext(os.path.basename(os.path.abspath(html_path)))[0]
    return "{0}.data.{1}.json".format(base, family)
def build_manifest(graph, html_path):
    """固定四片清单；空家族也写空片，保证分片数量不随数据变化。"""
    buckets = bucket_edges(graph)
    return {
        "format": "tablelink-graph-shard-manifest", "schema_version": "1.0", "base": "",
        "families": [{"family": name, "file": shard_filename(html_path, name),
                      "edge_count": len(buckets[name])} for name in FAMILIES],
    }
def write_shards(graph, html_path, manifest):
    """写出全部伴生分片并返回 family -> 绝对路径；JSON 紧凑且无时间戳。"""
    buckets, directory, paths = bucket_edges(graph), os.path.dirname(os.path.abspath(html_path)), {}
    for entry in manifest["families"]:
        payload = {"format": "tablelink-graph-shard", "schema_version": "1.0",
                   "family": entry["family"], "edge_count": len(buckets[entry["family"]]),
                   "edges": buckets[entry["family"]]}
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
        paths[entry["family"]] = write_text(os.path.join(directory, entry["file"]), text)
    return paths
def diff_summary(diff):
    """骨架只携带统计摘要；完整差异仍由 graph.json / relations.json 持有。"""
    return None if not diff else {"threshold": diff.get("threshold"),
                                  "summary": diff.get("summary", {})}
def meta_payload(graph, manifest, diff):
    return {"mode": "sharded", "schema_version": graph.get("schema_version", "1.0"),
            "nodes": graph.get("nodes", []), "stats": graph.get("stats", {}),
            "shards": manifest, "diff": diff_summary(diff)}
