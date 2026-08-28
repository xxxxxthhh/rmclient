"""文档树模型与遍历助手。

服务端同一个对象有两套字段名（REPORT §2）：

    写响应（POST /ui/api/folders、/documents/upload）用大写键：
        {"ID","Type":"CollectionType"|"DocumentType","Parent","Name","Version"}
    读树（GET /ui/api/documents）用小写键：
        目录 {"id","name","lastModified","isFolder":true,"children":[...]}
        文档 {"id","name","lastModified","type","size"}   ← 没有 isFolder

两套字段并不携带同样的信息：写响应有 Version 没有 size/lastModified，
树条目有 size/lastModified/type 没有 Version。缺的就留空，不互相伪造。
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from .config import locked_folders

# 锁定目录：按名字在**根级**解析，整棵子树只读（CLAUDE.md 纪律 1）。默认是
# paperpal 的信箱 Mailbox，别的部署用 RMCLIENT_LOCKED_FOLDERS 改。嵌套的同名
# 目录不算——锁的是根级那一个。
def locked_label() -> str:
    """报错文案里用：把配置的锁定目录名列出来，默认就是 Mailbox。"""
    return ", ".join(locked_folders()) or "none configured"


@dataclass
class Folder:
    id: str
    name: str
    parent: str = ""
    last_modified: str = ""
    version: int | None = None  # 只有写响应给
    children: list[Node] = field(default_factory=list)


@dataclass
class Document:
    id: str
    name: str
    parent: str = ""
    last_modified: str = ""
    version: int | None = None  # 只有写响应给
    # 树上的 type：既有（已被设备同步过的）文档可信，值是 notebook/epub/pdf；
    # 但**刚上传的文档这里回显的是文件名本身**，不是 fileType（REPORT §4.1、§6）。
    # 要准确类型只能读 export_rmdoc 里的 .content 的 fileType。写响应不给这个字段。
    type: str = ""
    size: int = 0


type Node = Folder | Document


@dataclass
class Tree:
    entries: list[Node] = field(default_factory=list)
    trash: list[Node] = field(default_factory=list)


# ---- 解析 ----------------------------------------------------------


def parse_tree_entry(entry: dict, parent: str = "") -> Node:
    """读树的小写键 → 模型（目录递归带上 children）。"""
    node_id = str(entry.get("id") or "")
    name = entry.get("name") or ""
    last_modified = entry.get("lastModified") or ""
    # 目录判定只能靠 isFolder 存在与否——文档条目没有这个键（REPORT §2）。
    if bool(entry.get("isFolder")) or "children" in entry:
        folder = Folder(id=node_id, name=name, parent=parent, last_modified=last_modified)
        folder.children = [
            parse_tree_entry(child, node_id) for child in (entry.get("children") or [])
        ]
        return folder
    return Document(
        id=node_id,
        name=name,
        parent=parent,
        last_modified=last_modified,
        type=entry.get("type") or "",
        size=int(entry.get("size") or 0),
    )


def parse_tree(payload: dict) -> Tree:
    return Tree(
        entries=[parse_tree_entry(e, "") for e in (payload.get("Entries") or [])],
        trash=[parse_tree_entry(e, "") for e in (payload.get("Trash") or [])],
    )


def parse_write_response(payload: dict | list) -> Node:
    """写响应的大写键 → 模型。upload 回的是单元素数组，folders 回裸对象。"""
    if isinstance(payload, list):
        if not payload:
            raise ValueError("empty write response")
        payload = payload[0]
    node_id = str(payload.get("ID") or "")
    name = payload.get("Name") or ""
    parent = payload.get("Parent") or ""
    version = payload.get("Version")
    version = int(version) if version is not None else None
    # 这里的 Type 是目录/文档判别符，不是 fileType——绝不能塞进 Document.type。
    if payload.get("Type") == "CollectionType":
        return Folder(id=node_id, name=name, parent=parent, version=version)
    return Document(id=node_id, name=name, parent=parent, version=version)


# ---- 遍历 ----------------------------------------------------------


def mailbox_roots(entries: Iterable[Node]) -> list[Folder]:
    """所有根级、名字在锁定名单里的目录。嵌套的同名目录不算——锁的是根级那一个。

    paperpal 的 find_postbox 要求根级信箱唯一，不唯一就 fail closed。这里不抛
    （dump_tree 遇到怪树不该崩），改成同名的全都算：排除类助手宁可多排，不能漏排。
    """
    names = set(locked_folders())
    return [n for n in entries if isinstance(n, Folder) and n.name in names]


def exclude_mailbox(entries: Iterable[Node]) -> list[Node]:
    """去掉根级信箱（及其整棵子树）的根级列表。"""
    entries = list(entries)
    boxes = {box.id for box in mailbox_roots(entries)}
    return [n for n in entries if n.id not in boxes]


def mailbox_ids(entries: Iterable[Node]) -> set[str]:
    """信箱本身 + 整棵子树的所有 id。

    单点操作（delete/move 拿到一个 id）用它做断言——遍历过滤保护不了这类调用。
    """
    boxes = mailbox_roots(entries)
    return {box.id for box in boxes} | {node.id for _, node in walk(boxes)}


def walk(
    entries: Iterable[Node], *, skip_mailbox: bool = False, _path: tuple[str, ...] = ()
) -> Iterator[tuple[tuple[str, ...], Node]]:
    """深度优先遍历，产出 (祖先名字路径, 节点)。

    skip_mailbox 默认 False：展示要能看到信箱（SPEC M2「显示但锁定只读」）。
    任何会写的批量操作必须显式传 skip_mailbox=True。
    """
    if skip_mailbox and not _path:
        entries = exclude_mailbox(entries)
    for node in entries:
        yield _path, node
        if isinstance(node, Folder):
            yield from walk(node.children, skip_mailbox=False, _path=_path + (node.name,))


def find(entries: Iterable[Node], node_id: str) -> Node | None:
    for _, node in walk(entries):
        if node.id == node_id:
            return node
    return None


def deepest_first(ids: Iterable[str], entries: Iterable[Node]) -> list[str]:
    """按树深度倒序排——先删深后删浅。

    HashTree.Remove 不级联：先删父目录会把子项甩成根级孤儿（REPORT §4.5）。
    id 不在树上就报错：删除是硬删，宁可让调用方重新读树也不瞎猜顺序。
    """
    depth = {node.id: len(path) for path, node in walk(entries)}
    ids = list(ids)
    unknown = [i for i in ids if i not in depth]
    if unknown:
        raise ValueError(f"not in tree, refuse to guess delete order: {unknown}")
    return sorted(ids, key=lambda i: depth[i], reverse=True)


class PathError(LookupError):
    """可见名路径解析失败，附带该层的候选目录名。"""

    def __init__(self, message: str, candidates: list[str]):
        self.candidates = candidates
        super().__init__(message)


def children_of(entries: Iterable[Node], parent_id: str) -> list[Node]:
    """parent_id 为空串即根级；否则必须是一个目录。"""
    entries = list(entries)
    if not parent_id:
        return entries
    node = find(entries, parent_id)
    if node is None:
        raise PathError(f"{parent_id} not in tree", [])
    if not isinstance(node, Folder):
        raise PathError(f"{parent_id} is a document, not a folder", [])
    return node.children


def resolve_path(entries: Iterable[Node], path: str) -> Folder:
    """按树上的可见名逐层解析目录，如 "Books/CS"。

    找不到就报错并列出该层候选——绝不静默退回根级（推错地方比报错糟得多）。
    同层多个同名目录也报错：服务端允许同名（REPORT §10），客户端不猜。
    """
    parts = [p for p in path.strip("/").split("/") if p]
    if not parts:
        raise PathError(f"empty path: {path!r}", [])
    level = list(entries)
    current: Folder | None = None
    for i, part in enumerate(parts):
        folders = [n for n in level if isinstance(n, Folder) and n.name == part]
        if len(folders) > 1:
            raise PathError(
                f"{'/'.join(parts[: i + 1])!r} is ambiguous: {len(folders)} folders share that name",
                [f.name for f in level if isinstance(f, Folder)],
            )
        if not folders:
            docs = [n for n in level if n.name == part]
            hint = " (that is a document, not a folder)" if docs else ""
            raise PathError(
                f"no folder {'/'.join(parts[: i + 1])!r}{hint}",
                sorted(n.name for n in level if isinstance(n, Folder)),
            )
        current = folders[0]
        level = current.children
    assert current is not None
    return current


def subtree_ids(entries: Iterable[Node], node_id: str) -> list[str]:
    """节点自己 + 整棵子树的所有 id（深度优先，父在子前）。"""
    node = find(entries, node_id)
    if node is None:
        raise PathError(f"{node_id} not in tree", [])
    return [n.id for _, n in walk([node])]


def is_descendant(entries: Iterable[Node], node_id: str, candidate_id: str) -> bool:
    """candidate_id 是不是 node_id 自己或它的子孙。

    把一个目录移进它自己的子孙里会把整棵子树甩飞，移动前必须拦。
    """
    return candidate_id in set(subtree_ids(entries, node_id))
