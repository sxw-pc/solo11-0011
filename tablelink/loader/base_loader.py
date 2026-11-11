"""加载器基类、表元数据模型与共用的类型推断逻辑。"""
import fnmatch
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import pandas as pd
def json_value(value):
    """把 pandas / numpy 标量转成可 JSON 化的 Python 值。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return value
    return str(value)
_DATE_RE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}(?:[ T].*)?$")
def infer_dtype(series):
    """推断稳定的业务类型，避免直接暴露 pandas 内部 dtype。"""
    clean = series.dropna()
    if len(clean) == 0:
        return "empty"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_integer_dtype(series):
        return "integer"
    if pd.api.types.is_float_dtype(series):
        return "number"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    samples = [str(item).strip() for item in clean.head(200).tolist() if str(item).strip()]
    if samples and all(item.lower() in ("true", "false") for item in samples):
        return "boolean"
    if samples and all(_DATE_RE.match(item) for item in samples):
        return "datetime"
    return "string"
def type_compatible(left, right, strict=True):
    """判断两个字段是否允许做值域比较。"""
    if "empty" in (left, right):
        return False
    if not strict:
        return True
    numeric = {"integer", "number"}
    if left in numeric and right in numeric:
        return True
    return left == right
def build_column_meta(series, name, top_n=10):
    non_null = int(series.notna().sum())
    total = int(len(series))
    counts = series.dropna().astype(str).value_counts().head(top_n)
    top_values = [{"value": key, "count": int(count)} for key, count in counts.items()]
    samples = list(dict.fromkeys(series.dropna().astype(str).head(top_n * 2).tolist()))
    cardinality = int(series.nunique(dropna=True))
    return {
        "name": str(name),
        "dtype": infer_dtype(series),
        "non_null_ratio": round(non_null / total, 4) if total else 0.0,
        "cardinality": cardinality,
        "unique_ratio": round(cardinality / non_null, 4) if non_null else 0.0,
        "top_values": top_values,
        "samples": samples[:top_n],
    }
@dataclass
class TableData:
    """一张已加载表的元数据与内存数据。"""
    name: str
    source_type: str
    source_name: str
    row_count: int
    columns: List[Dict[str, Any]]
    primary_keys: List[str] = field(default_factory=list)
    foreign_keys: List[Dict[str, Any]] = field(default_factory=list)
    frame: Optional[pd.DataFrame] = field(default=None, repr=False)
    def column(self, name):
        for item in self.columns:
            if item["name"] == name:
                return item
        return None
    def column_names(self):
        return [item["name"] for item in self.columns]
    def to_dict(self):
        return {
            "table": self.name,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "row_count": self.row_count,
            "primary_keys": list(self.primary_keys),
            "foreign_keys": [dict(item) for item in self.foreign_keys],
            "columns": [dict(item) for item in self.columns],
        }
@dataclass
class Dataset:
    """全部数据源合并后的目录，同时保留加载错误。"""
    tables: Dict[str, TableData] = field(default_factory=dict)
    errors: List[Dict[str, str]] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    def add_table(self, table):
        name = table.name
        if name in self.tables:
            base = "{0}__{1}".format(name, table.source_type)
            name = base
            index = 2
            while name in self.tables:
                name = "{0}_{1}".format(base, index)
                index += 1
            table.name = name
            self.errors.append({
                "source": table.source_name,
                "message": "表名重复，已重命名为 {0}".format(name),
                "kind": "warning",
            })
        self.tables[name] = table
        if table.source_name not in self.sources:
            self.sources.append(table.source_name)
        return name
    def add_error(self, source, message, kind="error"):
        self.errors.append({"source": str(source), "message": str(message), "kind": kind})
    def table_dicts(self):
        return [self.tables[name].to_dict() for name in sorted(self.tables)]
class BaseLoader:
    """CSV / SQLite 加载器共用配置过滤与元数据构造。"""
    source_type = "base"
    def __init__(self, config, name_filter=None):
        self.config = config
        sources = config.get("sources", {})
        self.include_tables = sources.get("include_tables", [])
        self.exclude_tables = sources.get("exclude_tables", [])
        self.exclude_fields = sources.get("exclude_fields", [])
        self.name_filter = name_filter
    @staticmethod
    def _matches(name, patterns):
        lowered = str(name).lower()
        return any(fnmatch.fnmatch(lowered, str(pattern).lower()) for pattern in patterns)
    def table_allowed(self, name):
        if self.include_tables and not self._matches(name, self.include_tables):
            return False
        if self.exclude_tables and self._matches(name, self.exclude_tables):
            return False
        if self.name_filter is not None and not self.name_filter(name):
            return False
        return True
    def fields_allowed(self, frame):
        if not self.exclude_fields:
            return frame
        kept = [col for col in frame.columns if not self._matches(col, self.exclude_fields)]
        return frame.loc[:, kept]
    def make_table(self, name, frame, source_name, primary_keys=None,
                   foreign_keys=None, source_type=None):
        frame = self.fields_allowed(frame)
        columns = [build_column_meta(frame[col], col) for col in frame.columns]
        return TableData(
            name=str(name),
            source_type=source_type or self.source_type,
            source_name=str(source_name),
            row_count=int(len(frame)),
            columns=columns,
            primary_keys=list(primary_keys or []),
            foreign_keys=list(foreign_keys or []),
            frame=frame,
        )
    def load(self, dataset):
        raise NotImplementedError
