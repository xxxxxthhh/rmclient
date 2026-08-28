"""Web 路由的离线测试：TestClient + 依赖覆盖，绝不建真实 RmClient。"""

import json

import pytest
from fastapi.testclient import TestClient

from rmclient.journal import DeletionJournal
from rmclient.web import app, get_client, get_journal
from tests.fixtures import logged_in, stateful_handler, tiny_epub, tiny_pdf


@pytest.fixture
def live_web(journal):
    """假云会记事的版本：用来测改完之后树真的变了。"""
    client, seen = logged_in(stateful_handler())
    app.dependency_overrides[get_client] = lambda: client
    app.dependency_overrides[get_journal] = lambda: journal
    with TestClient(app) as test_client:
        yield test_client, seen, client
    app.dependency_overrides.clear()


@pytest.fixture
def journal(tmp_path):
    """删除记录写到 tmp_path，绝不碰仓库里的 var/。"""
    return DeletionJournal(tmp_path / "deleted.json")


@pytest.fixture
def web(journal):
    """(TestClient, 假云捕获到的请求)。依赖覆盖掉 get_client，不读凭据不打云。"""
    client, seen = logged_in()
    app.dependency_overrides[get_client] = lambda: client
    app.dependency_overrides[get_journal] = lambda: journal
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


# ---- 删除 ----------------------------------------------------------


def test_delete_plan_lists_the_whole_subtree_deepest_first(web):
    r = web[0].post("/api/delete/plan", data={"id": "books"})
    assert r.status_code == 200
    plan = r.json()
    assert set(plan["ids"]) == {"books", "b1", "cs"}
    assert plan["ids"][-1] == "books"  # 父目录最后删
    assert {i["name"] for i in plan["items"]} == {"Books", "Book One", "CS"}


def test_delete_plan_refuses_the_mailbox(web):
    client, seen = web
    r = client.post("/api/delete/plan", data={"id": "mb"})
    assert r.status_code == 403 and r.json()["detail"]["reason"] == "mailbox"
    assert [x.method for x in seen] == ["GET"]


def test_delete_removes_the_subtree_and_rechecks(live_web):
    client, seen, api = live_web
    plan = client.post("/api/delete/plan", data={"id": "books"}).json()
    r = client.post("/api/delete", data={"id": "books", "ids": plan["ids"]})
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"][-1] == "books" and body["residue"] == []
    assert [x.url.path for x in seen if x.method == "DELETE"] == [
        f"/ui/api/documents/{i}" for i in body["deleted"]
    ]
    assert [n.id for n in api.list_tree().entries] == ["mb", "loose"]


def test_delete_reports_residue_when_the_delete_did_not_stick(web):
    # 默认假云的 DELETE 是空操作 —— 用来证明删完那次复查真的在查。
    client, _ = web
    plan = client.post("/api/delete/plan", data={"id": "books"}).json()
    body = client.post("/api/delete", data={"id": "books", "ids": plan["ids"]}).json()
    assert sorted(body["residue"]) == ["b1", "books", "cs"]


def test_delete_refuses_when_the_confirmed_list_no_longer_matches(web):
    # 计划与确认之间设备同步塞了个新文件进来：让用户重看一遍，别闷头删。
    client, seen = web
    r = client.post("/api/delete", data={"id": "books", "ids": ["books", "b1"]})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["reason"] == "tree_changed" and detail["added"] == ["cs"]
    assert "DELETE" not in [x.method for x in seen]


def test_delete_refuses_the_mailbox_subtree(web):
    client, seen = web
    r = client.post("/api/delete", data={"id": "mb", "ids": ["mb", "mb-doc"]})
    assert r.status_code == 403
    assert "DELETE" not in [x.method for x in seen]


# ---- 删除记录与复活复查 --------------------------------------------


def test_delete_writes_a_record_per_item(live_web, journal):
    client, _, _ = live_web
    plan = client.post("/api/delete/plan", data={"id": "books"}).json()
    client.post("/api/delete", data={"id": "books", "ids": plan["ids"]})
    records = journal.load()
    assert {(r["id"], r["name"], r["path"]) for r in records} == {
        ("books", "Books", ""),
        ("b1", "Book One", "Books"),
        ("cs", "CS", "Books"),
    }
    assert all(r["deleted_at"] for r in records)


def test_delete_records_nothing_when_it_was_refused(web, journal):
    client, _ = web
    client.post("/api/delete", data={"id": "mb", "ids": ["mb", "mb-doc"]})
    client.post("/api/delete", data={"id": "books", "ids": ["books"]})  # 清单对不上 → 409
    assert journal.load() == []


def test_api_deleted_serves_the_file(web, journal):
    journal.append([{"id": "x", "name": "Gone", "path": "Books", "kind": "doc"}])
    assert [r["id"] for r in web[0].get("/api/deleted").json()["records"]] == ["x"]


def test_resurrection_checks_the_ids_in_the_file(web, journal):
    # 页面不再传 UUID 进来——复查的对象就是文件里那份。
    journal.append([
        {"id": "b1", "name": "Book One", "path": "Books", "kind": "doc"},
        {"id": "ghost", "name": "Gone", "path": "", "kind": "doc"},
    ])
    body = web[0].post("/api/resurrection").json()
    assert body["checked"] == 2
    assert [b["id"] for b in body["back"]] == ["b1"]  # 只有它回到了树上
    assert body["back"][0]["path"] == "Books"


def test_resurrection_is_quiet_when_nothing_came_back(live_web, journal):
    client, _, _ = live_web
    plan = client.post("/api/delete/plan", data={"id": "books"}).json()
    client.post("/api/delete", data={"id": "books", "ids": plan["ids"]})
    body = client.post("/api/resurrection").json()
    assert (body["checked"], body["back"]) == (3, [])


def test_clear_removes_one_record(web, journal):
    journal.append([{"id": "a", "name": "A"}, {"id": "b", "name": "B"}])
    assert web[0].post("/api/deleted/clear", data={"ids": ["a"]}).json()["cleared"] == 1
    assert [r["id"] for r in journal.load()] == ["b"]


def test_clear_without_ids_empties_the_file(web, journal):
    journal.append([{"id": "a", "name": "A"}, {"id": "b", "name": "B"}])
    assert web[0].post("/api/deleted/clear").json()["cleared"] == 2
    assert journal.load() == []


def test_clearing_records_never_touches_the_cloud(web, journal):
    client, seen = web
    journal.append([{"id": "b1", "name": "Book One"}])
    client.post("/api/deleted/clear")
    assert seen == []


def test_tree_page_carries_the_pending_block_and_no_longer_posts_ids(web):
    html = web[0].get("/tree").text
    assert 'id="pending"' in html and "loadPending()" in html
    # 复查的 UUID 来自文件，页面不再自己攒一份
    assert "/api/resurrection', {method: 'POST'}" in html
