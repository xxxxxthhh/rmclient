#!/usr/bin/env python3
"""离线 demo 的薄壳——真正的实现在 rmclient/demo.py，随包一起发布。

    uv run python scripts/demo_serve.py --port 9000     # 源码仓库里的老写法
    rmclient demo --port 9000                           # 装好之后的写法

保留这个文件只为向后兼容（旧文档、旧书签里可能还写着它）。新写法请用
`rmclient demo`：那条路不需要克隆仓库。
"""

import argparse

from rmclient.demo import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="demo_serve", description="Run the rmclient web UI against an in-memory demo cloud")
    parser.add_argument("--port", type=int, default=8001, help="port to listen on (default 8001)")
    return run(port=parser.parse_args(argv).port)


if __name__ == "__main__":
    raise SystemExit(main())
