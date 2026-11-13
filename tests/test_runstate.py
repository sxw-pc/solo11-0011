"""运行态管理、临时区原子提交与断点续跑测试。"""
import json
import os
from pathlib import Path
import pytest
import tablelink.pipeline as pipeline_module
from tablelink.exceptions import IncrementalError, TableLinkError
from tablelink.pipeline import STAGES, run_pipeline
from tablelink.runstate import (
    MANIFEST_NAME,
    RunManager,
    sha256_file,
)
from tests.conftest import ROOT, write_config
OUTPUT_FILES = ("relations.json", "relations.yaml", "report.md",
                "graph.json", "graph.html")
@pytest.fixture
def managed_config(tmp_path, default_config):
    return write_config(
        tmp_path, default_config,
        **{"output.directory": str(tmp_path / "out"),
           "incremental.default_baseline": ""}
    )
def _runs_root(out_dir):
    return Path(out_dir) / ".runs"
def _manifest(out_dir):
    manifests = list(_runs_root(out_dir).glob("run-*/" + MANIFEST_NAME))
    assert len(manifests) == 1
    return json.loads(manifests[0].read_text(encoding="utf-8"))
def test_managed_run_outputs_byte_identical_to_direct_run(tmp_path, managed_config):
    direct = run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                          use_default_baseline=False, managed=False)
    direct_hash = {name: sha256_file(str(tmp_path / "out" / name))
                   for name in OUTPUT_FILES}
    for name in OUTPUT_FILES:
        (tmp_path / "out" / name).unlink()
    managed = run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                           use_default_baseline=False, managed=True)
    assert managed.run_info["resumed"] is False
    assert managed.run_info["rerun"] == list(STAGES)
    managed_hash = {name: sha256_file(str(tmp_path / "out" / name))
                    for name in OUTPUT_FILES}
    assert managed_hash == direct_hash
    assert not _runs_root(tmp_path / "out").exists()
    text = (tmp_path / "out" / "relations.json").read_text(encoding="utf-8")
    assert "run-" not in text and ".runs" not in text
def test_keep_run_dir_preserves_verified_stage_artifacts(tmp_path, managed_config,
                                                         monkeypatch):
    captured = {}
    real_commit = pipeline_module._commit_outputs
    def spy_commit(run, outputs):
        manifest = json.loads(Path(run.manifest_path).read_text(encoding="utf-8"))
        captured["stages"] = manifest["stages"]
        captured["run_dir"] = run.run_dir
        for stage, record in manifest["stages"].items():
            for label, item in record["files"].items():
                assert sha256_file(item["path"]) == item["sha256"]
        return real_commit(run, outputs)
    monkeypatch.setattr(pipeline_module, "_commit_outputs", spy_commit)
    run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                 use_default_baseline=False, keep_run_dir=True)
    assert sorted(captured["stages"]) == sorted(STAGES)
    for record in captured["stages"].values():
        assert record["status"] == "completed"
    runs = _runs_root(tmp_path / "out")
    assert len([item for item in runs.iterdir() if item.is_dir()]) == 1
def test_failure_keeps_formal_outputs_untouched(tmp_path, managed_config,
                                                monkeypatch):
    run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                 use_default_baseline=False, managed=True)
    before = {name: sha256_file(str(tmp_path / "out" / name))
              for name in OUTPUT_FILES}
    def boom(*args, **kwargs):
        raise IncrementalError("注入的检测阶段故障")
    monkeypatch.setattr(pipeline_module, "detect_overlap", boom)
    with pytest.raises(IncrementalError):
        run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                     use_default_baseline=False, keep_run_dir=True)
    after = {name: sha256_file(str(tmp_path / "out" / name))
             for name in OUTPUT_FILES}
    assert after == before
    manifest = _manifest(tmp_path / "out")
    assert manifest["state"] == "failed"
    assert manifest["stages"]["load"]["status"] == "completed"
    assert manifest["stages"]["detect"]["status"] == "failed"
    formal = {item.name for item in (tmp_path / "out").iterdir()
              if item.is_file()}
    assert formal == set(OUTPUT_FILES)
def test_resume_skips_verified_stages_and_reruns_failed_downstream(
        tmp_path, managed_config, monkeypatch):
    def boom(*args, **kwargs):
        raise IncrementalError("注入的检测阶段故障")
    monkeypatch.setattr(pipeline_module, "detect_overlap", boom)
    with pytest.raises(IncrementalError):
        run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                     use_default_baseline=False, keep_run_dir=True)
    monkeypatch.undo()
    result = run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                          use_default_baseline=False)
    assert result.run_info["resumed"] is True
    assert result.run_info["skipped"] == ["load"]
    assert result.run_info["rerun"] == ["detect", "incremental", "graph", "export"]
    assert result.run_info["failed_stage"] == "detect"
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "运行态与断点续跑" in report
    assert "load" in report
    assert "detect、incremental、graph、export" in report
    assert "注入的检测阶段故障" in report
def test_tampered_stage_artifact_is_not_reused(tmp_path, managed_config,
                                               monkeypatch):
    def boom(*args, **kwargs):
        raise IncrementalError("先在 graph 阶段制造一次失败")
    monkeypatch.setattr(pipeline_module, "build_graph", boom)
    with pytest.raises(IncrementalError):
        run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                     use_default_baseline=False, keep_run_dir=True)
    runs = _runs_root(tmp_path / "out")
    detect_file = next(runs.glob("run-*/detect/associations.json"))
    detect_file.write_text('{"associations": []}', encoding="utf-8")
    monkeypatch.undo()
    result = run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                          use_default_baseline=False)
    assert "detect" in result.run_info["rerun"]
    assert "detect" not in result.run_info["skipped"]
    assert result.summary()["associations"] > 0
def test_changed_source_invalidates_load_and_all_downstream(
        tmp_path, default_config, monkeypatch):
    import shutil
    import yaml
    out_dir = tmp_path / "out2"
    config_path = write_config(
        tmp_path, default_config,
        **{"output.directory": str(out_dir),
           "incremental.default_baseline": ""}
    )
    def boom(*args, **kwargs):
        raise IncrementalError("先制造失败以保留可续跑临时区")
    monkeypatch.setattr(pipeline_module, "build_graph", boom)
    with pytest.raises(IncrementalError):
        run_pipeline(config_path=config_path, base_dir=str(ROOT),
                     use_default_baseline=False, keep_run_dir=True)
    monkeypatch.undo()
    copied = tmp_path / "mock_csv"
    shutil.copytree(ROOT / "fixtures" / "mock_csv", copied)
    alarm = copied / "alarm_info.csv"
    rows = alarm.read_text(encoding="utf-8").strip().splitlines()
    rows.append(rows[1])
    alarm.write_text("\n".join(rows) + "\n", encoding="utf-8")
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    payload["sources"]["csv_dirs"] = [str(copied)]
    Path(config_path).write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    result = run_pipeline(config_path=config_path, base_dir=str(ROOT),
                          use_default_baseline=False, keep_run_dir=True)
    assert result.run_info["resumed"] is True
    assert sorted(result.run_info["rerun"]) == sorted(STAGES)
    assert result.run_info["skipped"] == []
def test_fresh_flag_ignores_failed_run(tmp_path, managed_config, monkeypatch):
    def boom(*args, **kwargs):
        raise IncrementalError("失败一次")
    monkeypatch.setattr(pipeline_module, "detect_overlap", boom)
    with pytest.raises(IncrementalError):
        run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                     use_default_baseline=False, keep_run_dir=True)
    monkeypatch.undo()
    result = run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                          use_default_baseline=False, resume=False,
                          keep_run_dir=True)
    assert result.run_info["resumed"] is False
    assert result.run_info["rerun"] == list(STAGES)
    assert result.run_info["skipped"] == []
def test_web_direct_mode_creates_no_run_dir(tmp_path, default_config):
    from tablelink.web import create_app
    config_path = write_config(
        tmp_path, default_config,
        **{"output.directory": str(tmp_path / "webout"),
           "incremental.default_baseline": ""}
    )
    app = create_app(config_path, base_dir=str(ROOT))
    app.config.update(TESTING=True)
    response = app.test_client().post("/api/scan", json={})
    assert response.status_code == 200
    assert not (tmp_path / "webout" / ".runs").exists()
    for name in OUTPUT_FILES:
        assert (tmp_path / "webout" / name).is_file()
def test_consecutive_successes_remain_byte_identical(tmp_path, managed_config):
    run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                 use_default_baseline=False)
    first = {name: sha256_file(str(tmp_path / "out" / name))
             for name in OUTPUT_FILES}
    run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                 use_default_baseline=False)
    second = {name: sha256_file(str(tmp_path / "out" / name))
              for name in OUTPUT_FILES}
    assert first == second
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "运行态与断点续跑" not in report
def test_discover_resumable_ignores_completed_manifests(tmp_path):
    out_dir = tmp_path / "out"
    assert RunManager.discover_resumable(out_dir, STAGES) is None
    run = RunManager(out_dir, stages=STAGES)
    run.begin()
    run.mark_completed()
    assert RunManager.discover_resumable(out_dir, STAGES) is None
def test_older_failed_runs_marked_superseded(tmp_path, managed_config,
                                             monkeypatch):
    real_overlap = pipeline_module.detect_overlap
    def boom(*args, **kwargs):
        raise IncrementalError("失败一次")
    monkeypatch.setattr(pipeline_module, "detect_overlap", boom)
    for _ in range(2):
        with pytest.raises(IncrementalError):
            run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                         use_default_baseline=False, resume=False,
                         keep_run_dir=True)
    monkeypatch.setattr(pipeline_module, "detect_overlap", real_overlap)
    run_pipeline(config_path=managed_config, base_dir=str(ROOT),
                 use_default_baseline=False, keep_run_dir=True)
    states = {}
    for manifest in _runs_root(tmp_path / "out").glob("run-*/" + MANIFEST_NAME):
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        states[payload["run_id"]] = payload["state"]
    assert sorted(states.values()) == ["completed", "superseded"]
