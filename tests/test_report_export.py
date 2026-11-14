"""JSON/YAML 规则、Markdown 报告与单文件 HTML 图谱测试。"""
import json, pytest, yaml
from tablelink.detector import build_graph
from tablelink.exceptions import ExportError
from tablelink.reporter import (
    build_markdown,
    build_rules_payload,
    export_graph_json,
    export_rules,
    generate_html_graph,
    write_text,
)
from tablelink.reporter import html_graph
from tablelink.reporter.rule_exporter import load_rule_document
@pytest.fixture(scope="module")
def artifacts(default_dataset, default_config, explicit_associations,
              overlap_associations, fd_associations):
    associations = explicit_associations + overlap_associations + fd_associations
    graph = build_graph(default_dataset, associations)
    diff = {
        "threshold": 0.05,
        "summary": {"added": 1, "removed": 1, "confidence_changed": 1, "unchanged": 2},
        "added": [associations[0]],
        "removed": [dict(associations[-1], confidence=0.4)],
        "confidence_changed": [dict(associations[0], confidence=0.6,
                                    previous_confidence=0.4, confidence_delta=0.2)],
    }
    payload = build_rules_payload(default_dataset, associations, default_config,
                                  diff=diff, graph=graph)
    return associations, graph, diff, payload
def test_payload_and_export_round_trip(tmp_path, artifacts, default_config):
    associations, graph, diff, payload = artifacts
    assert payload["summary"]["association_count"] == len(associations)
    assert payload["dataset"]["table_count"] == 8
    assert payload["summary"]["high_confidence_count"] > 0
    json_path = tmp_path / "rules.json"
    yaml_path = tmp_path / "rules.yaml"
    paths = export_rules(payload, json_path, yaml_path)
    assert set(paths) == {"json", "yaml"}
    loaded = load_rule_document(json_path)
    assert loaded == load_rule_document(yaml_path) == json.loads(json_path.read_text(encoding="utf-8"))
    exported_graph = tmp_path / "graph.json"
    export_graph_json(graph, exported_graph)
    assert json.loads(exported_graph.read_text(encoding="utf-8"))["nodes"]
    text_path = tmp_path / "note.txt"
    assert write_text(text_path, "本地\n").endswith("note.txt")
def test_export_errors(tmp_path, artifacts):
    _, graph, _, payload = artifacts
    with pytest.raises(ExportError):
        export_rules(payload, tmp_path, tmp_path / "ok.yaml")
    with pytest.raises(ExportError):
        export_graph_json(graph, tmp_path)
    with pytest.raises(ExportError):
        load_rule_document(tmp_path / "missing.json")
def test_markdown_sections_and_diff(artifacts, default_dataset, default_config):
    associations, graph, diff, _ = artifacts
    text = build_markdown(default_dataset, associations, graph, default_config, diff=diff)
    for heading in ("数据集概览", "关联类型统计", "高置信度关联清单",
                    "待确认低置信度关联", "异常关联提示", "函数依赖清单",
                    "增量版本对比", "审计说明"):
        assert heading in text
    assert "| 函数依赖 |" in text
    assert "新增关联" in text and "失效关联" in text and "置信度变化" in text
    assert "无。" not in text.split("### 置信度变化")[1]
    plain = build_markdown(default_dataset, [], {"stats": {"table_count": 0, "field_count": 0}},
                           default_config)
    assert "未提供历史关联规则" in plain
    assert "未发现达到阈值的高置信度关联" in plain
    assert "未发现满足阈值的函数依赖" in plain
def test_html_single_file_offline(tmp_path, artifacts, default_config):
    _, graph, diff, _ = artifacts
    path = generate_html_graph(graph, default_config, tmp_path / "graph.html", diff=diff)
    html = open(path, encoding="utf-8").read()
    assert "window.__GRAPH__" in html and "window.__DIFF__" in html
    assert "ECharts" in html and "connect-src 'none'" in html
    assert "<script src=" not in html and "<link rel=\"stylesheet\"" not in html
    assert "cdn." not in html.lower()
    assert '\\u003c/script' not in html
    assert "增量变化" in html
def test_html_missing_asset(tmp_path, monkeypatch, artifacts, default_config):
    _, graph, _, _ = artifacts
    missing = tmp_path / "static"
    missing.mkdir()
    monkeypatch.setattr(html_graph, "STATIC_DIR", str(missing))
    with pytest.raises(ExportError) as exc:
        generate_html_graph(graph, default_config, tmp_path / "x.html")
    assert "本地静态资源" in str(exc.value)
