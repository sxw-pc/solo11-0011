"""加载 - 检测 - 去重 - 增量 - 导出的完整流水线。"""
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from .config import ConfigManager
from .detector import build_graph, detect_explicit, detect_fd, detect_overlap
from .detector.graph_common import merge_associations
from .exceptions import IncrementalError
from .incremental import compare, load_history, tag_current
from .loader import load_dataset
from .reporter import (
    build_markdown,
    build_rules_payload,
    export_graph_json,
    export_rules,
    generate_html_graph,
    write_text,
)
LOGGER = logging.getLogger("tablelink")
@dataclass
class PipelineResult:
    config: Dict[str, Any]
    manager: ConfigManager
    dataset: Any
    associations: List[Dict[str, Any]]
    graph: Dict[str, Any]
    payload: Dict[str, Any]
    diff: Optional[Dict[str, Any]]
    outputs: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    def summary(self):
        return {
            "tables": len(self.dataset.tables),
            "fields": sum(len(table.columns) for table in self.dataset.tables.values()),
            "associations": len(self.associations),
            "relation_types": self.graph["stats"]["by_relation_type"],
            "load_errors": len(self.dataset.errors),
            "diff": self.diff["summary"] if self.diff else None,
            "outputs": dict(self.outputs),
        }
def _resolve(manager, value):
    return manager.resolve(value) if value else value
def _select_baseline(manager, config, baseline_path, use_default_baseline):
    if baseline_path:
        path = _resolve(manager, baseline_path)
        if not os.path.isfile(path):
            raise IncrementalError("指定的历史规则文件不存在: {0}".format(path))
        return path
    if not use_default_baseline:
        return None
    default = config["incremental"].get("default_baseline")
    if not default:
        return None
    path = _resolve(manager, default)
    return path if os.path.isfile(path) else None
def _output_paths(manager, config):
    directory = _resolve(manager, config["output"]["directory"])
    return {
        "directory": directory,
        "rules_json": os.path.join(directory, config["output"]["rules_json"]),
        "rules_yaml": os.path.join(directory, config["output"]["rules_yaml"]),
        "report_md": os.path.join(directory, config["output"]["report_md"]),
        "graph_html": os.path.join(directory, config["output"]["graph_html"]),
        "graph_json": os.path.join(directory, config["output"]["graph_json"]),
    }
def run_pipeline(config_path=None, base_dir=None, baseline_path=None,
                 use_default_baseline=True, manager=None):
    """执行全流程并写出全部本地产物。"""
    manager = manager or ConfigManager(
        config_path, base_dir=base_dir, auto_reload=True
    )
    if manager.auto_reload:
        manager.reload_if_changed()
    config = manager.load()
    warnings = []
    LOGGER.info("加载本地数据源")
    dataset = load_dataset(config, manager.base_dir)
    for item in dataset.errors:
        warnings.append("{0}: {1}".format(item.get("source"), item.get("message")))
    LOGGER.info("检测显式关联与值域关联")
    explicit = detect_explicit(dataset, config, manager.base_dir)
    overlap = detect_overlap(dataset, config)
    LOGGER.info("检测函数依赖")
    functional = detect_fd(dataset, config, key_links=explicit + overlap)
    current = merge_associations(explicit + overlap + functional)
    baseline = _select_baseline(
        manager, config, baseline_path, use_default_baseline
    )
    diff = None
    if baseline:
        LOGGER.info("对比历史规则 %s", baseline)
        diff = compare(
            current, load_history(baseline),
            float(config["incremental"]["confidence_delta_threshold"]),
        )
        current = tag_current(current, diff)
    else:
        warnings.append("未提供历史规则，跳过增量对比")
    graph = build_graph(dataset, current, diff=diff)
    payload = build_rules_payload(dataset, current, config, diff=diff, graph=graph)
    outputs = _output_paths(manager, config)
    os.makedirs(outputs["directory"], exist_ok=True)
    LOGGER.info("导出 JSON/YAML 关联规则")
    exported = export_rules(payload, outputs["rules_json"], outputs["rules_yaml"])
    outputs.update(exported)
    export_graph_json(graph, outputs["graph_json"])
    markdown = build_markdown(dataset, current, graph, config, diff=diff)
    write_text(outputs["report_md"], markdown)
    generate_html_graph(graph, config, outputs["graph_html"], diff=diff)
    return PipelineResult(
        config=config,
        manager=manager,
        dataset=dataset,
        associations=current,
        graph=graph,
        payload=payload,
        diff=diff,
        outputs=outputs,
        warnings=warnings,
    )
