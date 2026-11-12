"""SQLite 加载器单元测试。"""
import copy, sqlite3
from tablelink.loader import Dataset, SQLiteLoader
from tests.conftest import ROOT
DB = ROOT / "fixtures" / "mock_sqlite" / "env_monitor.db"
def test_load_and_foreign_keys(default_config):
    dataset = SQLiteLoader(default_config, DB).load(Dataset())
    assert set(dataset.tables) == {"room_info", "device_registry", "engineer_info", "sensor_calibration"}
    registry = dataset.tables["device_registry"]
    assert registry.primary_keys == ["device_id"]
    assert registry.foreign_keys[0]["referred_table"] == "room_info"
    calibration = dataset.tables["sensor_calibration"]
    assert calibration.foreign_keys[0]["columns"] == ["device_id"]
    assert registry.to_dict()["foreign_keys"]
def test_table_and_field_filters(default_config):
    config = copy.deepcopy(default_config)
    config["sources"]["exclude_fields"] = ["firmware", "contact"]
    loader = SQLiteLoader(config, DB, name_filter=lambda name: name != "room_info")
    dataset = loader.load(Dataset())
    assert "room_info" not in dataset.tables
    assert dataset.tables["device_registry"].column("firmware") is None
    assert any(item["kind"] == "info" for item in dataset.errors)
def test_missing_invalid_and_empty_database(tmp_path, default_config):
    loader = SQLiteLoader(default_config, tmp_path / "missing.db")
    assert any("不存在" in item["message"] for item in loader.load(Dataset()).errors)
    invalid = tmp_path / "invalid.db"
    invalid.write_text("not a sqlite database", encoding="utf-8")
    assert any("失败" in item["message"] for item in SQLiteLoader(default_config, invalid).load(Dataset()).errors)
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    errors = SQLiteLoader(default_config, empty).load(Dataset()).errors
    assert any("没有可用表" in item["message"] for item in errors)
