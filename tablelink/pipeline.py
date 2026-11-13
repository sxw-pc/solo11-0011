"""加载 - 检测 - 去重 - 增量 - 导出的完整流水线。

批处理模式（run_demo）由 RunManager 托管：阶段产物先写 output/.runs/
临时区，全部阶段通过后再原子替换正式产物，失败可按摘要校验断点续跑。
Web 热加载扫描以 managed=False 调用，沿用原有同步直跑行为与输出位置，
不产生临时区，产物内容与改造前完全一致。
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from . import checkpoint
from .config import ConfigManager
from .detector import build_graph, detect_explicit, detect_fd, detect_overlap
from .detector.graph_common import merge_associations
from .exceptions import IncrementalError, TableLinkError
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
from .reporter.rule_exporter import load_rule_document
from .runstate import (
    RunManager,
    cleanup_completed_run,
    mark_older_runs_superseded,
    utc_now_text,
)
LOGGER = logging.getLogger("tablelink")
CHECKPOINT_FORMAT = "1.0"
STAGES = ("load", "detect", "incremental", "graph", "export")
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
    run_info: Dict[str, Any] = field(default_factory=dict)
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
def _warnings_from(dataset, baseline):
    warnings = ["{0}: {1}".format(item.get("source"), item.get("message"))
                for item in dataset.errors]
    if not baseline:
        warnings.append("未提供历史规则，跳过增量对比")
    return warnings
def _upstream(run, stage, label):
    """取上游检查点路径，作为下游输入指纹的级联组成部分。"""
    if run is None:
        return None
    path = run.stage_file(stage, label)
    return [path] if path else None
def _stage_fingerprint(name, config, baseline, source_paths, run):
    """阶段决策时惰性计算，确保级联的是本次运行最新的上游产物。"""
    if name == "load":
        parts = [("format", CHECKPOINT_FORMAT), ("sources", source_paths),
                 ("source_config", config.get("sources", {}))]
    elif name == "detect":
        parts = [("format", CHECKPOINT_FORMAT),
                 ("upstream", _upstream(run, "load", "dataset")),
                 ("config", {key: config.get(key)
                             for key in ("explicit", "overlap", "fd")})]
    elif name == "incremental":
        parts = [("format", CHECKPOINT_FORMAT),
                 ("upstream", _upstream(run, "detect", "associations")),
                 ("baseline", baseline or ""),
                 ("threshold", config["incremental"]["confidence_delta_threshold"])]
    elif name == "graph":
        parts = [("format", CHECKPOINT_FORMAT),
                 ("upstream", _upstream(run, "incremental", "diff"))]
    else:
        parts = [("format", CHECKPOINT_FORMAT),
                 ("upstream_graph", _upstream(run, "graph", "graph_json")),
                 ("report_config", config.get("report", {})),
                 ("project", config.get("project", {}))]
    return checkpoint.make_input_fingerprint(parts)
def _run_stage(run, name, fingerprint, rerun_call, reuse_call=None):
    """摘要校验通过则复用临时产物，否则重跑并登记清单。"""
    started = utc_now_text()
    if run is not None and run.can_reuse(name, fingerprint):
        result = reuse_call() if reuse_call else None
        run.skipped_stages.append(name)
        LOGGER.info("阶段 %s 摘要校验通过，复用临时产物", name)
        return result
    if run is not None:
        run.rerun_stages.append(name)
    result, files = rerun_call()
    if run is not None:
        run.record_stage(name, fingerprint, files, started)
        run.completed_stages.append(name)
    return result
def _commit_outputs(run, outputs):
    """全部阶段成功后，按固定顺序把临时产物原子替换为正式产物。"""
    plan = ("rules_json", "rules_yaml", "graph_json", "report_md", "graph_html")
    committed = {}
    for label in plan:
        source = run.stage_file("export", label)
        target = outputs[label]
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        os.replace(source, target)
        committed[label] = os.path.abspath(target)
    return committed
def run_pipeline(config_path=None, base_dir=None, baseline_path=None,
                 use_default_baseline=True, manager=None,
                 managed=True, resume=True, keep_run_dir=False):
    """执行全流程并写出全部本地产物。

    managed=True 启用临时区与断点续跑；managed=False 为 Web 热加载保留
    的同步直跑路径，不产生临时区，行为与改造前一致。
    """
    manager = manager or ConfigManager(
        config_path, base_dir=base_dir, auto_reload=True
    )
    if manager.auto_reload:
        manager.reload_if_changed()
    config = manager.load()
    outputs = _output_paths(manager, config)
    baseline = _select_baseline(
        manager, config, baseline_path, use_default_baseline
    )
    source_paths = checkpoint.source_input_paths(config, manager)
    run = None
    if managed:
        run = (RunManager.discover_resumable(outputs["directory"], STAGES)
               if resume else None)
        if run is None:
            run = RunManager(outputs["directory"], stages=STAGES)
        run.begin()
        LOGGER.info("运行目录 %s（%s）", run.run_dir,
                    "断点续跑" if run.resumed else "新建")
    def fingerprint(name):
        return _stage_fingerprint(name, config, baseline, source_paths, run)
    dataset = current = graph = payload = diff = None
    try:
        def load_call():
            data = load_dataset(config, manager.base_dir)
            files = checkpoint.save_dataset(run, "load", data) if run else {}
            return data, files
        dataset = _run_stage(
            run, "load", fingerprint("load"), load_call,
            reuse_call=lambda: checkpoint.restore_dataset(
                run, "load", config, manager.base_dir),
        )
        def detect_call():
            explicit = detect_explicit(dataset, config, manager.base_dir)
            overlap = detect_overlap(dataset, config)
            functional = detect_fd(dataset, config, key_links=explicit + overlap)
            assoc = merge_associations(explicit + overlap + functional)
            files = (checkpoint.save_associations(run, "detect", assoc)
                     if run else {})
            return assoc, files
        current = _run_stage(
            run, "detect", fingerprint("detect"), detect_call,
            reuse_call=lambda: checkpoint.load_associations_checkpoint(
                run, "detect"),
        )
        def incremental_call():
            if not baseline:
                result_diff, tagged = None, current
            else:
                LOGGER.info("对比历史规则 %s", baseline)
                result_diff = compare(
                    current, load_history(baseline),
                    float(config["incremental"]["confidence_delta_threshold"]),
                )
                tagged = tag_current(current, result_diff)
            files = (checkpoint.save_diff(run, "incremental", result_diff,
                                           baseline) if run else {})
            return (tagged, result_diff), files
        def incremental_reuse():
            result_diff, _ = checkpoint.load_diff_checkpoint(run, "incremental")
            tagged = tag_current(current, result_diff) if result_diff else current
            return tagged, result_diff
        current, diff = _run_stage(
            run, "incremental", fingerprint("incremental"),
            incremental_call, reuse_call=incremental_reuse,
        )
        def graph_call():
            built = build_graph(dataset, current, diff=diff)
            files = {}
            if run:
                path = run.stage_path("graph", "graph.json")
                export_graph_json(built, path)
                files = {"graph_json": path}
            return built, files
        graph = _run_stage(
            run, "graph", fingerprint("graph"), graph_call,
            reuse_call=lambda: load_rule_document(
                run.stage_file("graph", "graph_json")),
        )
        if run is not None:
            started = utc_now_text()
            run.rerun_stages.append("export")
            payload = build_rules_payload(
                dataset, current, config, diff=diff, graph=graph
            )
            files = {label: run.stage_path("export", filename) for label, filename in (
                ("rules_json", "rules.json"), ("rules_yaml", "rules.yaml"),
                ("graph_json", "graph.json"), ("report_md", "report.md"),
                ("graph_html", "graph.html"),
            )}
            export_rules(payload, files["rules_json"], files["rules_yaml"])
            export_graph_json(graph, files["graph_json"])
            markdown = build_markdown(
                dataset, current, graph, config, diff=diff,
                run_info=run.reuse_summary(),
            )
            write_text(files["report_md"], markdown)
            generate_html_graph(graph, config, files["graph_html"], diff=diff)
            run.record_stage("export", fingerprint("export"), files, started)
            run.completed_stages.append("export")
            outputs.update(_commit_outputs(run, outputs))
            run.mark_completed()
            mark_older_runs_superseded(run)
            if not keep_run_dir:
                cleanup_completed_run(run)
        else:
            os.makedirs(outputs["directory"], exist_ok=True)
            LOGGER.info("导出 JSON/YAML 关联规则")
            payload = build_rules_payload(
                dataset, current, config, diff=diff, graph=graph
            )
            outputs.update(export_rules(
                payload, outputs["rules_json"], outputs["rules_yaml"]
            ))
            export_graph_json(graph, outputs["graph_json"])
            markdown = build_markdown(dataset, current, graph, config, diff=diff)
            write_text(outputs["report_md"], markdown)
            generate_html_graph(graph, config, outputs["graph_html"], diff=diff)
    except Exception as exc:
        if run is not None:
            stage = run.rerun_stages[-1] if run.rerun_stages else "unknown"
            run.mark_stage_failed(stage, exc, utc_now_text())
        raise
    return PipelineResult(
        config=config,
        manager=manager,
        dataset=dataset,
        associations=current,
        graph=graph,
        payload=payload,
        diff=diff,
        outputs=outputs,
        warnings=_warnings_from(dataset, baseline),
        run_info=run.reuse_summary() if run is not None else {"managed": False},
    )
