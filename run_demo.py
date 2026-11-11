#!/usr/bin/env python
"""一键批处理演示：加载内置数据并输出全部结果。"""
import argparse
import logging
import os
import sys
from tablelink.exceptions import TableLinkError
from tablelink.pipeline import run_pipeline
ROOT = os.path.dirname(os.path.abspath(__file__))
def parse_args():
    parser = argparse.ArgumentParser(description="表链测绘仪离线演示")
    parser.add_argument("--config", default=os.path.join(ROOT, "config.yaml"),
                        help="YAML 配置文件路径")
    parser.add_argument("--baseline", default=None,
                        help="历史关联规则 JSON/YAML，用于增量对比")
    parser.add_argument("--no-baseline", action="store_true",
                        help="禁用配置中的默认历史基线")
    parser.add_argument("--quiet", action="store_true", help="只输出最终摘要")
    return parser.parse_args()
def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(message)s",
    )
    try:
        result = run_pipeline(
            config_path=args.config,
            base_dir=ROOT,
            baseline_path=args.baseline,
            use_default_baseline=not args.no_baseline,
        )
    except TableLinkError as exc:
        print("[失败] {0}".format(exc), file=sys.stderr)
        return 2
    summary = result.summary()
    print("")
    print("表链测绘仪 · 离线扫描完成")
    print("-" * 52)
    print("数据表: {0}  字段: {1}  去重关联: {2}  加载异常: {3}".format(
        summary["tables"], summary["fields"], summary["associations"],
        summary["load_errors"],
    ))
    print("关系类型: " + ", ".join(
        "{0}={1}".format(key, value)
        for key, value in summary["relation_types"].items()
    ))
    if summary["diff"]:
        print("增量对比: 新增 {added} / 失效 {removed} / 置信度变化 {confidence_changed}".format(
            **summary["diff"]
        ))
    else:
        print("增量对比: 未提供历史规则")
    print("")
    print("输出文件:")
    for key in ("rules_json", "rules_yaml", "report_md", "graph_json", "graph_html"):
        print("  {0:<12} {1}".format(key, result.outputs[key]))
    print("")
    print("提示: 直接双击 graph.html 即可离线查看交互图谱。")
    return 0
if __name__ == "__main__":
    sys.exit(main())
