"""组合键（多列复合外键）关联检测。"""
from .metrics import FIELD_SEP, detect_composite
from .pruning import Degradation, build_candidates

__all__ = ["detect_composite", "build_candidates", "Degradation", "FIELD_SEP"]
