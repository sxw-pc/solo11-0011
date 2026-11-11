"""数据源加载入口。"""
import os
from .base_loader import (
    BaseLoader,
    Dataset,
    TableData,
    build_column_meta,
    infer_dtype,
    json_value,
    type_compatible,
)
from .csv_loader import CSVDirectoryLoader, discover_csv_files
from .sqlite_loader import SQLiteLoader
__all__ = [
    "BaseLoader", "Dataset", "TableData", "CSVDirectoryLoader",
    "SQLiteLoader", "load_dataset", "discover_csv_files",
    "build_column_meta", "infer_dtype", "json_value", "type_compatible",
]
def _resolve(base_dir, value):
    if os.path.isabs(value):
        return value
    return os.path.abspath(os.path.join(base_dir, value))
def load_dataset(config, base_dir=None, name_filter=None):
    """按配置批量加载 CSV 与 SQLite，汇总失败项后返回 Dataset。"""
    base_dir = os.path.abspath(base_dir or os.getcwd())
    dataset = Dataset()
    sources = config.get("sources", {})
    for directory in sources.get("csv_dirs", []):
        path = _resolve(base_dir, directory)
        CSVDirectoryLoader(config, path, name_filter=name_filter).load(dataset)
    for database in sources.get("sqlite_files", []):
        path = _resolve(base_dir, database)
        SQLiteLoader(config, path, name_filter=name_filter).load(dataset)
    if not dataset.tables and not dataset.errors:
        dataset.add_error("<sources>", "没有加载到任何数据表", kind="warning")
    return dataset
