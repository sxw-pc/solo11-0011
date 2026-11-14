"""关联规则 JSON / YAML 导出与统一结果字典构造。"""
import json
import os
from collections import Counter
import yaml
from ..exceptions import ExportError
def _safe_associations(associations):
    result = []
    for item in associations:
        copied = json.loads(json.dumps(item, ensure_ascii=False, default=str))
        result.append(copied)
    return result
def build_rules_payload(dataset, associations, config, diff=None, graph=None):
    """构造结构化规则文档，供导出、差分和 Web API 共用。"""
    table_dicts = dataset.table_dicts()
    relation_counts = Counter(item.get("relation_type", "unknown") for item in associations)
    source_counts = Counter()
    for item in associations:
        for source in item.get("detection_sources", []):
            source_counts[source] += 1
    payload = {
        "schema_version": "1.1",
        "tool": "tablelink-mapper",
        "project": dict(config.get("project", {})),
        "dataset": {
            "table_count": len(dataset.tables),
            "field_count": sum(len(table.columns) for table in dataset.tables.values()),
            "row_count": sum(table.row_count for table in dataset.tables.values()),
            "sources": list(dataset.sources),
            "tables": table_dicts,
            "load_errors": list(dataset.errors),
        },
        "summary": {
            "association_count": len(associations),
            "by_relation_type": dict(sorted(relation_counts.items())),
            "by_detection_source": dict(sorted(source_counts.items())),
            "high_confidence_threshold": config["report"]["high_confidence"],
            "high_confidence_count": len([
                item for item in associations
                if item.get("confidence", 0) >= config["report"]["high_confidence"]
            ]),
            "graph": graph.get("stats", {}) if graph else {},
        },
        "associations": _safe_associations(associations),
        "incremental": diff,
    }
    return payload
def _atomic_write(path, text):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = os.path.abspath(path) + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except OSError as exc:
        raise ExportError("导出 {0} 失败: {1}".format(path, exc))
def export_rules(payload, json_path, yaml_path):
    """同时写出 JSON 与 YAML，两者内容等价。"""
    json_text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    try:
        yaml_text = yaml.safe_dump(
            payload, allow_unicode=True, sort_keys=False, default_flow_style=False
        )
    except yaml.YAMLError as exc:
        raise ExportError("YAML 序列化失败: {0}".format(exc))
    _atomic_write(json_path, json_text)
    _atomic_write(yaml_path, yaml_text)
    return {"json": os.path.abspath(json_path), "yaml": os.path.abspath(yaml_path)}
def export_graph_json(graph, path):
    text = json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    _atomic_write(path, text)
    return os.path.abspath(path)
def write_text(path, content):
    _atomic_write(path, content)
    return os.path.abspath(path)
def load_rule_document(path):
    """读取导出的规则文档，用于兼容 Web 与测试调用。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            if str(path).lower().endswith(".json"):
                return json.load(handle)
            return yaml.safe_load(handle)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise ExportError("读取规则文件失败: {0}".format(exc))
