#!/usr/bin/env python3
"""只读：登录自建云，打印完整文档树（含回收站）。

    uv run python scripts/dump_tree.py

信箱按 SPEC M2 的约定「显示但锁定只读」——这里显示它并标 🔒，不做任何写操作。
"""

from rmclient import RmClient
from rmclient.models import Folder, display_type, mailbox_ids


def show(nodes, depth, locked_ids):
    for node in sorted(nodes, key=lambda n: (not isinstance(n, Folder), n.name.lower())):
        pad = "  " * depth
        lock = " 🔒" if node.id in locked_ids else ""
        if isinstance(node, Folder):
            print(f"{pad}📁 {node.name}/{lock}")
            show(node.children, depth + 1, locked_ids)
        else:
            print(f"{pad}·  {node.name}  [{display_type(node) or '?'}, "
                  f"{node.size / 1024:.0f}KB, {node.last_modified[:10]}]{lock}")


def main() -> None:
    with RmClient() as client:
        client.login()
        tree = client.list_tree()
    locked = mailbox_ids(tree.entries)
    print(f"=== 根级（{len(tree.entries)} 项）===")
    show(tree.entries, 0, locked)
    print(f"\n=== 回收站（{len(tree.trash)} 项）===")
    show(tree.trash, 0, set())


if __name__ == "__main__":
    main()
