"""历史规则加载、增量差分与标记测试。"""
import json, pytest, yaml
from tablelink.exceptions import IncrementalError
from tablelink.incremental import compare, load_history, tag_current
def _item(source, target, confidence=0.8, **extra):
    value = {"source_table": source, "source_field": "id",
             "target_table": target, "target_field": "id", "confidence": confidence}
    value.update(extra)
    return value
def _write(path, payload):
    if path.suffix == ".json":
        path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return str(path)
def test_load_json_yaml_and_dedupe(tmp_path):
    path = tmp_path / "history.json"
    loaded = load_history(_write(path, [_item("a", "b", 0.7), _item("a", "b", 0.9)]))
    assert len(loaded) == 1 and loaded[0]["confidence"] == 0.9
    assert loaded[0]["relation_type"] == "unknown"
    assert loaded[0]["detection_sources"] == ["history"]
    yaml_item = dict(_item("c", "d"), relation_type="custom", relation_types=["custom"])
    loaded = load_history(_write(tmp_path / "history.yaml", {"associations": [yaml_item]}))
    assert loaded[0]["relation_types"] == ["custom"]
@pytest.mark.parametrize("payload,message", [
    ({"other": []}, "associations"), ([1], "不是映射"),
    ([{"source_table": "a"}], "缺少字段"), ([dict(_item("a", "b"), confidence="high")], "不是数字"),
    ([_item("a", "b", 2)], "0~1"),
])
def test_invalid_history(tmp_path, payload, message):
    with pytest.raises(IncrementalError) as exc:
        load_history(_write(tmp_path / "bad.json", payload))
    assert message in str(exc.value)
def test_missing_and_unparsable_history(tmp_path):
    with pytest.raises(IncrementalError) as exc:
        load_history(str(tmp_path / "none.json"))
    assert "不存在" in str(exc.value)
    path = tmp_path / "bad.yaml"
    path.write_text("items: [\n", encoding="utf-8")
    with pytest.raises(IncrementalError) as exc:
        load_history(str(path))
    assert "解析失败" in str(exc.value)
def test_old_baseline_degrades_and_merges(tmp_path):
    old = [_item("a", "b", 0.7, relation_type="value_overlap"),
           _item("a", "b", 0.9, relation_type="explicit_fk")]
    loaded = load_history(_write(tmp_path / "old.json", {"associations": old}))
    assert len(loaded) == 1
    item = loaded[0]
    assert item["confidence"] == 0.9 and item["relation_type"] == "explicit_fk"
    assert item["relation_types"] == ["explicit_fk", "value_overlap"]
    assert item["detection_sources"] == ["history"] and item["evidence"] == []
    assert item["source_groups"] == [] and len(item["detections"]) == 2
def test_compare_and_tag_current():
    history = [_item("a", "b", 0.8), _item("c", "d", 0.7), _item("e", "f", 0.6)]
    current = [_item("a", "b", 0.9), _item("c", "d", 0.72), _item("g", "h", 0.5)]
    diff = compare(current, history, threshold=0.05)
    assert diff["summary"] == {"added": 1, "removed": 1,
                               "confidence_changed": 1, "unchanged": 1}
    assert diff["added"][0]["change"] == "added"
    changed = diff["confidence_changed"][0]
    assert changed["previous_confidence"] == 0.8 and changed["confidence_delta"] == 0.1
    assert diff["removed"][0]["source_table"] == "e"
    tagged = tag_current(current, diff)
    assert tagged[0]["change"] == "confidence_changed" and tagged[0]["change_delta"] == 0.1
    assert tagged[1]["change"] is None and tagged[2]["change"] == "added"
