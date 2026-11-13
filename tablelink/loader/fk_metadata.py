"""结构化外键描述：SQLite 加载器与显式检测器之间的数据契约。

加载器把每条外键归一化为字典：在旧版四键（name/columns/referred_table/
referred_columns）之外补充 referred_schema、source_schema、referred_key、
on_delete、on_update、deferrable、initially_deferred、match、composite。
检测器只消费该字典：单列外键走旧路径逐列展开，复合外键作为一条整体
记录输出，on_delete/on_update 通过 action_confidence 影响置信度取整。
契约落在加载器侧，overlap/FD 检测器不读取外键元数据，互不影响。
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
DEFAULT_SCHEMA = "main"
NULLIFYING_ACTIONS = frozenset({"SET NULL", "SET DEFAULT"})
ACTION_FACTORS = {
    "NO ACTION": Decimal("1"),
    "RESTRICT": Decimal("0.995"),
    "CASCADE": Decimal("0.985"),
    "SET DEFAULT": Decimal("0.965"),
    "SET NULL": Decimal("0.955"),
}
def normalize_action(value):
    """把 on_delete/on_update 归一化为已知动作，未知动作按 NO ACTION。"""
    action = str(value or "").strip().upper()
    return action if action in ACTION_FACTORS else "NO ACTION"
def action_confidence(on_delete, on_update):
    """复合外键置信度：动作因子相乘；含置空动作时向下取整，否则四舍五入。"""
    delete, update = normalize_action(on_delete), normalize_action(on_update)
    raw = ACTION_FACTORS[delete] * ACTION_FACTORS[update]
    mode = ROUND_FLOOR if NULLIFYING_ACTIONS & {delete, update} else ROUND_HALF_UP
    return float(raw.quantize(Decimal("0.0001"), rounding=mode))
def join_fields(fields):
    """复合键端点的稳定字符串形态，列序与约束声明一致。"""
    return "+".join(str(item) for item in fields)
def referred_key(spec):
    """外键目标在数据集中的查找键；非默认 schema 需要限定名。"""
    schema = spec.get("referred_schema")
    table = str(spec.get("referred_table") or "")
    return "{0}.{1}".format(schema, table) if schema and schema != DEFAULT_SCHEMA else table
def _behavior(options):
    options = options or {}
    initially = str(options.get("initially") or "").strip().upper()
    deferrable = options.get("deferrable")
    return {
        "on_delete": normalize_action(options.get("ondelete")),
        "on_update": normalize_action(options.get("onupdate")),
        "deferrable": bool(deferrable) if deferrable is not None else None,
        "initially_deferred": (initially == "DEFERRED") if initially else None,
        "match": None,
    }
def _pragma_behavior(entry):
    return {
        "on_delete": normalize_action(entry[5]),
        "on_update": normalize_action(entry[4]),
        "deferrable": None,
        "initially_deferred": None,
        "match": str(entry[6]) if entry[6] else None,
    }
def _spec(name, columns, referred_table, referred_columns, source_schema,
          referred_schema=None, behavior=None):
    spec = {
        "name": str(name),
        "columns": [str(item) for item in columns],
        "referred_table": str(referred_table),
        "referred_columns": [str(item) for item in referred_columns],
        "referred_schema": referred_schema or source_schema,
        "source_schema": source_schema,
        "composite": len(columns) > 1,
    }
    spec.update(behavior or _behavior(None))
    spec["referred_key"] = referred_key(spec)
    return spec
def specs_from_reflection(items, table_name, source_schema=None, primary_keys=None):
    """归一化 SQLAlchemy 反射结果；无名约束的占位名与旧版保持一致。"""
    specs, seen = [], set()
    for item in items or []:
        name = item.get("name")
        if not name:
            name = "fk_{0}_{1}".format(table_name, len(seen))
        seen.add(name)
        constrained = item.get("constrained_columns") or []
        referred = item.get("referred_columns") or list(primary_keys or [])
        referred_table = item.get("referred_table")
        if not constrained or not referred_table or not referred:
            continue
        specs.append(_spec(name, constrained, referred_table, referred, source_schema,
                           referred_schema=item.get("referred_schema"),
                           behavior=_behavior(item.get("options"))))
    return specs
def specs_from_pragma(rows, table_name, source_schema, referred_pk=None):
    """归一化 PRAGMA foreign_key_list 行：按 id 分组、按 seq 还原列序。"""
    grouped = {}
    for row in rows or []:
        fid, seq, ref_table, from_col, to_col, on_update, on_delete, match = list(row)[:8]
        grouped.setdefault(int(fid), []).append(
            (int(seq), ref_table, from_col, to_col, on_update, on_delete, match))
    specs = []
    for fid in sorted(grouped):
        entries = sorted(grouped[fid], key=lambda item: item[0])
        referred_table = entries[0][1]
        fallback = (referred_pk or {}).get(referred_table) or []
        columns, referred = [], []
        for seq, _table, from_col, to_col, _update, _delete, _match in entries:
            target = to_col if to_col is not None else \
                (fallback[seq] if seq < len(fallback) else None)
            if from_col is None or target is None:
                referred = None
                break
            columns.append(str(from_col))
            referred.append(str(target))
        if not columns or referred is None:
            continue
        specs.append(_spec("fk_{0}_{1}".format(table_name, fid), columns,
                           referred_table, referred, source_schema,
                           behavior=_pragma_behavior(entries[0])))
    return specs
