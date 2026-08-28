"""push 层的离线测试：目标校验、重名检测、force。不打真实云。"""

import pytest

from rmclient.models import PathError
from rmclient.push import DuplicateName, check_target, find_duplicates, push, visible_name
from tests.fixtures import logged_in, tiny_epub


def test_visible_name_strips_the_extension_and_directories():
    # 服务端存的可见名是文件名去后缀（TrimSuffix，REPORT §4.6）。
    assert visible_name("/tmp/Book One.epub") == "Book One"
    assert visible_name("Paper.pdf") == "Paper"


def test_check_target_refuses_the_mailbox_subtree():
    client, _ = logged_in()
    tree = client.list_tree()
    with pytest.raises(PermissionError, match="Mailbox"):
        check_target(tree, "mb")
    with pytest.raises(PermissionError, match="Mailbox"):
        check_target(tree, "mb-doc")


def test_check_target_refuses_a_document_or_unknown_id():
    client, _ = logged_in()
    tree = client.list_tree()
    with pytest.raises(PathError, match="not a folder"):
        check_target(tree, "loose")
    with pytest.raises(PathError, match="not in tree"):
        check_target(tree, "ghost")
    check_target(tree, "")  # 根级永远合法


def test_find_duplicates_matches_the_visible_name():
    client, _ = logged_in()
    tree = client.list_tree()
    assert [d.id for d in find_duplicates(tree, "books", "Book One")] == ["b1"]
    assert find_duplicates(tree, "books", "Book One.epub") == []  # 比的是可见名，不是文件名
    assert find_duplicates(tree, "", "Book One") == []  # 只看目标目录那一层


def test_push_refuses_a_duplicate_without_force():
    # 服务端不覆盖不去重（REPORT §10），所以重名必须用户显式确认。
    client, seen = logged_in()
    with pytest.raises(DuplicateName) as exc:
        push(client, tiny_epub(), "Book One.epub", parent_id="books")
    assert [d.id for d in exc.value.existing] == ["b1"]
    assert [r.method for r in seen] == ["GET"]  # 只读了树，没上传


def test_push_with_force_uploads_and_reports_the_existing_copies():
    client, seen = logged_in()
    node, existing = push(client, tiny_epub(), "Book One.epub", parent_id="books", force=True)
    assert node.id == "u1"
    assert [d.id for d in existing] == ["b1"]
    assert [r.url.path for r in seen] == ["/ui/api/documents", "/ui/api/documents/upload"]


def test_push_to_a_clean_target_uploads():
    client, seen = logged_in()
    node, existing = push(client, tiny_epub(), "Fresh Book.epub", parent_id="cs")
    assert (node.id, existing) == ("u1", [])
    assert b"cs" in seen[-1].content


def test_push_into_the_mailbox_never_reaches_the_upload():
    client, seen = logged_in()
    with pytest.raises(PermissionError, match="Mailbox"):
        push(client, tiny_epub(), "Book.epub", parent_id="mb")
    assert [r.method for r in seen] == ["GET"]
