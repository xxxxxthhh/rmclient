"""manage 层的离线测试：移动/重命名/新建/删除的策略与执行。不打真实云。"""

import pytest

from rmclient.manage import (
    TreeChanged,
    check_move,
    check_name,
    check_resurrection,
    create_folder,
    delete_subtree,
    move,
    plan_delete,
    rename,
)
from tests.fixtures import logged_in, stateful_handler


def tree_of(client):
    return client.list_tree()


# ---- 纯策略 --------------------------------------------------------


def test_check_name_strips_and_refuses_empty():
    assert check_name("  Book  ") == "Book"
    for bad in ("", "   "):
        with pytest.raises(ValueError, match="must not be empty"):
            check_name(bad)


def test_check_move_refuses_both_ends_of_the_mailbox():
    client, _ = logged_in()
    tree = tree_of(client)
    with pytest.raises(PermissionError, match="Mailbox"):
        check_move(tree, "mb-doc", "books")
    with pytest.raises(PermissionError, match="Mailbox"):
        check_move(tree, "b1", "mb")


def test_check_move_refuses_moving_a_folder_into_itself_or_its_subtree():
    client, _ = logged_in()
    tree = tree_of(client)
    with pytest.raises(ValueError, match="itself or its own subtree"):
        check_move(tree, "books", "books")
    with pytest.raises(ValueError, match="itself or its own subtree"):
        check_move(tree, "books", "cs")


def test_check_move_allows_a_normal_move():
    client, _ = logged_in()
    check_move(tree_of(client), "b1", "cs")
    check_move(tree_of(client), "b1", "")  # 到根级


def test_plan_delete_lists_the_whole_subtree_deepest_first():
    client, _ = logged_in()
    plan = plan_delete(tree_of(client), "books")
    assert [i["id"] for i in plan][-1] == "books"  # 父目录最后删
    assert {i["id"] for i in plan} == {"books", "b1", "cs"}
    assert [i["depth"] for i in plan] == sorted((i["depth"] for i in plan), reverse=True)
    assert next(i for i in plan if i["id"] == "b1")["size"] == 3993


def test_plan_delete_refuses_the_mailbox():
    client, _ = logged_in()
    with pytest.raises(PermissionError, match="Mailbox"):
        plan_delete(tree_of(client), "mb")


# ---- 执行 ----------------------------------------------------------


def test_create_folder_refuses_a_mailbox_parent():
    client, seen = logged_in()
    with pytest.raises(PermissionError, match="Mailbox"):
        create_folder(client, "New", "mb")
    assert "POST" not in [r.method for r in seen]


def test_create_folder_refuses_a_document_parent_and_an_empty_name():
    client, seen = logged_in()
    with pytest.raises(LookupError, match="not a folder"):
        create_folder(client, "New", "b1")
    with pytest.raises(ValueError, match="must not be empty"):
        create_folder(client, "  ", "books")
    assert "POST" not in [r.method for r in seen]


def test_create_folder_posts_into_the_parent():
    client, seen = logged_in(stateful_handler())
    node = create_folder(client, "New", "books")
    assert node.name == "New"
    assert [i.id for i in client.list_tree().entries[1].children] == ["b1", "cs", node.id]


def test_rename_keeps_the_parent_and_sends_the_new_name():
    import json

    client, seen = logged_in(stateful_handler())
    rename(client, "b1", " Renamed ")
    put = next(r for r in seen if r.method == "PUT")
    assert json.loads(put.content) == {"documentId": "b1", "parentId": "books", "name": "Renamed"}


def test_rename_refuses_the_mailbox_and_an_empty_name():
    client, seen = logged_in()
    with pytest.raises(PermissionError, match="Mailbox"):
        rename(client, "mb-doc", "x")
    with pytest.raises(ValueError, match="must not be empty"):
        rename(client, "b1", "   ")
    assert "PUT" not in [r.method for r in seen]


def test_move_preserves_the_original_name():
    import json

    client, seen = logged_in(stateful_handler())
    move(client, "b1", "")
    put = next(r for r in seen if r.method == "PUT")
    # name 无条件覆写：只移动也必须把原名原样传回（REPORT §9.1）。
    assert json.loads(put.content) == {"documentId": "b1", "parentId": "", "name": "Book One"}
    assert [n.id for n in client.list_tree().entries] == ["mb", "books", "loose", "b1"]


def test_move_into_own_subtree_sends_nothing():
    client, seen = logged_in()
    with pytest.raises(ValueError, match="own subtree"):
        move(client, "books", "cs")
    assert "PUT" not in [r.method for r in seen]


def test_delete_subtree_deletes_deepest_first_and_rechecks():
    client, seen = logged_in(stateful_handler())
    plan = plan_delete(client.list_tree(), "books")
    result = delete_subtree(client, "books", [i["id"] for i in plan])
    assert result["deleted"][-1] == "books"
    assert result["residue"] == []
    assert [n.id for n in client.list_tree().entries] == ["mb", "loose"]


def test_delete_subtree_reports_residue_when_the_delete_did_not_stick():
    # 默认假云的 DELETE 是个空操作——正好用来证明复查真的在查。
    client, _ = logged_in()
    plan = plan_delete(client.list_tree(), "books")
    result = delete_subtree(client, "books", [i["id"] for i in plan])
    assert sorted(result["residue"]) == ["b1", "books", "cs"]


def test_delete_subtree_refuses_when_the_tree_changed_since_the_plan():
    # 计划与确认之间设备同步塞了个新文件进来——必须重新看一遍再确认。
    client, seen = logged_in(stateful_handler())
    with pytest.raises(TreeChanged) as exc:
        delete_subtree(client, "books", ["books", "b1"])  # 少了 cs
    assert exc.value.added == ["cs"]
    assert "DELETE" not in [r.method for r in seen]


def test_check_resurrection_reports_ids_that_are_back():
    client, _ = logged_in()
    back = check_resurrection(client, ["b1", "ghost"])
    assert [b["id"] for b in back] == ["b1"]
    assert back[0]["path"] == "Books"
    assert check_resurrection(client, ["ghost"]) == []
