"""跨来源值规范化器：按字段名与值形态推断规范化链，供值域重叠救援路径使用。

规范化只作用于值的副本，不改动原始数据；无法解析的值返回 None，由调用方
按字段覆盖率决定降级。每条链的信任度（trust）来自配置，越激进的规范化
折扣越大，用于把规范化后的 Jaccard 折算为有效 Jaccard，在召回提升与
误报风险之间给出可解释的平衡，而不是一律套用最强规范化。
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from .common import normalize_value
_ASCII_ALNUM_RE = re.compile(r"[0-9A-Za-z]")
_NON_ALNUM_RE = re.compile(r"[^0-9A-Za-z]+")
_NUM_VALUE_RE = re.compile(r"^[¥$€£]?\s*([+-]?[\d,]+(?:\.\d+)?)\s*(万|亿)?$")
_DATE_RES = (
    re.compile(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})([ T].*)?$"),
    re.compile(r"^(\d{4})\.(\d{1,2})\.(\d{1,2})([ T].*)?$"),
    re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?(\s.*)?$"),
)
_NAME_HINTS = {
    "strip_delimiters": re.compile(
        r"phone|mobile|tel|contact|fax|code|number|_no$|sn$|sku|手机|电话|编号|编码", re.I),
    "numeric_unit": re.compile(r"amount|price|cost|fee|money|balance|total|金额|费用|价格", re.I),
    "date_unify": re.compile(r"date|day|time|_at$|日期|时间", re.I),
}
def _ratio(values, pred):
    if not values:
        return 0.0
    return sum(1 for value in values if pred(value)) / len(values)
def _match_date(value):
    for pattern in _DATE_RES:
        match = pattern.match(value)
        if not match:
            continue
        try:
            date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            return None
        return match
    return None
def _detect_case_fold(name, values):
    return _ratio(values, lambda v: any(ch.isalpha() for ch in v)) >= 0.6 and \
        any(v != v.lower() for v in values)
def _detect_strip_delimiters(name, values):
    hint = bool(_NAME_HINTS["strip_delimiters"].search(name or ""))
    shape = lambda v: bool(_ASCII_ALNUM_RE.search(v)) and bool(_NON_ALNUM_RE.search(v))
    if _ratio(values, shape) < (0.4 if hint else 0.6):
        return False
    semantic = lambda v: bool(_NUM_VALUE_RE.match(v)) or _match_date(v) is not None
    return _ratio(values, semantic) < 0.6
def _detect_numeric_unit(name, values):
    hint = bool(_NAME_HINTS["numeric_unit"].search(name or ""))
    if _ratio(values, lambda v: bool(_NUM_VALUE_RE.match(v))) < (0.4 if hint else 0.6):
        return False
    return any(re.search(r"[¥$€£,万亿]", v) for v in values)
def _detect_date_unify(name, values):
    hint = bool(_NAME_HINTS["date_unify"].search(name or ""))
    return _ratio(values, lambda v: _match_date(v) is not None) >= (0.4 if hint else 0.6)
def _norm_case_fold(value):
    return value.lower()
def _norm_strip_delimiters(value):
    text = _NON_ALNUM_RE.sub("", value)
    if not text:
        return None
    if text.isdigit():
        for prefix in ("0086", "86"):
            if text.startswith(prefix) and len(text) - len(prefix) == 11:
                return text[len(prefix):]
    return text
def _norm_numeric_unit(value):
    match = _NUM_VALUE_RE.match(value)
    if not match:
        return None
    try:
        number = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    unit = match.group(2)
    if unit == "万":
        number *= 10000
    elif unit == "亿":
        number *= 100000000
    return format(number.normalize(), "f")
def _norm_date_unify(value):
    match = _match_date(value)
    if not match:
        return None
    return "{0:04d}-{1:02d}-{2:02d}".format(
        int(match.group(1)), int(match.group(2)), int(match.group(3)))
NORMALIZERS = {
    "case_fold": (_detect_case_fold, _norm_case_fold),
    "strip_delimiters": (_detect_strip_delimiters, _norm_strip_delimiters),
    "numeric_unit": (_detect_numeric_unit, _norm_numeric_unit),
    "date_unify": (_detect_date_unify, _norm_date_unify),
}
CHAINS = (
    ("case_fold", ("case_fold",)),
    ("strip_delimiters", ("strip_delimiters",)),
    ("case_fold+strip_delimiters", ("case_fold", "strip_delimiters")),
    ("numeric_unit", ("numeric_unit",)),
    ("date_unify", ("date_unify",)),
)
_CHAIN_MAP = dict(CHAINS)
def detect_chains(field_name, values, norm_config):
    """按字段名与值形态推断可用链；只返回配置启用的链，顺序固定可复现。"""
    normalizers = norm_config["normalizers"]
    result = []
    for chain_id, members in CHAINS:
        if all(normalizers[key]["enabled"] for key in members) and \
                all(NORMALIZERS[key][0](field_name, values) for key in members):
            result.append(chain_id)
    return result
def apply_chain(chain_id, value):
    """对单个已规范化字符串依次应用链中各规范化器；失败返回 None。"""
    for key in _CHAIN_MAP[chain_id]:
        value = NORMALIZERS[key][1](value)
        if value is None:
            return None
    return value
def chain_trust(chain_id, norm_config):
    """链信任度为各成员信任度之积：链越长、越激进，折算越低。"""
    trust = 1.0
    for key in _CHAIN_MAP[chain_id]:
        trust *= float(norm_config["normalizers"][key]["trust"])
    return trust
class NormalizationCache:
    """按 (表, 字段, 链) 缓存规范化值集，同一字段在多对候选间复用。"""
    def __init__(self, norm_config, diagnostics=None):
        self._config = norm_config
        self._diagnostics = diagnostics if diagnostics is not None else {}
        self._entries = {}
    @property
    def size(self):
        return len(self._entries)
    def get(self, table, field, chain_id):
        key = (table.name, field, chain_id)
        if key not in self._entries:
            self._entries[key] = self._build(table, field, chain_id)
        return self._entries[key]
    def _build(self, table, field, chain_id):
        mapping = {}
        total = 0
        ok = 0
        for value in table.frame[field].dropna().tolist():
            base = normalize_value(value)
            if base is None:
                continue
            total += 1
            try:
                key = apply_chain(chain_id, base)
            except Exception:
                key = None
            if key is None:
                continue
            ok += 1
            if key not in mapping:
                mapping[key] = value
        coverage = ok / total if total else 0.0
        if total == 0 or coverage < float(self._config["min_side_coverage"]):
            self._diagnostics.setdefault("degraded", []).append({
                "table": table.name, "field": field, "chain": chain_id,
                "coverage": round(coverage, 4), "values": total,
            })
            return None
        return {"map": mapping, "keys": frozenset(mapping), "coverage": round(coverage, 4)}
