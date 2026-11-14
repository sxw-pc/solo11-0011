"""CSV 目录加载器：编码识别、结构校验与元数据提取。"""
import csv
import io
import os
from pathlib import Path
import pandas as pd
from ..exceptions import LoaderError
from .base_loader import BaseLoader
class CSVDirectoryLoader(BaseLoader):
    """加载一个目录下的全部 .csv 文件，单个文件失败不阻断批次。"""
    source_type = "csv"
    def __init__(self, config, directory, name_filter=None):
        super().__init__(config, name_filter=name_filter)
        self.directory = Path(directory)
        self.encodings = config.get("sources", {}).get(
            "csv_encodings", ["utf-8-sig", "utf-8", "gbk"]
        )
    def _decode(self, path):
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise LoaderError(path, "无法读取文件: {0}".format(exc))
        if b"\x00" in raw:
            raise LoaderError(path, "文件包含 NUL 字节，疑似损坏或非文本文件")
        tried = []
        for encoding in self.encodings:
            try:
                return raw.decode(encoding), encoding
            except (UnicodeDecodeError, LookupError):
                tried.append(encoding)
        raise LoaderError(path, "编码识别失败，已尝试 {0}".format(", ".join(tried)))
    @staticmethod
    def _validate_rows(text, path):
        try:
            reader = csv.reader(io.StringIO(text))
            rows = [row for row in reader if any(cell.strip() for cell in row)]
        except csv.Error as exc:
            raise LoaderError(path, "CSV 解析失败: {0}".format(exc))
        if not rows:
            raise LoaderError(path, "空文件，没有表头")
        header = [cell.strip() for cell in rows[0]]
        if not any(header):
            raise LoaderError(path, "表头为空")
        if any(not cell for cell in header):
            raise LoaderError(path, "表头存在空字段名")
        if len(set(header)) != len(header):
            raise LoaderError(path, "表头存在重复字段名")
        expected = len(header)
        for index, row in enumerate(rows[1:], start=2):
            if len(row) != expected:
                raise LoaderError(path, "第 {0} 行字段数为 {1}，期望 {2}，文件已跳过".format(
                    index, len(row), expected))
        return header
    def _load_file(self, path):
        text, encoding = self._decode(path)
        self._validate_rows(text, path)
        try:
            frame = pd.read_csv(io.StringIO(text))
        except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
            raise LoaderError(path, "pandas 读取失败: {0}".format(exc))
        frame.columns = [str(col).strip() for col in frame.columns]
        table = self.make_table(name=path.stem, frame=frame,
                                source_name=path.name, source_type="csv")
        table.encoding = encoding
        return table
    def load(self, dataset):
        if not self.directory.is_dir():
            dataset.add_error(self.directory, "CSV 目录不存在，已跳过")
            return dataset
        files = sorted(
            (item for item in self.directory.rglob("*")
             if item.is_file() and item.suffix.lower() == ".csv"),
            key=lambda item: str(item).lower())
        if not files:
            dataset.add_error(self.directory, "CSV 目录下没有 .csv 文件", kind="warning")
        for path in files:
            if not self.table_allowed(path.stem):
                dataset.add_error(path, "按配置过滤表 {0}".format(path.stem), kind="info")
                continue
            try:
                dataset.add_table(self._load_file(path))
            except LoaderError as exc:
                dataset.add_error(path, exc.message)
            except Exception as exc:  # 单文件兜底，保证批次继续
                dataset.add_error(path, "未预期加载错误: {0}".format(exc))
        return dataset
def discover_csv_files(directory):
    """返回目录下排序后的 CSV 文件，供测试与调用方预览。"""
    root = Path(directory)
    if not root.is_dir():
        return []
    return sorted(
        str(path) for path in root.iterdir()
        if path.is_file() and os.path.splitext(path.name)[1].lower() == ".csv"
    )
