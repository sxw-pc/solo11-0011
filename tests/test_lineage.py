"""字段级血缘快照与结构漂移审计的验收测试。"""
import json
import os
from pathlib import Path

import yaml

from tablelink.config import ConfigManager
from tablelink.pipeline import run_pipeline
from tests.conftest import write_config


def _orders(rows=12, uid="user_id"):
    lines = ["order_id,{0},amount".format(uid)]
    lines += ["{0},{1},{2}".format(i, 100 + i, 500 + i) for i in range(1, rows + 1)]
    return "\n".join(lines) + "\n"


def _users(city_nulls=0):
    lines = ["user_id,name,city"]
    for i in range(1, 13):
        city = "" if i <= city_nulls else "city{0}".format(i)
        lines.append("{0},user{1},{2}".format(100 + i, i, city))
    return "\n".join(lines) + "\n"


def _project(tmp_path, default_config, **updates):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "orders.csv").write_text(_orders(), encoding="utf-8")
    (data / "users.csv").write_text(_users(), encoding="utf-8")
    base = {"sources.csv_dirs": ["data"], "sources.sqlite_files": [],
            "explicit.custom_rules_path": "", "incremental.default_baseline": "",
            "output.directory": "out"}
    base.update(updates)
    return write_config(tmp_path, default_config, **base)


def _run(config_path, tmp_path, **kwargs):
    return run_pipeline(config_path=config_path, base_dir=str(tmp_path),
                        use_default_baseline=False, **kwargs)


def _audit(tmp_path):
    return json.loads((tmp_path / "out" / "lineage" / "audit.json").read_text(encoding="utf-8"))


def test_first_run_builds_baseline_only(tmp_path, default_config):
    result = _run(_project(tmp_path, default_config), tmp_path)
    assert result.lineage["status"] == "baseline_initialized"
    audit = _audit(tmp_path)
    assert audit["status"] == "baseline_initialized"
    assert audit["origin"] == "none"
    assert not any(audit["summary"][key] for key in
                   ("tables_added", "tables_removed", "fields_added", "fields_removed",
                    "associations_added", "associations_removed", "associations_changed"))
    snapshot = json.loads((tmp_path / "out" / "lineage" / "snapshot.json").read_text(encoding="utf-8"))
    assert snapshot["snapshot_format"] == "tablelink-lineage-snapshot"
    assert snapshot["snapshot_version"] == "1.0" and snapshot["snapshot_id"].startswith("sha256:")
    markdown = (tmp_path / "out" / "lineage" / "audit.md").read_text(encoding="utf-8")
    assert "已建立基线" in markdown


def test_csv_column_change_attribution(tmp_path, default_config):
    config_path = _project(tmp_path, default_config)
    _run(config_path, tmp_path)
    (tmp_path / "data" / "orders.csv").write_text(_orders(uid="uid"), encoding="utf-8")
    result = _run(config_path, tmp_path)
    audit = _audit(tmp_path)
    assert audit["status"] == "drift_detected" and audit["origin"] == "data"
    removed_fields = audit["source_layer"]["fields_removed"]
    assert [item["endpoint"] for item in removed_fields] == ["orders.user_id"]
    assert removed_fields[0]["origin"] == "data"
    assert removed_fields[0]["source_id"] == "csv:data/orders.csv"
    removed = audit["detection_layer"]["removed"]
    assert [item["key"] for item in removed] == ["orders.user_id->users.user_id"]
    causes = removed[0]["causes"]
    assert causes[0]["kind"] == "field_removed" and causes[0]["endpoint"] == "orders.user_id"
    assert causes[0]["source_id"] == "csv:data/orders.csv"
    assert removed[0]["origin"] == "data"
    markdown = (tmp_path / "out" / "lineage" / "audit.md").read_text(encoding="utf-8")
    assert "orders.user_id" in markdown and "csv:data/orders.csv" in markdown
    assert "orders.user_id->users.user_id" in markdown
    assert result.summary()["lineage"]["origin"] == "data"


def test_deleted_snapshot_rebuilds_baseline(tmp_path, default_config):
    config_path = _project(tmp_path, default_config)
    _run(config_path, tmp_path)
    for path in (tmp_path / "out" / "lineage").iterdir():
        path.unlink()
    result = _run(config_path, tmp_path)
    audit = _audit(tmp_path)
    assert result.lineage["status"] == "baseline_initialized"
    assert audit["status"] == "baseline_initialized" and audit["origin"] == "none"
    assert audit["summary"]["associations_removed"] == 0
    assert audit["summary"]["fields_removed"] == 0


def test_hot_reload_config_change_is_classified(tmp_path, default_config):
    config_path = _project(tmp_path, default_config)
    manager = ConfigManager(config_path, base_dir=str(tmp_path), auto_reload=True)
    run_pipeline(manager=manager, use_default_baseline=False)
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    payload["explicit"]["naming"]["enabled"] = False
    Path(config_path).write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    stat = Path(config_path).stat()
    os.utime(config_path, ns=(stat.st_atime_ns + 1000, stat.st_mtime_ns + 1000))
    result = run_pipeline(manager=manager, use_default_baseline=False)
    audit = _audit(tmp_path)
    assert audit["config_change"]["changed"] is True
    assert audit["config_change"]["sections"] == ["explicit"]
    layer = audit["detection_layer"]
    entries = layer["added"] + layer["removed"] + layer["changed"]
    assert entries and all(item["origin"] == "config" for item in entries)
    assert any("config_change" in [cause["kind"] for cause in item["causes"]]
               for item in entries)
    assert audit["source_layer"]["fields_changed"] == []
    assert audit["origin"] == "config"
    assert result.lineage["status"] == "drift_detected"


def test_broken_csv_isolated_and_snapshot_intact(tmp_path, default_config):
    config_path = _project(tmp_path, default_config)
    _run(config_path, tmp_path)
    (tmp_path / "data" / "broken.csv").write_bytes(b"a,b\n1,\x002\n")
    result = _run(config_path, tmp_path)
    assert result.summary()["tables"] == 2
    audit = _audit(tmp_path)
    degraded = audit["degraded_sources"]
    assert [item["source_id"] for item in degraded] == ["csv:data/broken.csv"]
    assert degraded[0]["state"] == "error" and "NUL" in degraded[0]["error"]
    snapshot = json.loads((tmp_path / "out" / "lineage" / "snapshot.json").read_text(encoding="utf-8"))
    states = {item["source_id"]: item["state"] for item in snapshot["sources"]}
    assert states["csv:data/broken.csv"] == "error"
    assert states["csv:data/orders.csv"] == states["csv:data/users.csv"] == "ok"
    tables = {item["table"] for item in snapshot["tables"]}
    assert tables == {"orders", "users"}
    assert audit["summary"]["sources_added"] == 1
    again = _run(config_path, tmp_path)
    assert _audit(tmp_path)["status"] == "no_drift"
    assert _audit(tmp_path)["degraded_sources"][0]["source_id"] == "csv:data/broken.csv"
    assert again.lineage["status"] == "no_drift"
    (tmp_path / "data" / "broken.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    _run(config_path, tmp_path)
    audit = _audit(tmp_path)
    assert audit["degraded_sources"] == []
    added = audit["source_layer"]["tables_added"]
    assert [item["table"] for item in added] == ["broken"]
    assert added[0]["cause"] == "source_recovered"


def test_csv_file_removed_and_restored(tmp_path, default_config):
    config_path = _project(tmp_path, default_config)
    _run(config_path, tmp_path)
    (tmp_path / "data" / "users.csv").unlink()
    _run(config_path, tmp_path)
    audit = _audit(tmp_path)
    removed_tables = audit["source_layer"]["tables_removed"]
    assert [item["table"] for item in removed_tables] == ["users"]
    assert removed_tables[0]["cause"] == "source_removed"
    assert removed_tables[0]["origin"] == "data"
    removed = audit["detection_layer"]["removed"]
    assert [item["key"] for item in removed] == ["orders.user_id->users.user_id"]
    assert removed[0]["causes"][0]["kind"] == "table_removed"
    assert removed[0]["causes"][0]["table"] == "users"
    (tmp_path / "data" / "users.csv").write_text(_users(), encoding="utf-8")
    _run(config_path, tmp_path)
    audit = _audit(tmp_path)
    assert [item["table"] for item in audit["source_layer"]["tables_added"]] == ["users"]
    assert audit["source_layer"]["tables_added"][0]["cause"] == "source_added"


def test_identical_inputs_produce_byte_identical_audit(tmp_path, default_config):
    config_path = _project(tmp_path, default_config)
    _run(config_path, tmp_path)
    _run(config_path, tmp_path)
    lineage = tmp_path / "out" / "lineage"
    first = {name: (lineage / name).read_bytes()
             for name in ("snapshot.json", "audit.json", "audit.md")}
    result = _run(config_path, tmp_path)
    second = {name: (lineage / name).read_bytes()
              for name in ("snapshot.json", "audit.json", "audit.md")}
    assert first == second
    assert result.lineage["status"] == "no_drift"
    audit = _audit(tmp_path)
    assert audit["baseline"]["snapshot_id"] == audit["current"]["snapshot_id"]


def test_field_stat_drift_detected(tmp_path, default_config):
    config_path = _project(tmp_path, default_config)
    _run(config_path, tmp_path)
    (tmp_path / "data" / "users.csv").write_text(_users(city_nulls=6), encoding="utf-8")
    orders = _orders().splitlines()
    orders[1] = "1,101,abc"
    (tmp_path / "data" / "orders.csv").write_text("\n".join(orders) + "\n", encoding="utf-8")
    _run(config_path, tmp_path)
    changed = {item["endpoint"]: item for item in _audit(tmp_path)["source_layer"]["fields_changed"]}
    city = changed["users.city"]["changes"]["non_null_ratio"]
    assert city["before"] == 1.0 and city["after"] == 0.5 and city["significant"] is True
    dtype = changed["orders.amount"]["changes"]["dtype"]
    assert dtype["before"] == "integer" and dtype["after"] == "string"
    assert dtype["compatible"] is False
    assert changed["users.city"]["origin"] == "data"


def test_unusable_baseline_resets_without_drift(tmp_path, default_config):
    config_path = _project(tmp_path, default_config)
    _run(config_path, tmp_path)
    snapshot_path = tmp_path / "out" / "lineage" / "snapshot.json"
    snapshot_path.write_text("{broken json", encoding="utf-8")
    result = _run(config_path, tmp_path)
    assert result.lineage["status"] == "baseline_reset"
    assert result.lineage["warnings"]
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["snapshot_version"] = "0.9"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")
    result = _run(config_path, tmp_path)
    assert result.lineage["status"] == "baseline_reset"
    audit = _audit(tmp_path)
    assert audit["origin"] == "none" and audit["summary"]["associations_removed"] == 0


def test_lineage_disabled_and_custom_directory(tmp_path, default_config):
    config_path = _project(tmp_path, default_config, **{"lineage.enabled": False})
    result = _run(config_path, tmp_path)
    assert result.lineage is None
    assert not (tmp_path / "out" / "lineage").exists()
    config_path = _project(tmp_path, default_config, **{"lineage.directory": "snap"})
    _run(config_path, tmp_path)
    assert (tmp_path / "snap" / "snapshot.json").is_file()


