"""字段级血缘快照：结构定义、构建、序列化与加载。

快照为内容寻址的 JSON 文档：不含时间戳与绝对路径，全部列表排序，
snapshot_id 为内容（除自身外）的 SHA-256，因此相同输入字节级一致。
"""
import hashlib
import json
import os
from .. import __version__
from ..detector.common import normalize_value

SNAPSHOT_FORMAT = "tablelink-lineage-snapshot"
SNAPSHOT_VERSION = "1.0"
SUPPORTED_VERSIONS = {"1.0"}
CONFIG_SECTIONS = ("sources", "explicit", "overlap", "fd")


def _sha256_text(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_obj(obj):
    canonical = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(canonical)


def _abs(base_dir, path):
    if os.path.isabs(path):
        return os.path.abspath(path)
    return os.path.abspath(os.path.join(base_dir, path))


def _rel(base_dir, path):
    try:
        return os.path.relpath(os.path.abspath(path), os.path.abspath(base_dir))
    except ValueError:  # Windows 跨盘符
        return os.path.abspath(path)


def _file_fingerprint(path):
    try:
        with open(path, "rb") as handle:
            return "sha256:" + hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def config_fingerprint(config, base_dir):
    """对影响血缘的配置段及自定义规则文件内容分别取指纹，供归因使用。"""
    sections = {name: _hash_obj(config.get(name) or {}) for name in CONFIG_SECTIONS}
    custom = None
    custom_path = (config.get("explicit") or {}).get("custom_rules_path")
    if custom_path:
        custom = _file_fingerprint(_abs(base_dir, custom_path))
    return {
        "sections": sections,
        "fingerprint": _hash_obj(sections),
        "custom_rules": custom,
    }


def _value_fingerprint(table, field):
    """字段规范化值集合的指纹；数据内容变化时即变，与统计指标互补。"""
    if table.frame is None or field not in table.frame.columns:
        return None
    values = set()
    for raw in table.frame[field].dropna().tolist():
        normalized = normalize_value(raw)
        if normalized is not None:
            values.add(normalized)
    return _sha256_text("\x1f".join(sorted(values)))


def enumerate_sources(config, base_dir):
    """按配置展开预期来源文件清单，与加载器使用同一套路径解析与排序。"""
    found = []
    sources = config.get("sources", {})
    for directory in sources.get("csv_dirs", []):
        root = _abs(base_dir, directory)
        if not os.path.isdir(root):
            continue
        files = sorted(
            (os.path.join(dirpath, name)
             for dirpath, _, names in os.walk(root) for name in names
             if name.lower().endswith(".csv")),
            key=str.lower,
        )
        found.extend(("csv", path) for path in files)
    for database in sources.get("sqlite_files", []):
        found.append(("sqlite", _abs(base_dir, database)))
    return sorted(found, key=lambda item: _source_id(item[0], _rel(base_dir, item[1])))


def _source_id(source_type, rel_path):
    return "{0}:{1}".format(source_type, rel_path)


def _errors_for(dataset, abs_path, name):
    matched = []
    for item in dataset.errors:
        source = str(item.get("source"))
        if source == abs_path or source == name:
            matched.append(item)
    return matched


def _tables_by_source(dataset):
    grouped = {}
    for name, table in dataset.tables.items():
        grouped.setdefault((table.source_type, table.source_name), []).append(name)
    return grouped


def _source_entry(source_type, abs_path, base_dir, dataset, tables_by_source):
    """单个来源文件的快照条目；读取失败只降级该条目，不影响整批。"""
    rel = _rel(base_dir, abs_path)
    entry = {
        "source_id": _source_id(source_type, rel),
        "source_type": source_type,
        "path": rel,
        "state": "ok",
        "fingerprint": None,
        "encoding": None,
        "tables": [],
        "error": None,
    }
    if not os.path.isfile(abs_path):
        entry["state"] = "missing"
        return entry
    fingerprint = _file_fingerprint(abs_path)
    if fingerprint is None:
        entry["state"] = "error"
        entry["error"] = "无法读取文件内容"
        return entry
    entry["fingerprint"] = fingerprint
    errors = _errors_for(dataset, abs_path, os.path.basename(abs_path))
    fatals = [item for item in errors if item.get("kind", "error") == "error"]
    tables = sorted(tables_by_source.get((source_type, os.path.basename(abs_path)), []))
    if fatals:
        entry["state"] = "error"
        entry["error"] = fatals[0].get("message")
    elif tables:
        entry["tables"] = tables
        first = dataset.tables[tables[0]]
        entry["encoding"] = getattr(first, "encoding", None)
    elif any(item.get("kind") == "info" for item in errors):
        entry["state"] = "filtered"
        entry["error"] = errors[0].get("message")
    else:
        entry["state"] = "empty"
        if errors:
            entry["error"] = errors[0].get("message")
    return entry


def _table_entry(table, source_id):
    foreign = sorted(
        (dict(item) for item in table.foreign_keys),
        key=lambda item: json.dumps(item, sort_keys=True),
    )
    return {
        "table": table.name,
        "source_id": source_id,
        "source_type": table.source_type,
        "row_count": int(table.row_count),
        "primary_keys": sorted(table.primary_keys),
        "foreign_keys": foreign,
        "fields": [
            {
                "field": column["name"],
                "dtype": column["dtype"],
                "non_null_ratio": round(float(column["non_null_ratio"]), 4),
                "cardinality": int(column["cardinality"]),
                "unique_ratio": round(float(column["unique_ratio"]), 4),
                "value_fingerprint": _value_fingerprint(table, column["name"]),
            }
            for column in sorted(table.columns, key=lambda item: item["name"])
        ],
    }


def _association_entry(item):
    detections = [
        {
            "relation_type": det.get("relation_type", "unknown"),
            "source": det.get("source", "unknown"),
            "confidence": round(float(det.get("confidence", 0)), 4),
        }
        for det in item.get("detections", [])
    ]
    detections.sort(key=lambda det: (det["source"], det["relation_type"]))
    return {
        "key": "{0}.{1}->{2}.{3}".format(
            item["source_table"], item["source_field"],
            item["target_table"], item["target_field"],
        ),
        "source_table": item["source_table"],
        "source_field": item["source_field"],
        "target_table": item["target_table"],
        "target_field": item["target_field"],
        "relation_type": item.get("relation_type", "unknown"),
        "relation_types": sorted(item.get("relation_types") or []),
        "confidence": round(float(item.get("confidence", 0)), 4),
        "detection_sources": sorted(item.get("detection_sources") or []),
        "detections": detections,
        "evidence_fingerprint": _hash_obj(item.get("evidence") or []),
        "details_fingerprint": _hash_obj({
            "details": item.get("details") or {},
            "detections": [det.get("details") for det in item.get("detections", [])],
        }),
    }


def build_snapshot(dataset, associations, config, base_dir):
    """从数据集与关联结果构建快照；不含时间戳，snapshot_id 为内容哈希。"""
    tables_by_source = _tables_by_source(dataset)
    sources = [
        _source_entry(source_type, path, base_dir, dataset, tables_by_source)
        for source_type, path in enumerate_sources(config, base_dir)
    ]
    table_sources = {}
    for entry in sources:  # sources 已按 source_id 排序，同名冲突取第一个
        for table in entry["tables"]:
            table_sources.setdefault(table, entry["source_id"])
    snapshot = {
        "snapshot_format": SNAPSHOT_FORMAT,
        "snapshot_version": SNAPSHOT_VERSION,
        "generator": {"tool": "tablelink-mapper", "tool_version": __version__},
        "config": config_fingerprint(config, base_dir),
        "sources": sources,
        "tables": [
            _table_entry(dataset.tables[name], table_sources.get(name))
            for name in sorted(dataset.tables)
        ],
        "associations": sorted(
            (_association_entry(item) for item in associations),
            key=lambda item: item["key"],
        ),
        "load_errors": sorted(
            ({"source": str(item.get("source")), "kind": item.get("kind", "error"),
              "message": item.get("message")} for item in dataset.errors),
            key=lambda item: (item["source"], item["kind"], item["message"] or ""),
        ),
    }
    snapshot["snapshot_id"] = _hash_obj(snapshot)
    return snapshot


def dump_snapshot(snapshot):
    return json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def validate_snapshot(payload):
    """校验历史快照结构；返回问题描述，合法时返回 None。"""
    if not isinstance(payload, dict):
        return "历史快照不是 JSON 对象"
    if payload.get("snapshot_format") != SNAPSHOT_FORMAT:
        return "历史快照格式标识不匹配"
    version = str(payload.get("snapshot_version"))
    if version not in SUPPORTED_VERSIONS:
        return "历史快照版本 {0} 不受支持".format(version)
    for key in ("sources", "tables", "associations"):
        if not isinstance(payload.get(key), list):
            return "历史快照缺少 {0} 列表".format(key)
    if not isinstance(payload.get("config"), dict):
        return "历史快照缺少配置指纹"
    return None


def load_snapshot(path):
    """读取历史快照；返回 (快照, 问题)。文件不存在时两者皆为 None。"""
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        return None, "历史快照解析失败: {0}".format(exc)
    problem = validate_snapshot(payload)
    if problem:
        return None, problem
    return payload, None
