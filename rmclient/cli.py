"""命令行：推书。

    rmclient push book.epub                  # 传到根级
    rmclient push book.epub --to Books/CS    # 按树上的可见名路径指定目录
    rmclient push book.epub --to Books --force   # 明知重名也要再传一份
    rmclient serve                           # 起本地 Web

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
        print(f"没有这个文件：{path}", file=sys.stderr)
        return 2
    data = path.read_bytes()

    with RmClient() as client:
        client.login()
        try:
            parent_id = resolve_target(client.list_tree().entries, args.to)
        except PathError as exc:
            print(f"--to 解析失败：{exc}", file=sys.stderr)
            if exc.candidates:
                print(f"  该层可选目录：{', '.join(exc.candidates)}", file=sys.stderr)
            return 2
        except PermissionError as exc:
            print(f"{exc}", file=sys.stderr)
            return 2

        try:
            node, existing = push(client, data, path.name, parent_id=parent_id, force=args.force)
        except ValidationError as exc:
            print(f"拒绝上传：{exc}", file=sys.stderr)
            return 2
        except DuplicateName as exc:
            print(f"目标目录里已经有 {exc.name!r}（{len(exc.existing)} 份）。", file=sys.stderr)
            print("服务端不覆盖也不去重：再传一次会多出一份独立副本，设备端两本同名无法区分"
                  "（REPORT §10）。确实要传就加 --force。", file=sys.stderr)
            for doc in exc.existing:
                print(f"  已有：{doc.id}  {doc.name}  {doc.size / 1024:.0f}KB", file=sys.stderr)
            return 3
        except PermissionError as exc:
            print(f"{exc}", file=sys.stderr)
            return 2
        except RmApiError as exc:
            print(f"上传失败：HTTP {exc.status} {exc.error or exc.body}", file=sys.stderr)
            return 1

    where = args.to or "（根级）"
    print(f"✓ 已上传 {visible_name(path.name)!r} → {where}")
    print(f"  UUID {node.id}")
    if existing:
        print(f"  ⚠ 同名的还有 {len(existing)} 份，设备端会看到 {len(existing) + 1} 本同名书")
    print("  设备端需要同步一次才会出现")
    return 0


def cmd_serve(args) -> int:
    import uvicorn  # 延迟导入：push 不该为 Web 依赖买单

    from .web import app

    # 先把配置读通再起服务：不然错要等到第一个请求才以 500 的形式冒出来。
    load_credentials()
    print(f"rmclient → {base_url()}  （锁定目录：{', '.join(locked_folders()) or '无'}）")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rmclient", description="reMarkable 自建云内容管理")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("push", help="上传一本书（.epub/.pdf/.rmdoc）")
    p.add_argument("file")
    p.add_argument("--to", help="目标目录的可见名路径，如 'Books/CS'；不给就传到根级")
    p.add_argument("--force", action="store_true", help="重名也照传（会多出一份独立副本）")
    p.set_defaults(func=cmd_push)

    p = sub.add_parser("serve", help="起本地 Web（拖拽上传）")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        # 配置问题给一句人话，不甩 traceback。
        print(f"配置有问题：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
