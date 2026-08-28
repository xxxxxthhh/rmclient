"""models 的纯逻辑测试：双键名解析、Mailbox 排除、删除顺序。不打真实 API。"""

import pytest

from rmclient.models import (
    Document,
    PathError,
    Folder,
    children_of,
    deepest_first,
    exclude_mailbox,
    find,
    is_descendant,
    mailbox_ids,
    mailbox_roots,
    parse_tree,
    parse_tree_entry,
    parse_write_response,
    resolve_path,
    subtree_ids,
    walk,
)

# 读树用小写键（REPORT §2）。目录有 isFolder，文档没有但有 type/size。
TREE_PAYLOAD = {
    "Entries": [
        {
            "id": "mb",
            "name": "Mailbox",
            "lastModified": "2026-08-28T07:41:06.731Z",
            "isFolder": True,
            "children": [
                {"id": "mb-doc", "name": "letter", "type": "notebook", "size": 10},
                {
                    "id": "mb-sub",
                    "name": "回信",
                    "isFolder": True,
                    "children": [{"id": "mb-deep", "name": "reply", "type": "pdf", "size": 1}],
                },
            ],
        },
        {
            "id": "books",
            "name": "Books",
            "isFolder": True,
            "children": [
                # 嵌套的同名目录不是信箱：信箱按根级唯一名字解析。
                {
                    "id": "nested-mb",
                    "name": "Mailbox",
                    "isFolder": True,
                    "children": [{"id": "nested-doc", "name": "x", "type": "epub", "size": 2}],
                },
                {"id": "b1", "name": "Book One", "type": "epub", "size": 3993},
            ],
        },
        {"id": "loose", "name": "Loose", "type": "pdf", "size": 601},
    ],
    "Trash": [{"id": "t1", "name": "old", "type": "pdf", "size": 1}],
}


def tree():
    return parse_tree(TREE_PAYLOAD)


# ---- 双键名 --------------------------------------------------------


def test_tree_entry_document_lowercase_keys():
    doc = parse_tree_entry({"id": "b1", "name": "Book One", "type": "epub", "size": 3993}, "books")
    assert isinstance(doc, Document)
    assert (doc.id, doc.name, doc.parent, doc.type, doc.size) == ("b1", "Book One", "books", "epub", 3993)


def test_tree_entry_folder_has_no_size_or_type():
    folder = parse_tree_entry({"id": "f", "name": "F", "isFolder": True, "lastModified": "2026-08-28T00:00:00Z"})
    assert isinstance(folder, Folder)
    assert folder.last_modified == "2026-08-28T00:00:00Z"
    assert folder.children == []


def test_tree_entry_children_key_alone_means_folder():
    # 目录判定沿用 spike 在真实 70 条目树上跑过的谓词：isFolder 或 children 存在。
    assert isinstance(parse_tree_entry({"id": "f", "name": "F", "children": []}), Folder)


def test_parse_tree_propagates_parent_and_trash():
    t = tree()
    assert [n.id for n in t.entries] == ["mb", "books", "loose"]
    assert [n.id for n in t.trash] == ["t1"]
    assert find(t.entries, "mb-deep").parent == "mb-sub"
    assert find(t.entries, "b1").parent == "books"


def test_write_response_folder_uppercase_keys():
    node = parse_write_response(
        {"ID": "9bc59550", "Type": "CollectionType", "Parent": "", "Name": "spike", "Version": 0}
    )
    assert isinstance(node, Folder)
    assert (node.id, node.name, node.parent, node.version) == ("9bc59550", "spike", "", 0)


def test_write_response_upload_is_single_element_list():
    node = parse_write_response(
        [{"ID": "u1", "Type": "DocumentType", "Parent": "p", "Name": "Book One", "Version": 1}]
    )
    assert isinstance(node, Document)
    assert (node.id, node.parent, node.version) == ("u1", "p", 1)
    # 写响应的 Type 是目录/文档判别符，不是 fileType——不能塞进 type。
    assert node.type == ""
    # 写响应不带 size/lastModified，留空，不伪造。
    assert (node.size, node.last_modified) == (0, "")


# ---- Mailbox -------------------------------------------------------


def test_mailbox_root_is_root_level_only():
    assert [f.id for f in mailbox_roots(tree().entries)] == ["mb"]


def test_multiple_root_mailboxes_are_all_excluded():
    # 根级信箱本该唯一；真出现两个，排除类助手宁可多排也不能漏排。
    payload = {
        "Entries": [
            {"id": "mb1", "name": "Mailbox", "isFolder": True,
             "children": [{"id": "d1", "name": "a", "type": "notebook", "size": 1}]},
            {"id": "mb2", "name": "Mailbox", "isFolder": True,
             "children": [{"id": "d2", "name": "b", "type": "notebook", "size": 1}]},
            {"id": "keep", "name": "Books", "isFolder": True, "children": []},
        ]
    }
    entries = parse_tree(payload).entries
    assert mailbox_ids(entries) == {"mb1", "d1", "mb2", "d2"}
    assert [n.id for n in exclude_mailbox(entries)] == ["keep"]


def test_mailbox_ids_cover_whole_subtree_but_not_nested_namesake():
    ids = mailbox_ids(tree().entries)
    assert ids == {"mb", "mb-doc", "mb-sub", "mb-deep"}
    assert "nested-mb" not in ids and "nested-doc" not in ids


def test_exclude_mailbox_drops_only_the_root_mailbox():
    assert [n.id for n in exclude_mailbox(tree().entries)] == ["books", "loose"]


def test_walk_shows_mailbox_by_default():
    # 展示要能看到信箱（SPEC M2：显示但锁定只读），所以默认不跳。
    assert "mb-deep" in {node.id for _, node in walk(tree().entries)}


def test_walk_skip_mailbox_drops_subtree_keeps_nested_namesake():
    seen = {node.id for _, node in walk(tree().entries, skip_mailbox=True)}
    assert seen.isdisjoint({"mb", "mb-doc", "mb-sub", "mb-deep"})
    assert {"nested-mb", "nested-doc", "b1", "loose"} <= seen


def test_walk_yields_ancestor_path():
    paths = {node.id: path for path, node in walk(tree().entries)}
    assert paths["loose"] == ()
    assert paths["b1"] == ("Books",)
    assert paths["mb-deep"] == ("Mailbox", "回信")


# ---- 删除顺序 ------------------------------------------------------


def test_deepest_first_orders_children_before_parents():
    # HashTree.Remove 不级联：父目录先删会把子项甩成根级孤儿。
    ordered = deepest_first(["books", "nested-mb", "nested-doc", "loose"], tree().entries)
    assert ordered.index("nested-doc") < ordered.index("nested-mb") < ordered.index("books")
    assert ordered[-1] in ("books", "loose")


def test_deepest_first_refuses_unknown_id():
    with pytest.raises(ValueError, match="not in tree"):
        deepest_first(["ghost"], tree().entries)


# ---- 可见名路径解析 ------------------------------------------------


def test_resolve_path_walks_visible_names():
    assert resolve_path(tree().entries, "Books").id == "books"
    assert resolve_path(tree().entries, "Books/Mailbox").id == "nested-mb"
    assert resolve_path(tree().entries, "/Books/").id == "books"


def test_resolve_path_lists_candidates_when_missing():
    with pytest.raises(PathError, match="no folder 'Books/Nope'") as exc:
        resolve_path(tree().entries, "Books/Nope")
    assert exc.value.candidates == ["Mailbox"]


def test_resolve_path_rejects_a_document():
    with pytest.raises(PathError, match="document, not a folder"):
        resolve_path(tree().entries, "Books/Book One")


def test_resolve_path_refuses_ambiguous_siblings():
    # 服务端允许同名目录（REPORT §10），客户端不猜是哪一个。
    payload = {
        "Entries": [
            {"id": "d1", "name": "dup", "isFolder": True, "children": []},
            {"id": "d2", "name": "dup", "isFolder": True, "children": []},
        ]
    }
    with pytest.raises(PathError, match="ambiguous"):
        resolve_path(parse_tree(payload).entries, "dup")


def test_resolve_path_refuses_an_empty_path():
    with pytest.raises(PathError, match="empty path"):
        resolve_path(tree().entries, "/")


def test_children_of_root_and_folder():
    entries = tree().entries
    assert [n.id for n in children_of(entries, "")] == ["mb", "books", "loose"]
    assert [n.id for n in children_of(entries, "books")] == ["nested-mb", "b1"]
    with pytest.raises(PathError, match="not a folder"):
        children_of(entries, "b1")


# ---- 子树 ----------------------------------------------------------


def test_subtree_ids_includes_the_node_itself():
    assert subtree_ids(tree().entries, "books") == ["books", "nested-mb", "nested-doc", "b1"]
    assert subtree_ids(tree().entries, "loose") == ["loose"]


def test_subtree_ids_refuses_an_unknown_id():
    with pytest.raises(PathError, match="not in tree"):
        subtree_ids(tree().entries, "ghost")


def test_is_descendant_covers_self_and_children():
    entries = tree().entries
    assert is_descendant(entries, "books", "books") is True
    assert is_descendant(entries, "books", "nested-doc") is True
    assert is_descendant(entries, "books", "loose") is False


# ---- 锁定目录可配置（默认仍是 Mailbox）----------------------------


def test_locked_folder_name_comes_from_the_configuration(monkeypatch):
    payload = {
        "Entries": [
            {"id": "inbox", "name": "Inbox", "isFolder": True,
             "children": [{"id": "kid", "name": "letter", "type": "notebook", "size": 1}]},
            {"id": "mb", "name": "Mailbox", "isFolder": True, "children": []},
        ]
    }
    entries = parse_tree(payload).entries
    monkeypatch.setenv("RMCLIENT_LOCKED_FOLDERS", "Inbox")
    assert mailbox_ids(entries) == {"inbox", "kid"}   # 换了名字，Mailbox 就不再锁
    assert [n.id for n in exclude_mailbox(entries)] == ["mb"]


def test_nothing_is_locked_when_the_list_is_empty(monkeypatch):
    monkeypatch.setenv("RMCLIENT_LOCKED_FOLDERS", "")
    assert mailbox_ids(tree().entries) == set()
    assert len(exclude_mailbox(tree().entries)) == 3


def test_several_folders_can_be_locked_at_once(monkeypatch):
    monkeypatch.setenv("RMCLIENT_LOCKED_FOLDERS", "Mailbox,Books")
    ids = mailbox_ids(tree().entries)
    assert {"mb", "mb-doc", "books", "b1"} <= ids


def test_the_default_is_still_mailbox_only():
    # 我们自己的部署行为一丝不变，这条是硬纪律。
    assert [f.name for f in mailbox_roots(tree().entries)] == ["Mailbox"]
