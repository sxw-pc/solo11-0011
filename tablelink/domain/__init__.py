"""主题域自动划分：确定性加权聚类、桥接表识别与域命名。"""
from .config import (
    DEFAULT_DOMAIN_CONFIG,
    build_domain_settings,
    validate_domain_config,
)
from .partition import annotate_graph, partition_domains
__all__ = [
    "DEFAULT_DOMAIN_CONFIG", "build_domain_settings", "validate_domain_config",
    "partition_domains", "annotate_graph",
]
