"""阶段内存产物的检查点序列化与输入指纹构造。

检查点只落在运行临时区，复用前由 RunManager 校验内容摘要；
DataFrame 不进检查点：复用时由加载器按相同源路径重新取数（源文件
摘要已在输入指纹中校验），再用检查点里的表元数据补齐派生字段。
"""
import hashlib
import json
import os
from .loader import load_dataset
from .loader.base_loader import Dataset, TableData
from .runstate import fingerprint_paths, sha256_file
def _jsonable(value):
    """把 DataFrame 等不可直接 JSON 化的对象转成纯 JSON 类型。"""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
def write_checkpoint(path, payload):
    text = json.dumps(_jsonable(payload), ensure_ascii=False,
                      indent=2, sort_keys=False) + "\n"
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temporary, path)
    return path
def read_checkpoint(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)
def save_dataset(run, stage, dataset):
    """加载阶段检查点：表元数据、加载错误与来源清单（不含 DataFrame）。"""
    path = run.stage_path(stage, "dataset.json")
    write_checkpoint(path, {
        "tables": dataset.table_dicts(),
        "errors": list(dataset.errors),
        "sources": list(dataset.sources),
    })
    return {"dataset": path}
def restore_dataset(run, stage, config, base_dir):
    """复用加载阶段：源文件经指纹校验未变，重新取数并合并检查点元数据。"""
    payload = read_checkpoint(run.stage_file(stage, "dataset"))
    fresh = load_dataset(config, base_dir)
    meta = {item["table"]: item for item in payload["tables"]}
    dataset = Dataset()
    for name, table in sorted(fresh.tables.items()):
        saved = meta.get(name)
        if saved is not None:
            table.primary_keys = list(saved.get("primary_keys", []))
            table.foreign_keys = _jsonable(saved.get("foreign_keys", []))
            table.columns = _jsonable(saved.get("columns", table.columns))
        dataset.tables[name] = table
        if table.source_name not in dataset.sources:
            dataset.sources.append(table.source_name)
    dataset.errors = list(payload.get("errors", fresh.errors))
    dataset.sources = list(payload.get("sources", dataset.sources))
    return dataset
def save_associations(run, stage, associations):
    path = run.stage_path(stage, "associations.json")
    write_checkpoint(path, {"associations": _jsonable(associations)})
    return {"associations": path}
def load_associations_checkpoint(run, stage):
    payload = read_checkpoint(run.stage_file(stage, "associations"))
    return payload["associations"]
def save_diff(run, stage, diff, baseline_path):
    path = run.stage_path(stage, "diff.json")
    write_checkpoint(path, {
        "baseline_path": os.path.abspath(baseline_path) if baseline_path else None,
        "diff": _jsonable(diff),
    })
    return {"diff": path}
def load_diff_checkpoint(run, stage):
    payload = read_checkpoint(run.stage_file(stage, "diff"))
    return payload["diff"], payload.get("baseline_path")
def source_input_paths(config, manager):
    """解析配置声明的全部源数据路径，用于加载阶段输入指纹。"""
    paths = []
    sources = config.get("sources", {})
    for directory in sources.get("csv_dirs", []):
        resolved = manager.resolve(directory)
        if os.path.isdir(resolved):
            for root, _, files in os.walk(resolved):
                for name in sorted(files):
                    if name.lower().endswith(".csv"):
                        paths.append(os.path.join(root, name))
        else:
            paths.append(resolved)
    for database in sources.get("sqlite_files", []):
        paths.append(manager.resolve(database))
    custom = config.get("explicit", {}).get("custom_rules_path")
    if custom:
        paths.append(manager.resolve(custom))
    return paths
def make_input_fingerprint(parts):
    """组合多类输入（文件路径、配置段、上游产物摘要）为单一指纹。"""
    digest_parts = []
    for label, value in parts:
        if isinstance(value, (list, tuple, set)):
            digest_parts.append((label, fingerprint_paths(value)))
        elif value and os.sep in str(value) and os.path.isfile(str(value)):
            digest_parts.append((label, sha256_file(value)))
        else:
            digest_parts.append((label, _jsonable(value)))
    payload = json.dumps(digest_parts, ensure_ascii=False,
                         sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
