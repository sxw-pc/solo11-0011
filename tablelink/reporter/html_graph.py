"""单文件静态 HTML 关联图谱生成，内嵌本地 ECharts。"""
import json
import os
from jinja2 import Environment, FileSystemLoader, TemplateError
from markupsafe import Markup
from ..exceptions import ExportError
from . import graph_shards
from .rule_exporter import write_text

PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(PACKAGE_ROOT)
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
CSP_SELF = ("default-src 'none'; img-src data:; style-src 'unsafe-inline'; "
            "script-src 'unsafe-inline' 'unsafe-eval'; font-src data:; "
            "connect-src 'none'; base-uri 'none'; form-action 'none'")
CSP_SHARDED = CSP_SELF.replace("connect-src 'none'", "connect-src 'self'")
def _read_asset(name):
    path = os.path.join(STATIC_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        raise ExportError("缺少本地静态资源 {0}: {1}".format(path, exc))
def _safe_json(value):
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    text = text.replace("</", "<\\/")
    text = text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return Markup(text)
def _safe_script(text):
    return Markup(text.replace("</script", "<\\/script"))
def _environment():
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
def _sharded_config(config):
    return bool((config.get("output") or {}).get("shard_edges"))
def _render(environment, config, context):
    try:
        template = environment.get_template("graph.html")
        title = "{0} · 关联图谱".format(config.get("project", {}).get("name", "表链测绘仪"))
        return template.render(title=title, **_context(context))
    except (TemplateError, OSError) as exc:
        raise ExportError("HTML 图谱渲染失败: {0}".format(exc))
def _context(context):
    values = dict(context)
    values.update({
        "csp": CSP_SHARDED if values.get("sharded") else CSP_SELF,
        "css": Markup(_read_asset("graph_style.css")),
        "app_js": _safe_script(values.get("app_js_src") or _read_asset("graph_app.js")),
        "echarts_js": _safe_script(_read_asset("echarts.min.js")),
    })
    return values
def generate_html_graph(graph, config, output_path, diff=None):
    """输出自包含 HTML；开启 output.shard_edges 时额外写确定性伴生分片。"""
    environment = _environment()
    sharded = _sharded_config(config)
    if sharded:
        manifest = graph_shards.build_manifest(graph, output_path)
        graph_shards.write_shards(graph, output_path, manifest)
        meta = graph_shards.meta_payload(graph, manifest, diff)
        html = _render(environment, config, {
            "sharded": True,
            "stats": graph.get("stats", {}),
            "subtitle_note": "骨架 + 同目录分片数据",
            "footer_note": "边数据按关系家族拆分在同目录伴生 JSON 中按需加载（file:// 直开受限，建议本地 Web 控制台）。",
            "graph_json": _safe_json(meta),
            "diff_json": _safe_json(graph_shards.diff_summary(diff)),
            "app_js_src": _read_asset("graph_shard_app.js"),
        })
    else:
        html = _render(environment, config, {
            "sharded": False,
            "stats": graph.get("stats", {}),
            "subtitle_note": "单文件可直接打开",
            "footer_note": "无 CDN、无外部请求。",
            "graph_json": _safe_json(graph),
            "diff_json": _safe_json(diff),
        })
    return write_text(output_path, html)
