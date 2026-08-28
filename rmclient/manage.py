"""树管理策略：新建目录 / 重命名 / 移动 / 删除。

api 层已经有两道通用闸（信箱断言、删除白名单）。这一层加的是「操作本身讲不讲得通」：
移动不能移进自己的子孙、重命名不能置空、删除前先把整棵子树摊开给用户看清楚。
"""

from __future__ import annotations

from .api import RmClient
from .models import (
    Document,
    Folder,
    Node,
    Tree,
    find,
    is_descendant,
    mailbox_ids,
    subtree_ids,
    walk,
)


class TreeChanged(Exception):
    """删除计划与当前树对不上——中间有人（多半是设备同步）动过这棵子树。"""

    def __init__(self, added: list[str], removed: list[str]):
        self.added, self.removed = added, removed
        super().__init__(
            f"the tree changed since the plan was made: {len(added)} item(s) appeared, "
            f"{len(removed)} disappeared. Re-plan before deleting."
        )


def check_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("name must not be empty")
    return name


def check_not_mailbox(tree: Tree, node_id: str) -> None:
    if node_id and node_id in mailbox_ids(tree.entries):
        raise PermissionError(f"refusing to touch the Mailbox subtree: {node_id}")


def check_move(tree: Tree, node_id: str, parent_id: str) -> None:
    """信箱两头都查，再拦「移进自己的子孙」。"""
    check_not_mailbox(tree, node_id)
    check_not_mailbox(tree, parent_id)
    if parent_id and is_descendant(tree.entries, node_id, parent_id):
        raise ValueError(f"refusing to move {node_id} into itself or its own subtree")


def plan_delete(tree: Tree, node_id: str) -> list[dict]:
    """删除计划：这一刀会删掉的每一项，先深后浅（就是实际删除顺序）。

    删目录时要把整棵子树摊给用户看——HashTree.Remove 不级联，客户端得自己删干净，
    而且删除是硬删、会同步删掉设备上的文件（REPORT §4.4/§4.5/§9.2）。
    """
    check_not_mailbox(tree, node_id)
    root = find(tree.entries, node_id)
    if root is None:
        raise LookupError(f"{node_id} not in tree")
    ids = set(subtree_ids(tree.entries, node_id))
    items = [
        {
            "id": node.id,
            "name": node.name,
            "kind": "folder" if isinstance(node, Folder) else "doc",
            "type": getattr(node, "type", ""),
            "size": getattr(node, "size", 0),
            "depth": len(path),
        }
        for path, node in walk([root])
        if node.id in ids
    ]
    return sorted(items, key=lambda i: i["depth"], reverse=True)


# ---- 执行（薄，真正的守卫在 api 层）--------------------------------


def create_folder(client: RmClient, name: str, parent_id: str = "") -> Node:
    tree = client.list_tree()
    check_not_mailbox(tree, parent_id)
    if parent_id and not isinstance(find(tree.entries, parent_id), Folder):
        raise LookupError(f"{parent_id} is not a folder in the tree")
    return client.create_folder(check_name(name), parent_id)


def rename(client: RmClient, node_id: str, new_name: str) -> str:
    """改名 = 原 parent 不动 + 新 name（`PUT` 的 name 无条件覆写，REPORT §9.1）。"""
    tree = client.list_tree()
    check_not_mailbox(tree, node_id)
    node = find(tree.entries, node_id)
    if node is None:
        raise LookupError(f"{node_id} not in tree")
    name = check_name(new_name)
    client.move(node_id, node.parent, name=name, entries=tree.entries)
    return name


def move(client: RmClient, node_id: str, parent_id: str) -> None:
    """只移动不改名：name=None 走 api 的读树取原名路径，绝不发空名。"""
    tree = client.list_tree()
    check_move(tree, node_id, parent_id)
    client.move(node_id, parent_id, name=None, entries=tree.entries)


def delete_subtree(client: RmClient, node_id: str, expected_ids: list[str]) -> dict:
    """删整棵子树：重算计划 → 与用户确认过的清单比对 → 先深后浅删 → 立即复查。

    白名单用的是**服务端此刻重算出来的那份**，expected_ids 只用来比对；对不上就
    抛 TreeChanged，让用户重新看一遍再确认。
    """
    tree = client.list_tree()
    plan = plan_delete(tree, node_id)
    ids = [item["id"] for item in plan]
    added = sorted(set(ids) - set(expected_ids))
    removed = sorted(set(expected_ids) - set(ids))
    if added or removed:
        raise TreeChanged(added, removed)
    deleted = client.delete_many(ids, allowed_ids=set(ids), entries=tree.entries)
    after = client.list_tree().entries
    return {"deleted": deleted, "residue": [i for i in ids if find(after, i)]}


def check_resurrection(client: RmClient, ids: list[str]) -> list[dict]:
    """复活复查：删掉的 UUID 有没有被设备端原样推回来（REPORT §9.2）。

    删完立刻查基本查不到东西——复活要等设备同步一轮，所以这个得让用户过一会儿再点。
    """
    entries = client.list_tree().entries
    back = []
    for path, node in walk(entries):
        if node.id in ids:
            back.append(
                {
                    "id": node.id,
                    "name": node.name,
                    "path": "/".join(path),
                    "size": node.size if isinstance(node, Document) else 0,
                }
            )
    return back
