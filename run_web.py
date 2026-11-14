#!/usr/bin/env python
"""启动仅监听回环地址的本地 Web 控制台。"""
import argparse
import os
import sys
from tablelink.exceptions import TableLinkError
from tablelink.web import create_app
ROOT = os.path.dirname(os.path.abspath(__file__))
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
def main():
    parser = argparse.ArgumentParser(description="表链测绘仪本地 Web 控制台")
    parser.add_argument("--config", default=os.path.join(ROOT, "config.yaml"))
    parser.add_argument("--host", default=None, help="仅允许回环地址")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    try:
        app = create_app(args.config, base_dir=ROOT)
        config = app.extensions["tablelink"]["manager"].load()
    except TableLinkError as exc:
        print("[失败] {0}".format(exc), file=sys.stderr)
        return 2
    host = args.host or config["web"]["host"]
    port = args.port or config["web"]["port"]
    if host not in LOOPBACK:
        print("[失败] 安全限制：只能绑定 127.0.0.1、localhost 或 ::1", file=sys.stderr)
        return 2
    print("表链测绘仪本地控制台: http://{0}:{1}".format(host, port))
    print("仅监听本机回环地址，按 Ctrl+C 停止。")
    app.run(host=host, port=port, debug=bool(config["web"]["debug"]),
            use_reloader=False, threaded=True)
    return 0
if __name__ == "__main__":
    sys.exit(main())
