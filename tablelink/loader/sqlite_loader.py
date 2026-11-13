"""SQLite 数据源加载与原生外键元数据读取。"""
import re
from pathlib import Path
import pandas as pd
from sqlalchemy import URL, create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from ..exceptions import LoaderError
from .base_loader import BaseLoader
from .fk_metadata import DEFAULT_SCHEMA, specs_from_pragma, specs_from_reflection
_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
def _quote_identifier(name):
    return '"{0}"'.format(str(name).replace('"', '""'))
class SQLiteLoader(BaseLoader):
    """读取单个 SQLite 文件中的用户表及外键约束，可附加非默认 schema。"""
    source_type = "sqlite"
    def __init__(self, config, database_path, name_filter=None, attach=None):
        super().__init__(config, name_filter=name_filter)
        self.database_path = Path(database_path)
        self.attach = dict(attach or {})
    def _attach_schemas(self, connection, dataset):
        """按 attach={schema: path} 附加数据库；失败降级为提示，不中止扫描。"""
        attached = []
        for schema in sorted(self.attach):
            path = Path(self.attach[schema])
            if not _SCHEMA_RE.match(schema) or schema.lower() in (DEFAULT_SCHEMA, "temp"):
                dataset.add_error(self.database_path, "附加 schema 名非法: {0}".format(schema), kind="warning")
                continue
            if not path.is_file():
                dataset.add_error(path, "附加 SQLite 文件不存在，已跳过 schema {0}".format(schema), kind="warning")
                continue
            try:
                connection.exec_driver_sql('ATTACH DATABASE "{0}" AS "{1}"'.format(
                    str(path.resolve()).replace('"', '""'), schema))
                attached.append(schema)
            except SQLAlchemyError as exc:
                dataset.add_error(path, "附加 schema {0} 失败: {1}".format(schema, exc), kind="warning")
        return attached
    def _foreign_keys(self, inspector, table_name, primary_keys):
        return specs_from_reflection(
            inspector.get_foreign_keys(table_name), table_name,
            source_schema=DEFAULT_SCHEMA, primary_keys=primary_keys)
    def _safe_constraints(self, dataset, label, reader):
        """约束元数据读取失败时降级为空集合，表数据照常参与扫描。"""
        try:
            return reader()
        except (SQLAlchemyError, ValueError, KeyError) as exc:
            dataset.add_error(
                self.database_path,
                "表 {0} 约束元数据读取失败: {1}".format(label, exc),
                kind="warning",
            )
            return []
    def _pragma_pk(self, connection, schema, table_name):
        rows = connection.exec_driver_sql('PRAGMA "{0}".table_info("{1}")'.format(
            schema, str(table_name).replace('"', '""'))).fetchall()
        keyed = sorted((int(row[5]), row[1]) for row in rows if row[5])
        return [name for _position, name in keyed]
    def _pragma_foreign_keys(self, connection, schema, table_name):
        rows = connection.exec_driver_sql('PRAGMA "{0}".foreign_key_list("{1}")'.format(
            schema, str(table_name).replace('"', '""'))).fetchall()
        need = sorted({row[2] for row in rows if row[4] is None})
        referred_pk = {name: self._pragma_pk(connection, schema, name) for name in need}
        return specs_from_pragma(rows, table_name, schema, referred_pk=referred_pk)
    def _load_table(self, connection, inspector, table_name, dataset):
        frame = pd.read_sql_query(
            text("SELECT * FROM {0}".format(_quote_identifier(table_name))),
            connection,
        )
        primary_keys = self._safe_constraints(dataset, table_name, lambda: list(
            (inspector.get_pk_constraint(table_name) or {}).get("constrained_columns") or []))
        foreign_keys = self._safe_constraints(dataset, table_name, lambda: self._foreign_keys(
            inspector, table_name, primary_keys))
        if not self.table_allowed(table_name):
            return None
        return self.make_table(
            name=table_name,
            frame=frame,
            source_name=self.database_path.name,
            primary_keys=primary_keys,
            foreign_keys=foreign_keys,
            source_type="sqlite",
        )
    def _load_attached_table(self, connection, schema, table_name, dataset):
        qualified = "{0}.{1}".format(schema, table_name)
        frame = pd.read_sql_query(
            text("SELECT * FROM {0}.{1}".format(
                _quote_identifier(schema), _quote_identifier(table_name))),
            connection,
        )
        primary_keys = self._safe_constraints(
            dataset, qualified, lambda: self._pragma_pk(connection, schema, table_name))
        foreign_keys = self._safe_constraints(
            dataset, qualified, lambda: self._pragma_foreign_keys(connection, schema, table_name))
        if not self.table_allowed(qualified):
            return None
        return self.make_table(
            name=qualified,
            frame=frame,
            source_name=self.database_path.name,
            primary_keys=primary_keys,
            foreign_keys=foreign_keys,
            source_type="sqlite",
        )
    def _load_attached_schema(self, connection, dataset, schema):
        try:
            rows = connection.exec_driver_sql(
                "SELECT name FROM \"{0}\".sqlite_master WHERE type='table' ORDER BY name".format(schema)
            ).fetchall()
        except SQLAlchemyError as exc:
            dataset.add_error(
                self.database_path, "读取附加 schema {0} 的表清单失败: {1}".format(schema, exc),
                kind="warning")
            return 0
        found = 0
        for (table_name,) in rows:
            if table_name.lower().startswith("sqlite_"):
                continue
            qualified = "{0}.{1}".format(schema, table_name)
            try:
                table = self._load_attached_table(connection, schema, table_name, dataset)
                if table is not None:
                    dataset.add_table(table)
                    found += len(table.foreign_keys)
                else:
                    dataset.add_error(self.database_path, "按配置过滤表 {0}".format(qualified), kind="info")
            except (SQLAlchemyError, pd.errors.DatabaseError, ValueError) as exc:
                dataset.add_error(self.database_path, "表 {0} 加载失败: {1}".format(qualified, exc))
        return found
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
                attached = self._attach_schemas(connection, dataset)
                inspector = inspect(connection)
                try:
                    names = inspector.get_table_names()
                except SQLAlchemyError as exc:
                    raise LoaderError(self.database_path, "无法读取表清单: {0}".format(exc))
                names = [name for name in sorted(names) if not name.lower().startswith("sqlite_")]
                if not names:
                    dataset.add_error(self.database_path, "数据库中没有可用表", kind="warning")
                fk_count = 0
                for table_name in names:
                    try:
                        table = self._load_table(connection, inspector, table_name, dataset)
                        if table is not None:
                            dataset.add_table(table)
                            fk_count += len(table.foreign_keys)
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
                for schema in attached:
                    fk_count += self._load_attached_schema(connection, dataset, schema)
                if names and not fk_count:
                    dataset.add_error(
                        self.database_path,
                        "未读取到外键元数据，原生外键检测将无输出",
                        kind="info",
                    )
        except LoaderError as exc:
            dataset.add_error(self.database_path, exc.message)
        except (SQLAlchemyError, OSError) as exc:
            dataset.add_error(self.database_path, "数据库打开失败: {0}".format(exc))
        finally:
            engine.dispose()
        return dataset
