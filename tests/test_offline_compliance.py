"""离线、安全与代码规模合规检查。"""
import ast, re
from pathlib import Path
from tablelink.config import DEFAULT_CONFIG
ROOT = Path(__file__).resolve().parents[1]
SKIP = {"output", ".git", "__pycache__", ".pytest_cache", ".coverage", "htmlcov", "wheelhouse"}
TEXT_SUFFIXES = {".py", ".yaml", ".yml", ".md", ".txt", ".js", ".css", ".html", ".csv", ".ini"}
VENDOR = {ROOT / "static" / "echarts.min.js", ROOT / "static" / "ECHARTS-LICENSE.txt"}
def _delivered():
    files = []
    for path in ROOT.rglob("*"):
        if path.is_file() and not any(part in SKIP for part in path.parts) \
                and path.suffix.lower() in TEXT_SUFFIXES:
            files.append(path)
    return files
def test_all_text_files_utf8_and_line_budget():
    files = _delivered()
    total = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "\x00" not in text, path
        total += len(text.splitlines())
    assert 2500 <= total <= 5400, "项目文本总行数越界: {0}".format(total)
    for path in files:
        if path.suffix == ".py":
            assert len(path.read_text(encoding="utf-8").splitlines()) <= 300, path
def test_no_external_runtime_urls_or_network_imports():
    product = list((ROOT / "tablelink").rglob("*.py")) + [ROOT / "run_demo.py", ROOT / "run_web.py"]
    for path in product:
        text = path.read_text(encoding="utf-8")
        urls = re.findall(r"https?://[^\s\"']+", text)
        assert all(url.startswith(("http://{0}", "http://127.0.0.1", "http://localhost"))
                   for url in urls), path
        tree = ast.parse(text)
        imports = {node.names[0].name.split(".")[0] for node in ast.walk(tree)
                   if isinstance(node, (ast.Import, ast.ImportFrom)) and node.names}
        assert not imports & {"requests", "urllib", "http", "httpx", "socket", "aiohttp"}, path
    for path in _delivered():
        if path in VENDOR or path.suffix not in {".html", ".js", ".css"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r'(src|href)=["\']https?://', text), path
        assert not re.search(r'@import\s+url\(["\']?https?://', text), path
def test_loopback_only_and_no_secrets():
    assert DEFAULT_CONFIG["web"]["host"] == "127.0.0.1"
    assert DEFAULT_CONFIG["web"]["host"] in {"127.0.0.1", "localhost", "::1"}
    pattern = re.compile(r"(AKIA[0-9A-Z]{16}|BEGIN (RSA |EC )?PRIVATE KEY|sk-[A-Za-z0-9]{20,})")
    for path in _delivered():
        if path in VENDOR or path.name == "test_offline_compliance.py":
            continue
        assert not pattern.search(path.read_text(encoding="utf-8")), path
