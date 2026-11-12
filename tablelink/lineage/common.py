"""快照比对共用的常量与小工具。

归因模型：每条差异携带 origin（data / config / detector / mixed / unknown）。
来源层条目由「来源文件指纹或状态变化」（数据侧）与「sources 配置段变化」
（配置侧）推断；检测层条目由端点字段/表/来源文件的变化事件与检测配置段
（explicit/overlap/fd）、自定义规则文件指纹的变化事件回溯，全部信号都
不存在时归为 detector（检测规则实现本身变化）。
"""
AUDIT_FORMAT = "tablelink-drift-audit"
AUDIT_VERSION = "1.0"
NON_NULL_SIGNIFICANT = 0.1
DETECTION_SECTIONS = ("explicit", "overlap", "fd")
STATE_DATA_SIGNAL = {"missing", "error", "empty"}
STATE_CONFIG_SIGNAL = {"filtered"}


def index_by(items, key):
    return {item[key]: item for item in items}


def combine_origins(origins):
    """把一组归因信号合并为单一归因；空集返回 none，全未知返回 unknown。"""
    found = {origin for origin in origins if origin and origin != "unknown"}
    if not found:
        return "unknown" if list(origins) else "none"
    if len(found) == 1:
        return found.pop()
    return "mixed"
