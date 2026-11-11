"""单文件静态 HTML 关联图谱生成，内嵌本地 ECharts。"""
import json
import os
from jinja2 import Environment, FileSystemLoader, TemplateError
from markupsafe import Markup
from ..exceptions import ExportError
from .rule_exporter import write_text
PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(PACKAGE_ROOT)
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
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
def generate_html_graph(graph, config, output_path, diff=None):
    """输出自包含 HTML；所有 JS/CSS 均从本地 static 读入后内嵌。"""
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    try:
        template = environment.get_template("graph.html")
        title = "{0} · 关联图谱".format(config.get("project", {}).get("name", "表链测绘仪"))
        html = template.render(
            title=title,
            stats=graph.get("stats", {}),
            css=Markup(_read_asset("graph_style.css")),
            app_js=_safe_script(_read_asset("graph_app.js")),
            echarts_js=_safe_script(_read_asset("echarts.min.js")),
            graph_json=_safe_json(graph),
            diff_json=_safe_json(diff),
        )
    except (TemplateError, OSError) as exc:
        raise ExportError("HTML 图谱渲染失败: {0}".format(exc))
    return write_text(output_path, html)
