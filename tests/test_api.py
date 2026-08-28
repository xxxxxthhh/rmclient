"""api 的离线测试：用 httpx.MockTransport 钉住线上契约的形状，不打真实 API。

M0 阶段对生产云只允许只读，所以 upload/move/delete 的唯一正确性证据就是这里。
断言到方法 + URL + 字段名 + 根级 sentinel 这一层。
"""

import json

import httpx
import pytest

from rmclient.api import RmApiError
from rmclient.models import Document, Folder
from rmclient.validate import ValidationError
from tests.fixtures import (
    TOKEN,
    default_handler,
    logged_in,
    make_client,
    tiny_epub,
    tiny_pdf,
    tiny_rmdoc,
)

# ---- 登录与认证 ----------------------------------------------------


def test_login_posts_email_and_password():
    client, seen = make_client(default_handler)
    client.login()
    assert (seen[0].method, seen[0].url.path) == ("POST", "/ui/api/login")
    assert json.loads(seen[0].content) == {"email": "user@example.test", "password": "pw"}


def test_login_failure_never_leaks_the_body():
    # 登录成功时 body 就是 JWT 本身，所以失败路径也一律不带 body。
    secret = "a-jwt-shaped-secret"
    client, _ = make_client(lambda r: httpx.Response(401, text=secret))
    with pytest.raises(RmApiError) as exc:
        client.login()
    assert secret not in str(exc.value)


def test_requests_carry_bearer_header_not_cookies():
    client, seen = logged_in()
    client.list_tree()
    assert seen[0].headers["Authorization"] == f"Bearer {TOKEN}"
    assert "Cookie" not in seen[0].headers


def test_calls_before_login_raise():
    client, seen = make_client(default_handler)
    with pytest.raises(RuntimeError, match="not logged in"):
        client.list_tree()
    assert seen == []


# ---- 读 ------------------------------------------------------------


def test_list_tree_parses_entries_and_trash():
    client, seen = logged_in()
    tree = client.list_tree()
    assert (seen[0].method, seen[0].url.path) == ("GET", "/ui/api/documents")
    assert [n.id for n in tree.entries] == ["mb", "books", "loose"]
    assert [n.id for n in tree.trash] == ["t1"]


def test_export_rmdoc_hits_the_type_query_and_returns_bytes():
    client, seen = logged_in()
    assert client.export_rmdoc("b1") == b"PK\x03\x04zip-bytes"
    assert seen[0].url.path == "/ui/api/documents/b1"
    assert seen[0].url.params["type"] == "rmdoc"


# ---- 建目录 / 上传 -------------------------------------------------


def test_create_folder_root_sentinel_is_empty_string():
    client, seen = logged_in()
    node = client.create_folder("spike")
    assert (seen[0].method, seen[0].url.path) == ("POST", "/ui/api/folders")
    assert json.loads(seen[0].content) == {"parentId": "", "name": "spike"}
    assert isinstance(node, Folder) and node.id == "f1"


def test_upload_multipart_field_names_and_root_sentinel():
    client, seen = logged_in()
    node = client.upload(tiny_epub(), "Book One.epub")
    body = seen[0].content
    assert seen[0].url.path == "/ui/api/documents/upload"
    assert b'name="file"' in body and b'filename="Book One.epub"' in body
    # upload 的根级 sentinel 是 "root"，与 folders 的空串不同——别统一。
    assert b'name="parent"' in body and b"root" in body
    assert isinstance(node, Document) and node.id == "u1"


def test_upload_into_a_folder_passes_the_uuid():
    client, seen = logged_in()
    client.upload(tiny_epub(), "Book.epub", parent="f1")
    assert b"f1" in seen[0].content


def test_upload_rejects_bad_extension_before_any_request():
    # 服务端只认后缀且不校验内容，传错会安静地把书弄坏在设备端。
    client, seen = logged_in()
    with pytest.raises(ValidationError, match="not in"):
        client.upload(tiny_epub(), "Book One.txt")
    assert seen == []


def test_upload_accepts_the_verified_whitelist():
    client, _ = logged_in()
    for data, name in ((tiny_pdf(), "a.pdf"), (tiny_epub(), "b.epub"), (tiny_rmdoc(), "c.rmdoc")):
        client.upload(data, name)


def test_upload_refuses_an_uppercase_extension():
    # 大写后缀的服务端分派行为未验证（REPORT §3.1 只测过小写）——本机拒掉，
    # 别赌一个 500 或者一本在设备端安静坏掉的书。
    client, seen = logged_in()
    with pytest.raises(ValidationError, match="not in"):
        client.upload(tiny_pdf(), "Book.PDF")
    assert seen == []


def test_upload_refuses_content_that_contradicts_the_extension():
    # 上传是 CLI 与 Web 共用的唯一上路口，内容校验就长在这，没有 bypass。
    client, seen = logged_in()
    with pytest.raises(ValidationError, match="not a valid EPUB"):
        client.upload(tiny_pdf(), "Book.epub")
    assert seen == []


# ---- 错误处理 ------------------------------------------------------


def test_error_field_is_parsed_from_a_500_body():
    # 不支持的扩展名回 500 而不是 4xx，原因只在 body 的 error 字段。
    def handler(request):
        if request.url.path == "/ui/api/login":
            return httpx.Response(200, text=TOKEN)
        return httpx.Response(500, json={"error": "unsupported extension: .txt"})

    client, _ = logged_in(handler)
    with pytest.raises(RmApiError) as exc:
        client.list_tree()
    assert exc.value.status == 500
    assert exc.value.error == "unsupported extension: .txt"


def test_non_json_error_page_does_not_crash_the_parser():
    # Cloudflare 边缘（比如撞 100MB 上限）回的是 HTML，不是 JSON。
    def handler(request):
        if request.url.path == "/ui/api/login":
            return httpx.Response(200, text=TOKEN)
        return httpx.Response(413, html="<html><title>413 Payload Too Large</title></html>")

    client, _ = logged_in(handler)
    with pytest.raises(RmApiError) as exc:
        client.export_rmdoc("b1")
    assert exc.value.error == ""
    assert "413" in str(exc.value)


# ---- 移动：原名必须回传 --------------------------------------------


def test_move_without_name_looks_up_the_original():
    client, seen = logged_in()
    client.move("b1", "mb-target-not-used")
    # 先读树取原名，再 PUT。
    assert [(r.method, r.url.path) for r in seen] == [
        ("GET", "/ui/api/documents"),
        ("PUT", "/ui/api/documents"),
    ]
    assert json.loads(seen[1].content) == {
        "documentId": "b1",
        "parentId": "mb-target-not-used",
        "name": "Book One",
    }


def test_move_reads_the_tree_even_with_an_explicit_name():
    # 读树是为了信箱断言：默认路径必须有保护，不能只靠调用方自觉。
    client, seen = logged_in()
    client.move("b1", "", name="Renamed")
    assert [r.method for r in seen] == ["GET", "PUT"]
    assert json.loads(seen[1].content) == {"documentId": "b1", "parentId": "", "name": "Renamed"}


def test_move_with_a_fresh_tree_in_hand_skips_the_extra_read():
    client, seen = logged_in()
    entries = client.list_tree().entries
    seen.clear()
    client.move("b1", "cs", name="Book One", entries=entries)
    assert [r.method for r in seen] == ["PUT"]


def test_move_refuses_when_the_original_name_is_unknown():
    # name 无条件覆写：漏传会把可见名置空，宁可报错也不发空名。
    client, seen = logged_in()
    with pytest.raises(LookupError):
        client.move("ghost", "books")
    assert [r.method for r in seen] == ["GET"]


def test_move_refuses_an_empty_name():
    client, seen = logged_in()
    with pytest.raises(ValueError, match="empty name"):
        client.move("b1", "books", name="")
    assert "PUT" not in [r.method for r in seen]


def test_move_refuses_a_document_inside_the_mailbox():
    client, seen = logged_in()
    with pytest.raises(PermissionError, match="Mailbox"):
        client.move("mb-doc", "books")
    assert "PUT" not in [r.method for r in seen]


def test_move_refuses_a_mailbox_target():
    client, seen = logged_in()
    with pytest.raises(PermissionError, match="Mailbox"):
        client.move("b1", "mb")
    assert "PUT" not in [r.method for r in seen]


# ---- 删除：白名单 + 先深后浅 + 信箱 --------------------------------


def test_delete_requires_the_id_to_be_whitelisted():
    client, seen = logged_in()
    with pytest.raises(PermissionError, match="allow-list"):
        client.delete("b1", allowed_ids={"other"})
    assert seen == []


def test_delete_sends_the_request_for_a_whitelisted_id():
    client, seen = logged_in()
    client.delete("b1", allowed_ids={"b1"})
    assert (seen[-1].method, seen[-1].url.path) == ("DELETE", "/ui/api/documents/b1")


def test_delete_refuses_a_mailbox_id_even_when_whitelisted():
    # 白名单是调用方的显式意图，信箱是绝对禁区：两道闸都得过。
    client, seen = logged_in()
    with pytest.raises(PermissionError, match="Mailbox"):
        client.delete("mb-doc", allowed_ids={"mb-doc"})
    assert "DELETE" not in [r.method for r in seen]


def test_delete_many_goes_deepest_first():
    client, seen = logged_in()
    tree = client.list_tree()
    seen.clear()
    ordered = client.delete_many(["books", "b1"], allowed_ids={"books", "b1"}, entries=tree.entries)
    assert ordered == ["b1", "books"]
    # 那棵新鲜的树往下传，不是每个 id 各读一次
    assert [r.url.path for r in seen] == ["/ui/api/documents/b1", "/ui/api/documents/books"]


def test_delete_many_refuses_the_mailbox_subtree_before_sending_anything():
    client, seen = logged_in()
    tree = client.list_tree()
    seen.clear()
    with pytest.raises(PermissionError, match="Mailbox"):
        client.delete_many(["b1", "mb-doc"], allowed_ids={"b1", "mb-doc"}, entries=tree.entries)
    assert seen == []


def test_delete_many_checks_the_whitelist_before_sending_anything():
    client, seen = logged_in()
    tree = client.list_tree()
    seen.clear()
    with pytest.raises(PermissionError, match="allow-list"):
        client.delete_many(["b1", "books"], allowed_ids={"b1"}, entries=tree.entries)
    assert seen == []
