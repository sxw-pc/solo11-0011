"""结构化外键契约、复合外键检测与历史形态兼容测试。"""
import copy
import hashlib
import json
from tablelink.detector import detect_explicit
from tablelink.incremental import compare, load_history
from tablelink.loader import Dataset, SQLiteLoader
from tablelink.loader.fk_metadata import action_confidence, normalize_action
from tablelink.pipeline import run_pipeline
from tests.conftest import ROOT, write_config
COMPOSITE_DIR = ROOT / "fixtures" / "composite_sqlite"
MAIN_DB = COMPOSITE_DIR / "composite_main.db"
AUX_DB = COMPOSITE_DIR / "composite_aux.db"
def _config(config):
    copied = copy.deepcopy(config)
    copied["explicit"]["custom_rules_path"] = None
    return copied
def _load_main(config, **kwargs):
    return SQLiteLoader(config, MAIN_DB, **kwargs).load(Dataset())
def _native(result):
    return [item for item in result if item["detection_sources"] == ["sqlite_foreign_key"]]
def test_action_confidence_rounding():
    assert action_confidence("NO ACTION", "NO ACTION") == 1.0
    assert action_confidence("SET NULL", "CASCADE") == 0.9406  # 含置空动作 → 向下取整
    assert action_confidence("RESTRICT", "CASCADE") == 0.9801  # 无置空动作 → 四舍五入
    assert action_confidence("CASCADE", "CASCADE") == 0.9702
    assert action_confidence("SET NULL", "SET NULL") == 0.912
    assert action_confidence(None, "bogus") == 1.0             # 未知动作按 NO ACTION
    assert normalize_action(" set null ") == "SET NULL"
def test_loader_exposes_structured_composite_spec(default_config):
    dataset = _load_main(default_config)
    spec = dataset.tables["shipments"].foreign_keys[0]
    assert spec["name"] == "fk_shipment_order_store"
    assert spec["columns"] == ["order_id", "store_id"]         # 列序与声明一致
    assert spec["referred_columns"] == ["order_id", "store_id"]
    assert spec["referred_table"] == "order_stores"
    assert spec["referred_schema"] == "main" and spec["referred_key"] == "order_stores"
    assert spec["on_delete"] == "SET NULL" and spec["on_update"] == "CASCADE"
    assert spec["deferrable"] is True and spec["initially_deferred"] is True
    assert spec["composite"] is True
    orders = dataset.tables["orders"].foreign_keys[0]
    assert orders["composite"] is False and orders["on_delete"] == "NO ACTION"
def test_loader_attached_schema_and_fallbacks(default_config, tmp_path):
    dataset = SQLiteLoader(
        default_config, MAIN_DB,
        attach={"tenant_aux": AUX_DB, "ghost": tmp_path / "none.db", "bad!": AUX_DB},
    ).load(Dataset())
    spec = dataset.tables["tenant_aux.inventory"].foreign_keys[0]
    assert spec["referred_schema"] == "tenant_aux"
    assert spec["referred_key"] == "tenant_aux.warehouses"
    assert spec["on_delete"] == "CASCADE"
    moves = dataset.tables["tenant_aux.stock_moves"].foreign_keys[0]
    assert moves["columns"] == ["sku", "warehouse_id"]         # PRAGMA seq 还原列序
    assert moves["composite"] is True
    notes = dataset.tables["tenant_aux.notes"].foreign_keys[0]
    assert notes["referred_columns"] == ["warehouse_id"]       # 隐式列回退到目标主键
    messages = [item["message"] for item in dataset.errors]
    assert any("不存在" in message for message in messages)    # 缺失附加库降级为提示
    assert any("非法" in message for message in messages)      # 非法 schema 名降级为提示
    assert "orders" in dataset.tables                          # 主库表照常加载
def test_detector_composite_single_record(default_config):
    config = _config(default_config)
    dataset = _load_main(config)
    result = _native(detect_explicit(dataset, config, str(ROOT)))
    composite = [item for item in result if item["details"].get("composite")]
    assert len(composite) == 1                                 # 复合键只有一条整体记录
    item = composite[0]
    assert item["source_table"] == "shipments"
    assert item["source_field"] == "order_id+store_id"         # 单一整体端点
    assert item["target_field"] == "order_id+store_id"
    assert item["details"]["source_fields"] == ["order_id", "store_id"]
    assert item["confidence"] == 0.9406                        # SET NULL → 向下取整
    assert item["details"]["matched_values"] == 6
    assert len(item["evidence"][0]["source_value"]) == 2       # 元组级证据
    singles = [item for item in result if not item["details"].get("composite")]
    assert [item["source_field"] for item in singles] == ["customer_id"]
    assert singles[0]["confidence"] == 1.0                     # 单列外键仍走原路径
    assert set(singles[0]["details"]) == {"constraint", "matched_values", "message"}
    assert any("未加载" in item["message"] for item in dataset.errors)  # 悬空外键提示
def test_incremental_historical_composite_forms(tmp_path):
    current = [{
        "source_table": "shipments", "source_field": "order_id+store_id",
        "target_table": "order_stores", "target_field": "order_id+store_id",
        "confidence": 0.9406, "relation_type": "explicit_fk",
        "details": {"source_fields": ["order_id", "store_id"],
                    "target_fields": ["order_id", "store_id"]},
    }]
    history = tmp_path / "history.json"
    history.write_text(json.dumps([{                           # 无列序的整体历史形态
        "source_table": "shipments", "target_table": "order_stores",
        "source_fields": ["store_id", "order_id"],
        "target_fields": ["store_id", "order_id"], "confidence": 1.0,
    }]), encoding="utf-8")
    diff = compare(current, load_history(str(history)))
    assert diff["summary"] == {"added": 0, "removed": 0,
                               "confidence_changed": 0, "unchanged": 1}
    split = [dict(source_table="shipments", source_field=field,  # 拆分型历史形态
                  target_table="order_stores", target_field=field,
                  confidence=1.0, relation_type="explicit_fk")
             for field in ("order_id", "store_id")]
    diff = compare(current, split)
    assert diff["summary"] == {"added": 0, "removed": 0,
                               "confidence_changed": 0, "unchanged": 1}
    diff = compare(current, split[:1])                         # 只覆盖一半仍是真实变化
    assert diff["summary"]["added"] == 1 and diff["summary"]["removed"] == 1
def test_pipeline_composite_output_and_bad_db(tmp_path, default_config):
    broken = tmp_path / "broken.db"
    broken.write_text("not a sqlite database", encoding="utf-8")
    config_path = write_config(
        tmp_path, default_config,
        **{"sources.sqlite_files": ["fixtures/composite_sqlite/composite_main.db", str(broken)],
           "explicit.custom_rules_path": None,
           "output.directory": str(tmp_path / "out"),
           "incremental.default_baseline": ""})
    run_pipeline(config_path=config_path, base_dir=str(ROOT), use_default_baseline=False)
    payload = json.loads((tmp_path / "out" / "relations.json").read_text(encoding="utf-8"))
    composite = [item for item in payload["associations"] if item["details"].get("composite")]
    assert len(composite) == 1                                 # 输出里复合关系只有一个端点
    assert composite[0]["source_field"] == "order_id+store_id"
    assert composite[0]["details"]["source_fields"] == ["order_id", "store_id"]
    assert any(item["source_table"] == "device_base"
               for item in payload["associations"])            # 坏库不拖垮 CSV 关系
    assert any("文件头校验失败" in item["message"]
               for item in payload["dataset"]["load_errors"])
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "文件头校验失败" in report                          # 报告含坏库异常提示
    digest = hashlib.sha256((tmp_path / "out" / "relations.json").read_bytes()).hexdigest()
    run_pipeline(config_path=config_path, base_dir=str(ROOT), use_default_baseline=False)
    assert digest == hashlib.sha256(
        (tmp_path / "out" / "relations.json").read_bytes()).hexdigest()
def test_default_baseline_shows_no_churn(tmp_path, default_config):
    config_path = write_config(
        tmp_path, default_config, **{"output.directory": str(tmp_path / "out")})
    result = run_pipeline(config_path=config_path, base_dir=str(ROOT))
    assert result.diff["summary"] == {"added": 1, "removed": 1,
                                      "confidence_changed": 1, "unchanged": 73}
