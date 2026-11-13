"""CSV 加载器单元测试。"""
import copy
from tablelink.loader import CSVDirectoryLoader, Dataset, discover_csv_files
from tests.conftest import ROOT
def test_load_mock_directory_metadata(default_config):
    dataset = CSVDirectoryLoader(default_config, ROOT / "fixtures" / "mock_csv").load(Dataset())
    assert set(dataset.tables) == {"device_base", "sensor_metric", "alarm_info", "maintain_record"}
    table = dataset.tables["device_base"]
    assert table.row_count == 12 and len(table.columns) == 6
    assert table.column("device_id")["cardinality"] == 12
    assert table.column("device_id")["non_null_ratio"] == 1.0
    assert table.column("device_type")["top_values"][0]["count"] >= 4
    assert table.to_dict()["source_type"] == "csv"
    assert table.encoding == "utf-8-sig"
def test_gbk_and_filters(tmp_path, default_config):
    (tmp_path / "中文表.csv").write_bytes("编号,名称\n甲,设备一\n乙,设备二\n".encode("gbk"))
    (tmp_path / "skip_me.csv").write_text("id,value\n1,2\n", encoding="utf-8")
    config = copy.deepcopy(default_config)
    config["sources"]["exclude_fields"] = ["名称"]
    dataset = CSVDirectoryLoader(config, tmp_path, name_filter=lambda name: "skip" not in name).load(Dataset())
    table = dataset.tables["中文表"]
    assert table.row_count == 2 and table.column_names() == ["编号"]
    assert "skip_me" not in dataset.tables
    assert any(item["kind"] == "info" for item in dataset.errors)
    assert discover_csv_files(tmp_path)
def test_edge_case_files(default_config):
    dataset = CSVDirectoryLoader(default_config, ROOT / "fixtures" / "edge_cases").load(Dataset())
    assert dataset.tables["empty_table"].row_count == 0
    assert dataset.tables["all_empty_field"].column("blank_a")["dtype"] == "empty"
    assert dataset.tables["isolated_table"].row_count == 10
    assert "broken_rows" not in dataset.tables
    assert any("字段数" in item["message"] for item in dataset.errors)
def test_bad_encoding_and_nul(tmp_path, default_config):
    (tmp_path / "bad.csv").write_bytes(b"\xff\xff\xff\xff")
    (tmp_path / "nul.csv").write_bytes(b"id,value\n1,\x00\n")
    dataset = CSVDirectoryLoader(default_config, tmp_path).load(Dataset())
    assert not dataset.tables
    messages = " ".join(item["message"] for item in dataset.errors)
    assert "编码" in messages and "NUL" in messages
def test_missing_and_empty_directory(tmp_path, default_config):
    dataset = CSVDirectoryLoader(default_config, tmp_path / "missing").load(Dataset())
    assert any("目录不存在" in item["message"] for item in dataset.errors)
    dataset = CSVDirectoryLoader(default_config, tmp_path).load(Dataset())
    assert any("没有 .csv" in item["message"] for item in dataset.errors)
def test_duplicate_table_name_renamed(default_config):
    copy_config = copy.deepcopy(default_config)
    loader = CSVDirectoryLoader(copy_config, ROOT / "fixtures" / "mock_csv")
    dataset = Dataset()
    dataset.add_table(loader._load_file(ROOT / "fixtures" / "mock_csv" / "device_base.csv"))
    dataset.add_table(loader._load_file(ROOT / "fixtures" / "mock_csv" / "device_base.csv"))
    assert "device_base__csv" in dataset.tables
    assert any("重命名" in item["message"] for item in dataset.errors)
