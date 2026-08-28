"""命令行：推书。输出一律英文（公开项目的默认脸面），退出码不变。

    rmclient push book.epub                  # 传到根级
    rmclient push book.epub --to Books/CS    # 按树上的可见名路径指定目录
    rmclient push book.epub --to Books --force   # 明知重名也要再传一份
    rmclient serve                           # 起本地 Web
    rmclient demo                            # 离线试玩，不需要服务器和凭据

--to 只解析已存在的目录，不自动创建；找不到就报错并列候选（推错地方比报错糟得多）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .api import RmApiError, RmClient
from .config import ConfigError, base_url, load_credentials, locked_folders
from .models import Folder, PathError, locked_label, mailbox_ids, resolve_path
from .push import DuplicateName, push, visible_name
from .validate import ValidationError


def resolve_target(entries: list, path: str | None) -> str:
    """--to 的可见名路径 → 目标目录 UUID（None/空 = 根级）。

    信箱查两遍：路径第一段就叫 Mailbox 的直接拒，解析出来的 id 再对信箱子树查一次
    （第二道拦的是没预料到的路径形态，比如根级出现了第二个同名信箱）。
    """
    if not path:
        return ""
    if path.strip("/").split("/")[0] in locked_folders():
        raise PermissionError(f"refusing to push into a locked folder ({locked_label()})")
    folder: Folder = resolve_path(entries, path)
    if folder.id in mailbox_ids(entries):
        raise PermissionError(f"refusing to push into a locked folder ({locked_label()}): {folder.id}")
    return folder.id


def cmd_push(args) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 2
    data = path.read_bytes()

    with RmClient() as client:
        client.login()
        try:
            parent_id = resolve_target(client.list_tree().entries, args.to)
        except PathError as exc:
            print(f"--to did not resolve: {exc}", file=sys.stderr)
            if exc.candidates:
                print(f"  folders at that level: {', '.join(exc.candidates)}", file=sys.stderr)
            return 2
        except PermissionError as exc:
            print(f"{exc}", file=sys.stderr)
            return 2

        try:
            node, existing = push(client, data, path.name, parent_id=parent_id, force=args.force)
        except ValidationError as exc:
            print(f"refusing to upload: {exc}", file=sys.stderr)
            return 2
        except DuplicateName as exc:
            print(f"the target folder already holds {exc.name!r} "
                  f"({len(exc.existing)} of them).", file=sys.stderr)
            print("The server neither overwrites nor de-duplicates: pushing again adds an "
                  "independent second copy, and the device cannot tell two same-named books "
                  "apart (REPORT §10). Pass --force to do it anyway.", file=sys.stderr)
            for doc in exc.existing:
                print(f"  already there: {doc.id}  {doc.name}  {doc.size / 1024:.0f}KB",
                      file=sys.stderr)
            return 3
        except PermissionError as exc:
            print(f"{exc}", file=sys.stderr)
            return 2
        except RmApiError as exc:
            print(f"upload failed: HTTP {exc.status} {exc.error or exc.body}", file=sys.stderr)
            return 1

    where = args.to or "(root)"
    print(f"✓ uploaded {visible_name(path.name)!r} → {where}")
    print(f"  UUID {node.id}")
    if existing:
        print(f"  ⚠ {len(existing)} more of that name already exist; "
              f"the device will show {len(existing) + 1} identically named books")
    print("  the device has to sync once before it shows up")
    return 0


def cmd_serve(args) -> int:
    import uvicorn  # 延迟导入：push 不该为 Web 依赖买单

    from .web import app

    # 先把配置读通再起服务：不然错要等到第一个请求才以 500 的形式冒出来。
    load_credentials()
    print(f"rmclient → {base_url()}  "
          f"(locked folders: {', '.join(locked_folders()) or 'none'})")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def cmd_demo(args) -> int:
    """离线 demo：内存假云 + 公版书数据集，不读凭据、不出网。"""
    from .demo import run

    return run(port=args.port)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rmclient", description="Content manager for your self-hosted reMarkable cloud"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("push", help="upload one book (.epub/.pdf/.rmdoc)")
    p.add_argument("file")
    p.add_argument("--to", help="target folder as a visible-name path, e.g. 'Books/CS'; "
                                "omit for the root")
    p.add_argument("--force", action="store_true",
                   help="upload even if the name exists (adds an independent second copy)")
    p.set_defaults(func=cmd_push)

    p = sub.add_parser("serve", help="start the local web UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("demo", help="try the web UI offline, against an in-memory demo cloud")
    p.add_argument("--port", type=int, default=8001,
                   help="port to listen on (default 8001, so it will not fight `serve`)")
    p.set_defaults(func=cmd_demo)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        # 配置问题给一句人话，不甩 traceback。
        print(f"bad configuration: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
