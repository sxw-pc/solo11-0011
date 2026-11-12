"""血缘快照落盘、基线轮转与审计产物导出。"""
import json
import os
from ..exceptions import LineageError
from .diff import compare_snapshots, empty_audit
from .report import build_audit_markdown
from .snapshot import build_snapshot, dump_snapshot, load_snapshot


def _atomic_write(path, text):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = os.path.abspath(path) + ".tmp"
    try:
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except OSError as exc:
        raise LineageError("血缘产物写入失败 {0}: {1}".format(path, exc))


def lineage_paths(config, base_dir, output_directory):
    """解析血缘产物路径；directory 为空时默认 <输出目录>/lineage。"""
    section = config["lineage"]
    directory = section.get("directory") or os.path.join(output_directory, "lineage")
    if not os.path.isabs(directory):
        directory = os.path.join(base_dir, directory)
    directory = os.path.abspath(directory)
    return {
        "directory": directory,
        "snapshot": os.path.join(directory, section["snapshot_file"]),
        "audit_json": os.path.join(directory, section["audit_json"]),
        "audit_md": os.path.join(directory, section["audit_md"]),
    }


def run_lineage_audit(dataset, associations, config, base_dir, output_directory):
    """构建当前快照并与既有基线比对；无基线时只建基线、不报漂移。"""
    paths = lineage_paths(config, base_dir, output_directory)
    snapshot = build_snapshot(dataset, associations, config, base_dir)
    baseline, problem = load_snapshot(paths["snapshot"])
    _atomic_write(paths["snapshot"], dump_snapshot(snapshot))
    warnings = []
    if baseline is None:
        status = "baseline_reset" if problem else "baseline_initialized"
        note = "历史快照不可用（{0}），已重建基线".format(problem) if problem \
            else "未找到历史血缘快照，本次仅建立基线"
        if problem:
            warnings.append("血缘快照：{0}".format(note))
        audit = empty_audit(status, snapshot, note)
    else:
        audit = compare_snapshots(baseline, snapshot)
    text = json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write(paths["audit_json"], text)
    _atomic_write(paths["audit_md"], build_audit_markdown(audit))
    return {
        "status": audit["status"],
        "origin": audit["origin"],
        "summary": audit["summary"],
        "warnings": warnings,
        "outputs": {
            "lineage_snapshot": paths["snapshot"],
            "lineage_audit_json": paths["audit_json"],
            "lineage_audit_md": paths["audit_md"],
        },
    }
