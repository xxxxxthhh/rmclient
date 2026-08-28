"""Web 路由的离线测试：TestClient + 依赖覆盖，绝不建真实 RmClient。"""

import json

import pytest
from fastapi.testclient import TestClient

from rmclient.web import app, get_client
from tests.fixtures import logged_in, stateful_handler, tiny_epub, tiny_pdf


@pytest.fixture
def live_web():
    """假云会记事的版本：用来测改完之后树真的变了。"""
    client, seen = logged_in(stateful_handler())
    app.dependency_overrides[get_client] = lambda: client
    with TestClient(app) as test_client:
        yield test_client, seen, client
    app.dependency_overrides.clear()


@pytest.fixture
def web():
    """(TestClient, 假云捕获到的请求)。依赖覆盖掉 get_client，不读凭据不打云。"""
    client, seen = logged_in()
    app.dependency_overrides[get_client] = lambda: client
    with TestClient(app) as test_client:
        yield test_client, seen
    app.dependency_overrides.clear()


def test_index_serves_the_drop_page(web):
    r = web[0].get("/")
    assert r.status_code == 200 and "把 .epub" in r.text


def test_folder_options_exclude_the_mailbox(web):
    folders = web[0].get("/api/folders").json()["folders"]
    paths = [f["path"] for f in folders]
    assert paths == ["（根级）", "Books", "Books/CS"]
    assert all(f["id"] != "mb" for f in folders)


def test_upload_goes_through_the_same_path_as_the_cli(web):
    client, seen = web
    r = client.post(
        "/api/upload",
        files={"file": ("Fresh Book.epub", tiny_epub(), "application/epub+zip")},
        data={"parent": "cs"},
    )
    assert r.status_code == 200
    assert r.json() == {"id": "u1", "name": "Book", "duplicates": 0}
    assert seen[-1].url.path == "/ui/api/documents/upload"


def test_upload_refuses_invalid_content(web):
    client, seen = web
    r = client.post(
        "/api/upload", files={"file": ("Book.epub", tiny_pdf(), "application/epub+zip")}
    )
    assert r.status_code == 400
    assert r.json()["detail"]["reason"] == "invalid"
    assert "/ui/api/documents/upload" not in [x.url.path for x in seen]


def test_upload_refuses_a_bad_extension(web):
    r = web[0].post("/api/upload", files={"file": ("Book.txt", tiny_epub(), "text/plain")})
    assert r.status_code == 400
    assert "not in" in r.json()["detail"]["message"]


def test_upload_refuses_a_mailbox_parent_even_though_it_is_not_in_the_dropdown(web):
    # 下拉框过滤只是展示逻辑，拦不住直接带 id 打过来的请求。
    client, seen = web
    r = client.post(
        "/api/upload",
        files={"file": ("Book.epub", tiny_epub(), "application/epub+zip")},
        data={"parent": "mb"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["reason"] == "mailbox"
    assert "/ui/api/documents/upload" not in [x.url.path for x in seen]


def test_upload_reports_a_duplicate_as_409_with_the_existing_copies(web):
    client, seen = web
    r = client.post(
        "/api/upload",
        files={"file": ("Book One.epub", tiny_epub(), "application/epub+zip")},
        data={"parent": "books"},
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["reason"] == "duplicate"
    assert [e["id"] for e in detail["existing"]] == ["b1"]
    assert "/ui/api/documents/upload" not in [x.url.path for x in seen]


def test_upload_with_force_reports_the_duplicate_count(web):
    r = web[0].post(
        "/api/upload",
        files={"file": ("Book One.epub", tiny_epub(), "application/epub+zip")},
        data={"parent": "books", "force": "true"},
    )
    assert r.status_code == 200 and r.json()["duplicates"] == 1


def test_upload_refuses_an_unknown_parent(web):
    r = web[0].post(
        "/api/upload",
        files={"file": ("Book.epub", tiny_epub(), "application/epub+zip")},
        data={"parent": "ghost"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["reason"] == "bad_target"


# ---- 树浏览 --------------------------------------------------------


def test_tree_page_is_served_and_links_to_the_push_page(web):
    r = web[0].get("/tree")
    assert r.status_code == 200
    assert 'href="/"' in r.text and "文档树" in r.text


def test_push_page_links_to_the_tree(web):
    assert 'href="/tree"' in web[0].get("/").text


def test_api_tree_marks_the_whole_mailbox_subtree_locked(web):
    data = web[0].get("/api/tree").json()
    mailbox = next(n for n in data["entries"] if n["name"] == "Mailbox")
    assert mailbox["locked"] is True
    assert [c["locked"] for c in mailbox["children"]] == [True]
    books = next(n for n in data["entries"] if n["name"] == "Books")
    assert books["locked"] is False
    assert all(c["locked"] is False for c in books["children"])


def test_api_tree_carries_what_the_rows_display(web):
    data = web[0].get("/api/tree").json()
    books = next(n for n in data["entries"] if n["id"] == "books")
    doc = next(c for c in books["children"] if c["kind"] == "doc")
    assert (doc["type"], doc["size"], doc["parent"]) == ("epub", 3993, "books")
    assert next(c for c in books["children"] if c["kind"] == "folder")["children"] == []


def test_api_tree_includes_the_trash(web):
    assert [n["id"] for n in web[0].get("/api/tree").json()["trash"]] == ["t1"]


# ---- 管理操作：新建目录 / 重命名 / 移动 ----------------------------


def test_create_folder_lands_in_the_parent(live_web):
    client, _, api = live_web
    r = client.post("/api/folders", data={"name": " Notes ", "parent": "books"})
    assert r.status_code == 200 and r.json()["name"] == "Notes"
    books = next(n for n in api.list_tree().entries if n.id == "books")
    assert [c.name for c in books.children] == ["Book One", "CS", "Notes"]


def test_create_folder_refuses_the_mailbox_and_sends_no_write(web):
    client, seen = web
    r = client.post("/api/folders", data={"name": "X", "parent": "mb"})
    assert r.status_code == 403 and r.json()["detail"]["reason"] == "mailbox"
    assert [x.method for x in seen] == ["GET"]


def test_create_folder_refuses_an_empty_name(web):
    client, seen = web
    r = client.post("/api/folders", data={"name": "   ", "parent": "books"})
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "invalid"
    assert "POST" not in [x.method for x in seen]


def test_rename_keeps_the_parent(live_web):
    client, seen, api = live_web
    r = client.post("/api/rename", data={"id": "b1", "name": "Renamed"})
    assert r.status_code == 200 and r.json()["name"] == "Renamed"
    put = next(x for x in seen if x.method == "PUT")
    assert json.loads(put.content) == {"documentId": "b1", "parentId": "books", "name": "Renamed"}


def test_rename_refuses_the_mailbox_and_sends_no_write(web):
    client, seen = web
    r = client.post("/api/rename", data={"id": "mb-doc", "name": "X"})
    assert r.status_code == 403 and r.json()["detail"]["reason"] == "mailbox"
    assert "PUT" not in [x.method for x in seen]


def test_rename_refuses_an_empty_name(web):
    client, seen = web
    r = client.post("/api/rename", data={"id": "b1", "name": " "})
    assert r.status_code == 400
    assert "PUT" not in [x.method for x in seen]


def test_move_preserves_the_original_name(live_web):
    client, seen, api = live_web
    r = client.post("/api/move", data={"id": "b1", "parent": ""})
    assert r.status_code == 200
    put = next(x for x in seen if x.method == "PUT")
    assert json.loads(put.content) == {"documentId": "b1", "parentId": "", "name": "Book One"}
    assert [n.id for n in api.list_tree().entries] == ["mb", "books", "loose", "b1"]


def test_move_refuses_a_mailbox_target_even_though_it_is_not_in_the_picker(web):
    client, seen = web
    r = client.post("/api/move", data={"id": "b1", "parent": "mb"})
    assert r.status_code == 403 and r.json()["detail"]["reason"] == "mailbox"
    assert "PUT" not in [x.method for x in seen]


def test_move_refuses_a_document_from_the_mailbox(web):
    client, seen = web
    r = client.post("/api/move", data={"id": "mb-doc", "parent": "books"})
    assert r.status_code == 403
    assert "PUT" not in [x.method for x in seen]


def test_move_refuses_a_folder_into_its_own_subtree(web):
    client, seen = web
    r = client.post("/api/move", data={"id": "books", "parent": "cs"})
    assert r.status_code == 400 and "own subtree" in r.json()["detail"]["message"]
    assert "PUT" not in [x.method for x in seen]


def test_move_refuses_an_unknown_id(web):
    client, seen = web
    r = client.post("/api/move", data={"id": "ghost", "parent": "books"})
    assert r.status_code == 404
    assert "PUT" not in [x.method for x in seen]
