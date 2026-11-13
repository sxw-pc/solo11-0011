"""表链测绘仪的自定义异常。"""
class TableLinkError(Exception):
    """项目内所有可预期异常的基类。"""
class ConfigError(TableLinkError):
    """配置校验失败，携带出错位置与修复提示。"""
    def __init__(self, path, key, message, hint):
        self.path = str(path)
        self.key = key or "<root>"
        self.message = message
        self.hint = hint
        super().__init__(
            "配置错误 [{0}] 字段 {1}: {2}。修复建议: {3}".format(
                self.path, self.key, message, hint
            )
        )
class LoaderError(TableLinkError):
    """数据源加载失败。"""
    def __init__(self, source, message):
        self.source = str(source)
        self.message = message
        super().__init__("数据加载失败 [{0}]: {1}".format(source, message))
class DetectionError(TableLinkError):
    """关联检测阶段失败。"""
class ExportError(TableLinkError):
    """结果导出失败。"""
class IncrementalError(TableLinkError):
    """历史规则读取或增量对比失败。"""
