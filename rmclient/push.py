"""推书：CLI 与 Web 共用的那层策略（目标校验 + 重名检测 + 上传）。

上传本身在 api.upload（后缀 + 内容校验也在那）。这里只加两条 api 层看不到的规矩：
目标不许落在信箱子树里，以及重名要用户显式确认。
"""

from __future__ import annotations

import os

from .api import RmClient
from .models import Document, Node, Tree, children_of, find, mailbox_ids


class DuplicateName(Exception):
    """目标目录里已经有同可见名的文档。"""

    def __init__(self, name: str, existing: list[Document]):
        self.name, self.existing = name, existing
        super().__init__(
            f"{name!r} already exists in the target folder ({len(existing)} copy/copies). "
            "The server never overwrites or dedupes: pushing again adds another independent "
            "copy with the same visible name, indistinguishable on the device (REPORT §10)."
        )


def visible_name(filename: str) -> str:
    """服务端存的可见名是文件名剥掉扩展名（TrimSuffix，REPORT §4.6）。"""
    return os.path.splitext(os.path.basename(filename))[0]


def check_target(tree: Tree, parent_id: str) -> None:
    """目标必须是一个存在的目录，且不在信箱子树里。

    Web 的下拉框过滤是展示逻辑，保护不了直接带着 id 打过来的请求——所以这里再查一次。
    """
    if parent_id and parent_id in mailbox_ids(tree.entries):
        raise PermissionError(f"refusing to touch the Mailbox subtree: {parent_id}")
    children_of(tree.entries, parent_id)  # 不存在 / 不是目录会抛 PathError


def find_duplicates(tree: Tree, parent_id: str, name: str) -> list[Document]:
    return [n for n in children_of(tree.entries, parent_id) if isinstance(n, Document) and n.name == name]


def push(
    client: RmClient, data: bytes, filename: str, *, parent_id: str = "", force: bool = False
) -> tuple[Node, list[Document]]:
    """校验目标 → 查重 → 上传。返回 (新文档, 之前就存在的同名文档)。

    force=True 时照传不误，但同名的那几份会一起留在设备上（服务端不覆盖）。
    """
    tree = client.list_tree()
    check_target(tree, parent_id)
    name = visible_name(filename)
    existing = find_duplicates(tree, parent_id, name)
    if existing and not force:
        raise DuplicateName(name, existing)
    return client.upload(data, filename, parent=parent_id, entries=tree.entries), existing
