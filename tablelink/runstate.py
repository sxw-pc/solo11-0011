"""批处理运行态管理：临时区、阶段清单、摘要校验与断点续跑。

设计要点：
- 每次扫描在输出目录下建立 .runs/run-<id>/ 临时区，阶段产物只写临时区；
- 每个阶段完成后写入带输入指纹与输出 SHA-256 的清单（manifest）；
- 续跑只复用“输入指纹匹配且输出摘要校验通过”的阶段，污染或过期阶段
  及其下游阶段一律重跑；
- run id 与临时路径只存在于本模块的元数据中，绝不进入正式产物内容。
"""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
RUNS_DIRNAME = ".runs"
STATE_RUNNING = "running"
STATE_FAILED = "failed"
STATE_COMPLETED = "completed"
STATE_SUPERSEDED = "superseded"
MANIFEST_NAME = "manifest.json"
def utc_now_text():
    """UTC 时间戳，仅写入运行元数据，不进入正式产物。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def sha256_file(path):
    """计算文件 SHA-256；文件不可读时返回 None。"""
    if not os.path.isfile(path):
        return None
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 16), b""):
                digest.update(block)
    except OSError:
        return None
    return digest.hexdigest()
def fingerprint_paths(paths):
    """对一组输入路径计算稳定指纹；缺失文件用 None 显式占位。"""
    digest = hashlib.sha256()
    for path in sorted(str(item) for item in paths):
        digest.update(path.encode("utf-8") + b"\0")
        digest.update((sha256_file(path) or "missing").encode("utf-8") + b"\0")
    return digest.hexdigest()
def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None
def _write_json_atomic(path, payload):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as text:
            json.dump(payload, text, ensure_ascii=False, indent=2, sort_keys=True)
            text.write("\n")
        os.replace(temporary, path)
    except OSError:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise
class RunManager:
    """管理单次批处理的临时区与阶段清单。"""
    def __init__(self, output_dir, run_id=None, stages=None):
        self.output_dir = os.path.abspath(output_dir)
        self.runs_root = os.path.join(self.output_dir, RUNS_DIRNAME)
        self.run_id = run_id or "run-{0}-{1}".format(
            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
            os.urandom(4).hex(),
        )
        self.run_dir = os.path.join(self.runs_root, self.run_id)
        self.stage_names = list(stages or [])
        self.manifest_path = os.path.join(self.run_dir, MANIFEST_NAME)
        self.manifest = self._load_manifest()
        self.resumed = self.manifest is not None
        self.completed_stages, self.skipped_stages, self.rerun_stages = [], [], []
        self.failed_stage = self.failure_reason = None
        if self.resumed:
            for stage, record in self.manifest.get("stages", {}).items():
                if isinstance(record, dict) and record.get("status") == "failed":
                    self.failed_stage, self.failure_reason = stage, record.get("reason")
    def _load_manifest(self):
        manifest = _load_json(self.manifest_path)
        if (isinstance(manifest, dict) and manifest.get("run_id") == self.run_id
                and isinstance(manifest.get("stages"), dict)):
            return manifest
        return None
    @classmethod
    def discover_resumable(cls, output_dir, stages):
        """在 .runs 下寻找最近一个可续跑（未完成且清单可读）的运行。"""
        runs_root = os.path.join(os.path.abspath(output_dir), RUNS_DIRNAME)
        if not os.path.isdir(runs_root):
            return None
        candidates = []
        for name in os.listdir(runs_root):
            manifest = _load_json(os.path.join(runs_root, name, MANIFEST_NAME))
            if isinstance(manifest, dict) and manifest.get("state") == STATE_FAILED:
                candidates.append((manifest.get("updated_at", ""), name))
        if not candidates:
            return None
        manager = cls(output_dir, run_id=sorted(candidates)[-1][1], stages=stages)
        return manager if manager.manifest else None
    def begin(self):
        """建立临时区并写入运行态清单。"""
        os.makedirs(self.run_dir, exist_ok=True)
        if self.manifest is None:
            self.manifest = {"run_id": self.run_id, "state": STATE_RUNNING,
                             "created_at": utc_now_text(),
                             "updated_at": utc_now_text(), "stages": {}}
        else:
            self.manifest["state"] = STATE_RUNNING
            self.manifest["updated_at"] = utc_now_text()
        self._flush()
        return self.run_dir
    def stage_dir(self, stage):
        path = os.path.join(self.run_dir, stage)
        os.makedirs(path, exist_ok=True)
        return path
    def stage_path(self, stage, filename):
        return os.path.join(self.stage_dir(stage), filename)
    def record_stage(self, stage, input_fingerprint, outputs, started_at, note=None):
        """阶段成功：登记输入指纹与每个输出文件的摘要。"""
        files = {}
        for label, path in sorted(outputs.items()):
            digest = sha256_file(path)
            if digest is None:
                raise FileNotFoundError(path)
            files[label] = {"path": os.path.abspath(path), "sha256": digest}
        self.manifest["stages"][stage] = {
            "status": "completed", "input_fingerprint": input_fingerprint,
            "files": files, "started_at": started_at,
            "finished_at": utc_now_text(), "note": note,
        }
        self.manifest["updated_at"] = utc_now_text()
        self._flush()
    def mark_stage_failed(self, stage, reason, started_at):
        """阶段失败：状态落盘并保留现场，供下次续跑识别。"""
        self.manifest["stages"][stage] = {
            "status": "failed", "started_at": started_at,
            "finished_at": utc_now_text(), "reason": str(reason),
        }
        self.manifest["state"] = STATE_FAILED
        self.manifest["updated_at"] = utc_now_text()
        self.failed_stage, self.failure_reason = stage, str(reason)
        self._flush()
    def mark_completed(self):
        self.manifest["state"] = STATE_COMPLETED
        self.manifest["updated_at"] = utc_now_text()
        self._flush()
    def can_reuse(self, stage, input_fingerprint):
        """仅当阶段已完成、输入指纹一致且全部输出摘要校验通过时复用。"""
        record = self.manifest.get("stages", {}).get(stage)
        if not isinstance(record, dict) or record.get("status") != "completed":
            return False
        if record.get("input_fingerprint") != input_fingerprint:
            return False
        return all(sha256_file(item.get("path")) == item.get("sha256")
                   for item in (record.get("files") or {}).values())
    def stage_file(self, stage, label):
        record = self.manifest.get("stages", {}).get(stage) or {}
        item = (record.get("files") or {}).get(label)
        return item.get("path") if item else None
    def reuse_summary(self):
        return {
            "run_id": self.run_id, "resumed": self.resumed,
            "completed": list(self.completed_stages),
            "skipped": list(self.skipped_stages),
            "rerun": list(self.rerun_stages),
            "failed_stage": self.failed_stage,
            "failure_reason": self.failure_reason,
        }
    def _flush(self):
        _write_json_atomic(self.manifest_path, self.manifest)
def mark_older_runs_superseded(run):
    """把同目录下更早的失败运行标记为已取代（不删除任何目录）。"""
    if not os.path.isdir(run.runs_root):
        return
    for name in os.listdir(run.runs_root):
        if name == run.run_id:
            continue
        manifest_path = os.path.join(run.runs_root, name, MANIFEST_NAME)
        manifest = _load_json(manifest_path)
        if isinstance(manifest, dict) and manifest.get("state") == STATE_FAILED:
            manifest["state"] = STATE_SUPERSEDED
            manifest["updated_at"] = utc_now_text()
            _write_json_atomic(manifest_path, manifest)
def cleanup_completed_run(run):
    """成功提交后清理本次临时区；旧失败运行先标记为已取代。"""
    import shutil
    mark_older_runs_superseded(run)
    shutil.rmtree(run.run_dir, ignore_errors=True)
    try:
        if os.path.isdir(run.runs_root) and not os.listdir(run.runs_root):
            os.rmdir(run.runs_root)
    except OSError:
        pass
