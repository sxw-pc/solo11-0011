"""函数依赖检测测试：完全/部分依赖、跨表连接与噪声过滤。"""
import copy, pandas as pd
from tablelink.detector import detect_fd
from tests.conftest import make_dataset
def _find(result, source, target):
    return [item for item in result if (item["source_table"], item["source_field"],
                                        item["target_table"], item["target_field"]) == source + target]
def test_default_complete_and_cross_table(fd_associations, default_config):
    assert len(fd_associations) >= 10
    assert all(item["confidence"] >= default_config["fd"]["confidence_threshold"]
               for item in fd_associations)
    scopes = {item["details"]["scope"] for item in fd_associations}
    assert scopes == {"same_table", "cross_table"}
    assert all(item["details"]["dependency"] == "complete" for item in fd_associations)
    assert all(item["evidence"] for item in fd_associations)
    assert not _find(fd_associations, ("maintain_record", "device_id"),
                     ("maintain_record", "result"))
    cross = [item for item in fd_associations if item["details"]["scope"] == "cross_table"]
    assert cross and all("via" in item["details"] for item in cross)
def test_disabled_and_min_rows(default_dataset, default_config):
    config = copy.deepcopy(default_config)
    config["fd"]["enabled"] = False
    assert detect_fd(default_dataset, config) == []
    config["fd"]["enabled"] = True
    config["fd"]["min_rows"] = 1000
    assert detect_fd(default_dataset, config) == []
def test_partial_dependency(default_config):
    config = copy.deepcopy(default_config)
    config["fd"]["confidence_threshold"] = 0.8
    source = [key for key in "ABCDEFGHIJ" for _ in range(2)]
    target = ["x"] * 18 + ["y", "z"]
    dataset = make_dataset(config, {"sample": pd.DataFrame({"code": source, "state": target})})
    result = detect_fd(dataset, config)
    pair = _find(result, ("sample", "code"), ("sample", "state"))
    assert pair and pair[0]["details"]["dependency"] == "partial"
    assert pair[0]["confidence"] == 0.9
    assert len(pair[0]["evidence"]) == 5
def test_unique_source_and_target_cardinality_guards(default_config):
    config = copy.deepcopy(default_config)
    rows = list(range(10))
    dataset = make_dataset(config, {
        "solo": pd.DataFrame({"only": rows, "constant": ["same"] * 10}),
    })
    assert detect_fd(dataset, config) == []
    config["fd"]["max_per_table"] = 1
    wide = pd.DataFrame({"key": ["A"] * 10, "one": ["x", "y"] * 5,
                         "two": ["u", "v"] * 5, "three": ["i", "j"] * 5})
    result = detect_fd(make_dataset(config, {"wide": wide}), config)
    assert len(result) == 1
def test_cross_table_edges(default_config):
    keys = list(range(1, 6))
    left = pd.DataFrame({"key": keys * 4, "payload": ["p"] * 20})
    right = pd.DataFrame({"key": keys * 2, "category": ["a", "a", "b", "b", "a"] * 2})
    dataset = make_dataset(default_config, {"left": left, "right": right})
    link = {"source_table": "left", "source_field": "key",
            "target_table": "right", "target_field": "key"}
    result = detect_fd(dataset, default_config, [link, link, {
        "source_table": "left", "source_field": "missing",
        "target_table": "right", "target_field": "key",
    }, {"source_table": "ghost", "source_field": "key",
        "target_table": "right", "target_field": "key"}])
    cross = _find(result, ("left", "key"), ("right", "category"))
    assert cross and cross[0]["details"]["scope"] == "cross_table"
    assert cross[0]["details"]["matched_rows"] == 20
    invalid = {"source_table": "left", "source_field": "key",
               "target_table": "left", "target_field": "key"}
    assert not [item for item in detect_fd(dataset, default_config, [invalid])
                if item["details"]["scope"] == "cross_table"]
def test_frame_missing_columns(default_config):
    dataset = make_dataset(default_config, {
        "a": pd.DataFrame({"key": ["A"] * 10, "v": ["x", "y"] * 5}),
    })
    dataset.tables["a"].frame = None
    assert detect_fd(dataset, default_config, [{
        "source_table": "a", "source_field": "key",
        "target_table": "a", "target_field": "v"}]) == []
