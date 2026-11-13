"""本地 Flask 服务：仅绑定回环地址的可视化操作页面。"""
import os
import threading
from pathlib import Path
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.exceptions import HTTPException
from ..config import ConfigManager
from ..exceptions import TableLinkError
from ..pipeline import run_pipeline
PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
ALLOWED_DOWNLOADS = {"rules_json", "rules_yaml", "report_md", "graph_html", "graph_json"}
LOOPBACK_ADDRESSES = {"127.0.0.1", "::1", "localhost"}
def create_app(config_path=None, base_dir=None):
    """应用工厂；测试与 run_web 共用。"""
    config_path = config_path or os.path.join(PROJECT_ROOT, "config.yaml")
    manager = ConfigManager(
        config_path, base_dir=base_dir or PROJECT_ROOT, auto_reload=True
    )
    manager.load()
    app = Flask(
        __name__,
        template_folder=os.path.join(os.path.dirname(__file__), "templates"),
        static_folder=STATIC_DIR,
        static_url_path="/static",
    )
    app.json.ensure_ascii = False
    app.extensions["tablelink"] = {
        "manager": manager,
        "result": None,
        "lock": threading.Lock(),
    }
    @app.before_request
    def restrict_to_loopback():
        if request.remote_addr not in LOOPBACK_ADDRESSES:
            return jsonify({"ok": False, "error": "仅允许本机回环地址访问"}), 403
        return None
    @app.errorhandler(TableLinkError)
    def handle_tablelink_error(error):
        return jsonify({"ok": False, "error": str(error)}), 400
    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return jsonify({"ok": False, "error": error.description}), error.code
    @app.errorhandler(Exception)
    def handle_error(error):
        app.logger.exception("Web 请求失败")
        return jsonify({"ok": False, "error": "服务端错误: {0}".format(error)}), 500
    @app.get("/")
    def index():
        state = app.extensions["tablelink"]
        config = manager.load()
        return render_template(
            "index.html",
            config=config,
            result=state["result"].summary() if state["result"] else None,
        )
    @app.post("/api/scan")
    def scan():
        state = app.extensions["tablelink"]
        payload = request.get_json(silent=True) or {}
        baseline = payload.get("baseline") or None
        if not state["lock"].acquire(blocking=False):
            return jsonify({"ok": False, "error": "已有扫描任务在执行"}), 409
        try:
            result = run_pipeline(
                manager=state["manager"], baseline_path=baseline
            )
            state["result"] = result
            return jsonify({"ok": True, "summary": result.summary()})
        finally:
            state["lock"].release()
    @app.get("/api/graph")
    def graph():
        state = app.extensions["tablelink"]
        if state["result"] is None:
            return jsonify({"ok": False, "error": "尚未执行扫描"}), 404
        return jsonify({"ok": True, "graph": state["result"].graph})
    @app.get("/api/config")
    def config_view():
        return jsonify({"ok": True, "config": state_config()})
    def state_config():
        return app.extensions["tablelink"]["manager"].load()
    @app.post("/api/config/reload")
    def reload_config():
        try:
            config = app.extensions["tablelink"]["manager"].load(force=True)
        except TableLinkError as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        return jsonify({"ok": True, "message": "配置已重新加载", "config": config})
    @app.get("/api/report")
    def report():
        state = app.extensions["tablelink"]
        if state["result"] is None:
            return jsonify({"ok": False, "error": "尚未执行扫描"}), 404
        path = state["result"].outputs["report_md"]
        with open(path, "r", encoding="utf-8") as handle:
            return jsonify({"ok": True, "markdown": handle.read()})
    @app.get("/files/<key>")
    def download(key):
        state = app.extensions["tablelink"]
        if key not in ALLOWED_DOWNLOADS:
            return jsonify({"ok": False, "error": "不允许的输出文件"}), 404
        if state["result"] is None:
            return jsonify({"ok": False, "error": "尚未执行扫描"}), 404
        path = state["result"].outputs.get(key)
        if not path or not os.path.isfile(path):
            return jsonify({"ok": False, "error": "输出文件不存在"}), 404
        return send_file(path, as_attachment=False)
    return app
