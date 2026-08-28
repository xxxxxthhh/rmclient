"""Web 路由的离线测试：TestClient + 依赖覆盖，绝不建真实 RmClient。"""

import pytest
from fastapi.testclient import TestClient

from rmclient.web import app, get_client
from tests.fixtures import logged_in, tiny_epub, tiny_pdf


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
