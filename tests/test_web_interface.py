"""Flask 本地 Web 控制台端到端测试。"""
from pathlib import Path
import pytest
from tablelink.web import app as web_module, create_app
from tests.conftest import ROOT, write_config
@pytest.fixture
def client(tmp_path, default_config):
    config_path = write_config(
        tmp_path, default_config,
        **{"output.directory": str(tmp_path / "out"),
           "incremental.default_baseline": ""}
    )
    app = create_app(config_path, base_dir=str(ROOT))
    app.config.update(TESTING=True)
    return app.test_client(), app, tmp_path
def test_index_config_and_empty_state(client):
    http, app, _ = client
    page = http.get("/")
    assert page.status_code == 200 and "本地控制台" in page.get_data(as_text=True)
    assert http.get("/api/config").get_json()["config"]["web"]["host"] == "127.0.0.1"
    assert http.get("/api/graph").status_code == 404
    assert http.get("/api/report").status_code == 404
    assert http.get("/files/rules_json").status_code == 404
    assert http.get("/missing").status_code == 404
    assert http.get("/missing").is_json
    assert http.get("/", environ_base={"REMOTE_ADDR": "10.0.0.1"}).status_code == 403
def test_scan_and_downloads(client):
    http, app, tmp_path = client
    assert http.post("/api/scan", json={"baseline": str(tmp_path / "none.json")}).status_code == 400
    response = http.post("/api/scan", json={})
    assert response.status_code == 200
    summary = response.get_json()["summary"]
    assert summary["tables"] == 8 and summary["associations"] > 40
    graph = http.get("/api/graph").get_json()
    assert graph["ok"] and graph["graph"]["nodes"]
    report = http.get("/api/report").get_json()
    assert report["ok"] and "表链测绘仪分析报告" in report["markdown"]
    for key in ("rules_json", "rules_yaml", "report_md", "graph_json", "graph_html"):
        assert http.get("/files/" + key).status_code == 200
    assert http.get("/files/nope").status_code == 404
    assert http.post("/api/config/reload").get_json()["ok"] is True
    state = app.extensions["tablelink"]
    state["result"].outputs["graph_json"] = str(tmp_path / "missing.json")
    assert http.get("/files/graph_json").status_code == 404
def test_locking_and_server_errors(client, monkeypatch):
    http, app, _ = client
    lock = app.extensions["tablelink"]["lock"]
    lock.acquire()
    try:
        assert http.post("/api/scan", json={}).status_code == 409
    finally:
        lock.release()
    def explode(**kwargs):
        raise RuntimeError("boom")
    monkeypatch.setattr(web_module, "run_pipeline", explode)
    response = http.post("/api/scan", json={})
    assert response.status_code == 500 and "boom" in response.get_json()["error"]
def test_invalid_config_reload(client):
    http, app, tmp_path = client
    path = Path(app.extensions["tablelink"]["manager"].path)
    path.write_text("web:\n  host: 8.8.8.8\n", encoding="utf-8")
    response = http.post("/api/config/reload")
    assert response.status_code == 400 and "回环" in response.get_json()["error"]
