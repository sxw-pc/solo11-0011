"""SQLite 数据源加载与原生外键元数据读取。"""
from pathlib import Path
import pandas as pd
from sqlalchemy import URL, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from ..exceptions import LoaderError
from .base_loader import BaseLoader
def _quote_identifier(name):
    return '"{0}"'.format(str(name).replace('"', '""'))
class SQLiteLoader(BaseLoader):
    """读取单个 SQLite 文件中的用户表及外键约束。"""
    source_type = "sqlite"
    def __init__(self, config, database_path, name_filter=None):
        super().__init__(config, name_filter=name_filter)
        self.database_path = Path(database_path)
    def _foreign_keys(self, inspector, table_name, primary_keys):
        grouped = {}
        for item in inspector.get_foreign_keys(table_name):
            key = item.get("name") or "fk_{0}_{1}".format(
                table_name, item.get("id", len(grouped))
            )
            grouped.setdefault(key, []).append(item)
        result = []
        for name, items in grouped.items():
            constrained = []
            referred = []
            for item in items:
                constrained.extend(item.get("constrained_columns") or [])
                columns = item.get("referred_columns") or primary_keys
                referred.extend(columns)
            referred_table = items[0].get("referred_table")
            if not constrained or not referred_table or not referred:
                continue
            result.append({
                "name": name,
                "columns": constrained,
                "referred_table": referred_table,
                "referred_columns": referred,
            })
        return result
    def _load_table(self, connection, inspector, table_name):
        frame = pd.read_sql_query(
            text("SELECT * FROM {0}".format(_quote_identifier(table_name))),
            connection,
        )
        pk_info = inspector.get_pk_constraint(table_name) or {}
        primary_keys = pk_info.get("constrained_columns") or []
        foreign_keys = self._foreign_keys(
            inspector, table_name, primary_keys
        )
        if not self.table_allowed(table_name):
            return None
        table = self.make_table(
            name=table_name,
            frame=frame,
            source_name=self.database_path.name,
            primary_keys=primary_keys,
            foreign_keys=foreign_keys,
            source_type="sqlite",
        )
        return table
    def load(self, dataset):
        if not self.database_path.is_file():
            dataset.add_error(self.database_path, "SQLite 文件不存在，已跳过")
            return dataset
        if self.database_path.stat().st_size and self.database_path.read_bytes()[:16] != b"SQLite format 3\x00":
            dataset.add_error(self.database_path, "SQLite 文件头校验失败，可能已损坏")
            return dataset
        url = URL.create("sqlite", database=str(self.database_path.resolve()))
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                inspector = inspect(connection)
                try:
                    names = inspector.get_table_names()
                except SQLAlchemyError as exc:
                    raise LoaderError(self.database_path, "无法读取表清单: {0}".format(exc))
                names = [name for name in sorted(names) if not name.lower().startswith("sqlite_")]
                if not names:
                    dataset.add_error(self.database_path, "数据库中没有可用表", kind="warning")
                for table_name in names:
                    try:
                        table = self._load_table(connection, inspector, table_name)
                        if table is not None:
                            dataset.add_table(table)
                        else:
                            dataset.add_error(
                                self.database_path,
                                "按配置过滤表 {0}".format(table_name),
                                kind="info",
                            )
                    except LoaderError as exc:
                        dataset.add_error(self.database_path, exc.message)
                    except (SQLAlchemyError, pd.errors.DatabaseError, ValueError) as exc:
                        dataset.add_error(
                            self.database_path,
                            "表 {0} 加载失败: {1}".format(table_name, exc),
                        )
        except LoaderError as exc:
            dataset.add_error(self.database_path, exc.message)
        except (SQLAlchemyError, OSError) as exc:
            dataset.add_error(self.database_path, "数据库打开失败: {0}".format(exc))
        finally:
            engine.dispose()
        return dataset
