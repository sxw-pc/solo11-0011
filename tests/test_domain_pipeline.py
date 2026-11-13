"""主题域能力端到端：产物复现、关闭态隔离、导出载体与 Web 控制台。"""
import copy
import hashlib
import json
from pathlib import Path
import yaml
from tablelink.pipeline import run_pipeline
from tablelink.web.app import create_app
from tests.conftest import ROOT, write_config
def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _base_config(tmp_path, default_config):
    return write_config(tmp_path, default_config,
                        **{"output.directory": str(tmp_path / "out"),
                           "incremental.default_baseline": ""})
def _enable_domain(tmp_path, default_config):
    config_path = _base_config(tmp_path, default_config)
    payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    payload["domain"] = copy.deepcopy(default_config["domain"])
    payload["domain"]["enabled"] = True
    Path(config_path).write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return config_path
def test_disabled_domain_leaves_all_artifacts_unchanged(tmp_path, default_config):
    config_path = _base_config(tmp_path, default_config)
    result = run_pipeline(config_path=config_path, base_dir=str(ROOT),
                          use_default_baseline=False)
    assert result.domain_result is None
    payload = json.loads((tmp_path / "out" / "relations.json").read_text(encoding="utf-8"))
    graph = json.loads((tmp_path / "out" / "graph.json").read_text(encoding="utf-8"))
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    html = (tmp_path / "out" / "graph.html").read_text(encoding="utf-8")
    assert "domain" not in payload and "domain" not in graph
    assert all("domain_id" not in node for node in graph["nodes"])
    assert "主题域自动划分" not in report
    assert "domainFilter" not in html and "TableLinkDomain" not in html
def test_enabled_pipeline_is_byte_reproducible(tmp_path, default_config):
    config_path = _enable_domain(tmp_path, default_config)
    first = run_pipeline(config_path=config_path, base_dir=str(ROOT),
                         use_default_baseline=False)
    assert first.domain_result and first.domain_result["enabled"] is True
    names = ("relations.json", "relations.yaml", "report.md", "graph.json", "graph.html")
    before = {n: _digest(tmp_path / "out" / n) for n in names}
    run_pipeline(config_path=config_path, base_dir=str(ROOT), use_default_baseline=False)
    assert before == {n: _digest(tmp_path / "out" / n) for n in names}
def test_enabled_artifacts_carry_domain_section(tmp_path, default_config):
    config_path = _enable_domain(tmp_path, default_config)
    run_pipeline(config_path=config_path, base_dir=str(ROOT), use_default_baseline=False)
    payload = json.loads((tmp_path / "out" / "relations.json").read_text(encoding="utf-8"))
    yaml_payload = yaml.safe_load((tmp_path / "out" / "relations.yaml").read_text(encoding="utf-8"))
    assert payload["domain"] == yaml_payload["domain"]
    graph = json.loads((tmp_path / "out" / "graph.json").read_text(encoding="utf-8"))
    table_nodes = [n for n in graph["nodes"] if n["node_type"] == "table"]
    assert graph["domain"]["enabled"] is True
    assert all("domain_role" in n and "domain_id" in n for n in table_nodes)
    report = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "## 8. 主题域自动划分" in report and "## 9. 审计说明" in report
    html = (tmp_path / "out" / "graph.html").read_text(encoding="utf-8")
    assert "domainFilter" in html and "TableLinkDomain" in html
    assert "connect-src 'none'" in html
def test_summary_exposes_domain_stats(tmp_path, default_config):
    config_path = _enable_domain(tmp_path, default_config)
    result = run_pipeline(config_path=config_path, base_dir=str(ROOT),
                          use_default_baseline=False)
    assert result.summary()["domains"] == result.domain_result["stats"]
def test_web_scan_graph_and_page_expose_domain(tmp_path, default_config):
    config_path = _enable_domain(tmp_path, default_config)
    app = create_app(config_path, base_dir=str(ROOT))
    app.config.update(TESTING=True)
    http = app.test_client()
    response = http.post("/api/scan", json={})
    assert response.status_code == 200
    assert response.get_json()["summary"]["domains"]["domain_count"] >= 1
    graph = http.get("/api/graph").get_json()["graph"]
    assert graph["domain"]["enabled"] is True
    assert all("domain_role" in n for n in graph["nodes"] if n["node_type"] == "table")
    page = http.get("/").get_data(as_text=True)
    assert "webDomain" in page and "domain_ui.js" in page
    offline = http.get("/files/graph_html").get_data(as_text=True)
    assert "TableLinkDomain" in offline and "domainFilter" in offline
def test_web_disabled_hides_domain_controls(tmp_path, default_config):
    config_path = _base_config(tmp_path, default_config)
    app = create_app(config_path, base_dir=str(ROOT))
    app.config.update(TESTING=True)
    http = app.test_client()
    http.post("/api/scan", json={})
    assert "domain" not in http.get("/api/graph").get_json()["graph"]
    page = http.get("/").get_data(as_text=True)
    assert 'id="webDomainField" hidden' in page
