"""血缘快照比对与序列化的单元测试（手工构造快照，覆盖归因分支）。"""
import json

from tablelink.lineage import build_snapshot, compare_snapshots, dump_snapshot, load_snapshot
from tests.conftest import make_dataset


def _snapshot(associations=(), sources=(), tables=(), sections=None, custom="sha256:r"):
    return {
        "snapshot_format": "tablelink-lineage-snapshot",
        "snapshot_version": "1.0",
        "generator": {"tool": "tablelink-mapper", "tool_version": "1.0.0"},
        "config": {"sections": sections or {"sources": "s", "explicit": "e",
                                            "overlap": "o", "fd": "f"},
                   "fingerprint": "x", "custom_rules": custom},
        "sources": list(sources), "tables": list(tables),
        "associations": list(associations), "load_errors": [],
        "snapshot_id": "sha256:id",
    }


def _assoc(confidence=0.8, relation="value_overlap"):
    return {"key": "a.b->c.d", "source_table": "a", "source_field": "b",
            "target_table": "c", "target_field": "d", "relation_type": relation,
            "relation_types": [relation], "confidence": confidence,
            "detection_sources": ["value_overlap"], "detections": [],
            "evidence_fingerprint": "sha256:e", "details_fingerprint": "sha256:f"}


def _source(**updates):
    entry = {"source_id": "csv:d/a.csv", "source_type": "csv", "path": "d/a.csv",
             "state": "ok", "fingerprint": "sha256:1", "encoding": "utf-8",
             "tables": ["a"], "error": None}
    entry.update(updates)
    return entry


def _table(**field_updates):
    field = {"field": "b", "dtype": "string", "non_null_ratio": 1.0,
             "cardinality": 5, "unique_ratio": 1.0, "value_fingerprint": "sha256:v"}
    field.update(field_updates)
    return {"table": "a", "source_id": "csv:d/a.csv", "source_type": "csv",
            "row_count": 5, "primary_keys": [], "foreign_keys": [],
            "fields": [field]}


def test_compare_detector_and_custom_rules_origins():
    old = _snapshot(associations=[_assoc()])
    new = _snapshot(associations=[_assoc(relation="explicit_naming")])
    audit = compare_snapshots(old, new)
    entry = audit["detection_layer"]["changed"][0]
    assert entry["origin"] == "detector"
    assert entry["causes"][0]["kind"] == "detector_behavior"
    assert entry["changes"]["relation_type"]["after"] == "explicit_naming"
    audit = compare_snapshots(_snapshot(custom="sha256:y"),
                              _snapshot(associations=[_assoc()], custom="sha256:x"))
    assert audit["config_change"]["custom_rules_changed"] is True
    assert audit["detection_layer"]["added"][0]["origin"] == "config"
    assert audit["detection_layer"]["added"][0]["causes"][0]["kind"] == "custom_rules_change"


def test_compare_mixed_origin_and_version_note():
    sections = {"sources": "s", "explicit": "e", "overlap": "o", "fd": "f"}
    old = _snapshot(associations=[_assoc()], sources=[_source(encoding=None)],
                    tables=[_table()], sections=sections)
    new = _snapshot(associations=[_assoc(confidence=0.6)],
                    sources=[_source(encoding=None, fingerprint="sha256:2")],
                    tables=[_table()], sections=dict(sections, overlap="o2"))
    new["generator"] = {"tool": "tablelink-mapper", "tool_version": "1.1.0"}
    audit = compare_snapshots(old, new)
    entry = audit["detection_layer"]["changed"][0]
    kinds = {cause["kind"] for cause in entry["causes"]}
    assert kinds == {"source_data_changed", "config_change"}
    assert entry["origin"] == "mixed" and audit["origin"] == "mixed"
    assert audit["config_change"]["tool_version_changed"] is True
    assert audit["notes"]


def test_source_level_diff_branches():
    old = _snapshot(sources=[_source()], tables=[_table()])
    # 仅编码变化且 sources 配置段变化 → 配置归因
    sections = {"sources": "s2", "explicit": "e", "overlap": "o", "fd": "f"}
    new = _snapshot(sources=[_source(encoding="gbk")], tables=[_table()],
                    sections=sections)
    audit = compare_snapshots(old, new)
    changed = audit["source_layer"]["sources"]["changed"]
    assert changed[0]["changes"]["encoding"] == {"before": "utf-8", "after": "gbk"}
    assert audit["config_change"]["sections"] == ["sources"]
    # 字段统计变化（基数/唯一率/内容）且文件内容变化 → 数据归因
    new = _snapshot(sources=[_source(fingerprint="sha256:2")],
                    tables=[_table(cardinality=3, unique_ratio=0.6,
                                   value_fingerprint="sha256:w")])
    audit = compare_snapshots(old, new)
    entry = audit["source_layer"]["fields_changed"][0]
    assert entry["changes"]["cardinality"] == {"before": 5, "after": 3}
    assert entry["changes"]["content_changed"] is True
    assert entry["origin"] == "data"
    # 来源缺失 → 降级清单与表消失归因
    missing = _source(state="missing", fingerprint=None, tables=[])
    audit = compare_snapshots(old, _snapshot(sources=[missing], tables=[]))
    assert audit["degraded_sources"][0]["state"] == "missing"
    assert audit["source_layer"]["tables_removed"][0]["cause"] == "source_degraded"


def test_build_snapshot_deterministic(default_config):
    import pandas as pd
    frames = {"t1": pd.DataFrame({"id": [1, 2, 3], "v": ["a", "b", "a"]}),
              "t2": pd.DataFrame({"id": [1, 2, 4], "w": [1.0, 2.0, 3.0]})}
    dataset = make_dataset(default_config, frames)
    first = dump_snapshot(build_snapshot(dataset, [], default_config, "."))
    second = dump_snapshot(build_snapshot(dataset, [], default_config, "."))
    assert first == second
    snapshot = json.loads(first)
    assert [item["table"] for item in snapshot["tables"]] == ["t1", "t2"]
    fields = snapshot["tables"][0]["fields"]
    assert [item["field"] for item in fields] == ["id", "v"]
    assert fields[1]["value_fingerprint"].startswith("sha256:")


def test_load_snapshot_errors(tmp_path):
    assert load_snapshot(str(tmp_path / "none.json")) == (None, None)
    path = tmp_path / "bad.json"
    path.write_text("[1,2]", encoding="utf-8")
    snapshot, problem = load_snapshot(str(path))
    assert snapshot is None and "JSON 对象" in problem
    path.write_text(json.dumps({"snapshot_format": "x"}), encoding="utf-8")
    assert "格式标识" in load_snapshot(str(path))[1]
    payload = _snapshot()
    payload.pop("sources")
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert "sources" in load_snapshot(str(path))[1]
