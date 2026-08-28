"""测试用的最小载荷 + 假云（httpx.MockTransport）。

不 import spike/ 的东西：测试不该绑在实验代码上。
"""

import io
import zipfile

import httpx

from rmclient.api import RmClient
from rmclient.config import Credentials

# ---- 载荷 ----------------------------------------------------------


def tiny_epub(title: str = "Tiny") -> bytes:
    """OCF 合规的最小 EPUB：mimetype 必须是第一个条目且不压缩。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        z.writestr("content.opf", f"<package><dc:title>{title}</dc:title></package>")
    return buf.getvalue()


def tiny_pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


def tiny_rmdoc() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("doc.content", "{}")
    return buf.getvalue()


# ---- 假云 ----------------------------------------------------------

TOKEN = "header.payload.signature"

# 一棵够用的树：信箱（含子树）、Books/（含一本书和空子目录 CS）、根级散文档、回收站。
TREE_PAYLOAD = {
    "Entries": [
        {
            "id": "mb",
            "name": "Mailbox",
            "isFolder": True,
            "children": [{"id": "mb-doc", "name": "letter", "type": "notebook", "size": 10}],
        },
        {
            "id": "books",
            "name": "Books",
            "isFolder": True,
            "children": [
                {"id": "b1", "name": "Book One", "type": "epub", "size": 3993},
                {"id": "cs", "name": "CS", "isFolder": True, "children": []},
            ],
        },
        {"id": "loose", "name": "Loose", "type": "pdf", "size": 601},
    ],
    "Trash": [{"id": "t1", "name": "old", "type": "pdf", "size": 1}],
}


def default_handler(request: httpx.Request) -> httpx.Response:
    path, method = request.url.path, request.method
    if path == "/ui/api/login":
        return httpx.Response(200, text=TOKEN)
    if path == "/ui/api/documents" and method == "GET":
        return httpx.Response(200, json=TREE_PAYLOAD)
    if path == "/ui/api/documents" and method == "PUT":
        return httpx.Response(200, json={})
    if path == "/ui/api/folders":
        return httpx.Response(
            200,
            json={"ID": "f1", "Type": "CollectionType", "Parent": "", "Name": "spike", "Version": 0},
        )
    if path == "/ui/api/documents/upload":
        return httpx.Response(
            200,
            json=[{"ID": "u1", "Type": "DocumentType", "Parent": "", "Name": "Book", "Version": 0}],
        )
    if method == "DELETE":
        return httpx.Response(204)
    if method == "GET":  # export
        return httpx.Response(200, content=b"PK\x03\x04zip-bytes")
    return httpx.Response(404, json={"error": "unexpected route"})


def make_client(handler=default_handler):
    """返回 (client, 捕获到的请求列表)。绝不打真实云。"""
    seen: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = RmClient(
        Credentials("user@example.test", "pw"),
        base_url="https://cloud.invalid",
        transport=httpx.MockTransport(capture),
    )
    return client, seen


def logged_in(handler=default_handler):
    client, seen = make_client(handler)
    client.login()
    seen.clear()
    return client, seen


def stateful_handler(payload: dict | None = None):
    """会记事的假云：DELETE 真删、PUT 真移、POST 真建。用来测删除/移动的回查路径。

    只实现测试用得到的那点行为，不是模拟器。
    """
    import copy

    state = copy.deepcopy(payload or TREE_PAYLOAD)
    counter = {"n": 0}

    def locate(nodes: list, node_id: str, parent: list | None = None):
        for node in nodes:
            if node["id"] == node_id:
                return node, (parent if parent is not None else nodes)
            if "children" in node:
                hit = locate(node["children"], node_id, node["children"])
                if hit[0] is not None:
                    return hit
        return None, None

    def container(parent_id: str) -> list:
        if not parent_id:
            return state["Entries"]
        node, _ = locate(state["Entries"], parent_id)
        return node["children"]

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        path, method = request.url.path, request.method
        if path == "/ui/api/login":
            return httpx.Response(200, text=TOKEN)
        if path == "/ui/api/documents" and method == "GET":
            return httpx.Response(200, json=state)
        if path == "/ui/api/documents" and method == "PUT":
            body = json.loads(request.content)
            node, siblings = locate(state["Entries"], body["documentId"])
            siblings.remove(node)
            node["name"] = body["name"]
            container(body["parentId"]).append(node)
            return httpx.Response(200, json={})
        if path == "/ui/api/folders":
            body = json.loads(request.content)
            counter["n"] += 1
            new = {"id": f"new{counter['n']}", "name": body["name"], "isFolder": True, "children": []}
            container(body["parentId"]).append(new)
            return httpx.Response(
                200,
                json={"ID": new["id"], "Type": "CollectionType", "Parent": body["parentId"],
                      "Name": new["name"], "Version": 0},
            )
        if method == "DELETE":
            node, siblings = locate(state["Entries"], path.rsplit("/", 1)[1])
            if node is not None:
                siblings.remove(node)
            return httpx.Response(204)
        return httpx.Response(404, json={"error": "unexpected route"})

    return handler
