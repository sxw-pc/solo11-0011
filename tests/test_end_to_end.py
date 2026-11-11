"""批处理、增量对比与组合筛选的端到端测试。"""
import copy, hashlib, json
import pytest
from pathlib import Path
from tablelink.exceptions import IncrementalError
from tablelink.pipeline import run_pipeline
from tests.conftest import ROOT, write_config
def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def _history(associations, path):
    history = copy.deepcopy(associations)
    history.pop()
    history[0]["confidence"] = max(0.0, history[0]["confidence"] - 0.2)
    history.append({
        "source_table": "history_only", "source_field": "old_id",
        "target_table": "history_target", "target_field": "old_id",
        "confidence": 0.6, "relation_type": "custom",
    })
    path.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    return str(path)
def test_pipeline_incremental_outputs_are_deterministic(tmp_path, default_config):
    config_path = write_config(
        tmp_path, default_config,
        **{"output.directory": str(tmp_path / "out"),
           "incremental.default_baseline": ""}
    )
    first = run_pipeline(config_path=config_path, base_dir=str(ROOT), use_default_baseline=False)
    assert first.diff is None
    assert "未提供历史规则" in first.warnings[-1]
    assert first.summary()["tables"] == 8
    associations = json.loads((tmp_path / "out" / "relations.json").read_text(encoding="utf-8"))
    baseline = _history(associations["associations"], tmp_path / "history.json")
    result = run_pipeline(config_path=config_path, base_dir=str(ROOT), baseline_path=baseline)
    assert result.diff["summary"] == {"added": 1, "removed": 1,
                                      "confidence_changed": 1, "unchanged": 73}
    assert result.graph["stats"]["changes"] == {"added": 1, "removed": 1,
                                                 "confidence_changed": 1}
    for key in ("rules_json", "rules_yaml", "report_md", "graph_json", "graph_html"):
        assert Path(result.outputs[key]).is_file()
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "增量版本对比" in report and "历史关联失效：1 条" in report
    html = (tmp_path / "out" / "graph.html").read_text(encoding="utf-8")
    assert "history_only.old_id" in html
    names = ("relations.json", "relations.yaml", "report.md", "graph.json", "graph.html")
    before = {name: _digest(tmp_path / "out" / name) for name in names}
    run_pipeline(config_path=config_path, base_dir=str(ROOT), baseline_path=baseline)
    assert before == {name: _digest(tmp_path / "out" / name) for name in names}
def test_pipeline_missing_baseline(tmp_path, default_config):
    config_path = write_config(
        tmp_path, default_config,
        **{"output.directory": str(tmp_path / "out"),
           "incremental.default_baseline": ""}
    )
    with pytest.raises(IncrementalError):
        run_pipeline(config_path=config_path, base_dir=str(ROOT),
                     baseline_path=str(tmp_path / "none.json"))
