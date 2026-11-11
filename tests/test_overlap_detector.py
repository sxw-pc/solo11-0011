"""隐式值域关联检测单元测试。"""
import copy, pandas as pd
from tablelink.detector import detect_overlap
from tablelink.loader import Dataset
from tests.conftest import make_dataset
def _pair(result, source, source_field, target, target_field):
    return [item for item in result if (
        item["source_table"], item["source_field"],
        item["target_table"], item["target_field"],
    ) == (source, source_field, target, target_field)]
def test_high_confidence_associations(overlap_associations, default_config):
    assert overlap_associations
    assert all(item["confidence"] >= default_config["overlap"]["threshold"] for item in overlap_associations)
    assert all(len(item["evidence"]) >= 3 for item in overlap_associations)
    assert _pair(overlap_associations, "sensor_metric", "device_id", "device_base", "device_id")
    assert _pair(overlap_associations, "maintain_record", "engineer_id", "engineer_info", "engineer_id")
    assert _pair(overlap_associations, "device_base", "room_id", "room_info", "room_id")
def test_high_cardinality_ids_filtered(overlap_associations):
    involved = {field for item in overlap_associations for field in
                (item["source_field"], item["target_field"])}
    assert "metric_id" not in involved and "calibration_id" not in involved
def test_strict_type_and_same_table(default_config):
    frame_a = pd.DataFrame({"code_id": [1, 2, 3, 4, 5]})
    frame_b = pd.DataFrame({"code_id": ["1", "2", "3", "4", "5"]})
    dataset = make_dataset(default_config, {"a": frame_a, "b": frame_b})
    assert detect_overlap(dataset, default_config) == []
    config = copy.deepcopy(default_config)
    config["overlap"]["strict_type"] = False
    assert detect_overlap(dataset, config)
    config = copy.deepcopy(default_config)
    config["overlap"]["same_table"] = True
    repeated = pd.DataFrame({"x_id": list("abcabcabca"), "y_id": list("abcabcabca")})
    dataset = make_dataset(config, {"one": repeated})
    assert detect_overlap(dataset, config)
def test_sparse_and_high_cardinality_disabled(default_config):
    config = copy.deepcopy(default_config)
    config["overlap"]["allow_reference_high_cardinality"] = False
    values = ["D{0}".format(i) for i in range(1, 11)]
    dataset = make_dataset(config, {
        "left": pd.DataFrame({"device_id": values, "sparse_id": [None] * 9 + ["D1"]}),
        "right": pd.DataFrame({"device_id": values}),
    })
    assert detect_overlap(dataset, config) == []
def test_pair_limit_and_empty_dataset(default_config):
    config = copy.deepcopy(default_config)
    config["overlap"]["max_pairs"] = 1
    dataset = make_dataset(config, {
        "a": pd.DataFrame({"x_id": list("abcabc")}),
        "b": pd.DataFrame({"x_id": list("abcabc")}),
        "c": pd.DataFrame({"x_id": list("abcabc")}),
    })
    assert len(detect_overlap(dataset, config)) <= 1
    assert detect_overlap(Dataset(), config) == []
