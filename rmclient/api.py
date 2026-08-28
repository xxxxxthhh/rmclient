"""rmfakecloud v0.0.31 UI API 客户端。契约与坑见 spike/REPORT.md。

    POST   /ui/api/login                      {"email","password"} -> 200, body = JWT 明文
    GET    /ui/api/documents                  -> {"Entries":[...],"Trash":[...]}
    POST   /ui/api/folders                    {"parentId","name"} -> Document（大写键）
    POST   /ui/api/documents/upload           multipart: file=<带扩展名>, parent=<uuid|root>
    PUT    /ui/api/documents                  {"documentId","parentId","name"} -> 移动/重命名
    GET    /ui/api/documents/{id}?type=rmdoc  -> zip 字节
    DELETE /ui/api/documents/{id}             -> 204，**硬删，不进回收站**
"""

from __future__ import annotations

from collections.abc import Collection, Iterable

import httpx

from .config import BASE_URL, Credentials, load_credentials
from .models import Node, Tree, find, mailbox_ids, parse_tree, parse_write_response, deepest_first
from .validate import validate

# 根级的 sentinel 两个端点不一样，别统一：folders 用空串，upload 用 "root"（REPORT §2）。
_ROOT_FOLDERS = ""
_ROOT_UPLOAD = "root"


class RmApiError(RuntimeError):
    """HTTP 错误。

    不支持的扩展名回的是 500 而不是 4xx，真正的原因在 body 的 error 字段
    （REPORT §4.3）——所以状态码区分不了「我传错了」和「服务端挂了」，必须看 error。
    """

    def __init__(self, method: str, url: str, status: int, error: str = "", body: str = ""):
        self.method, self.url, self.status, self.error, self.body = method, url, status, error, body
        detail = error or body or "(no body)"
        super().__init__(f"{method} {url} -> HTTP {status}: {detail}")


def _error_field(response: httpx.Response) -> str:
    """取 body 里的 error 字段。CF 的错误页是 HTML，json() 会抛，兜住。"""
    try:
        payload = response.json()
    except Exception:
        return ""
    return str(payload.get("error") or "") if isinstance(payload, dict) else ""


class RmClient:
    def __init__(
        self,
        credentials: Credentials | None = None,
        base_url: str = BASE_URL,
        *,
        transport: httpx.BaseTransport | None = None,
    ):
        self._creds = credentials or load_credentials()
        self._token: str | None = None
        self._client = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(120.0, connect=10.0),
            follow_redirects=False,
            transport=transport,
        )

    def __enter__(self) -> RmClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # ---- 底层 ------------------------------------------------------

    def login(self) -> None:
        r = self._client.post(
            "/ui/api/login", json={"email": self._creds.user, "password": self._creds.password}
        )
        if r.status_code != 200:
            # 绝不带上 body：登录成功时那个 body 就是 JWT 本身。
            raise RmApiError("POST", "/ui/api/login", r.status_code)
        self._token = r.text.strip()
        if not self._token:
            raise RuntimeError("login returned an empty token")

    def _request(self, method: str, url: str, **kw) -> httpx.Response:
        if not self._token:
            raise RuntimeError("not logged in: call login() first")
        # 认证只用 Authorization: Bearer——RM_HTTPS_COOKIE 下 cookie 带 Secure
        # 标记，某些路径不回传（REPORT §4.7）。token 不进 client.headers，免得
        # 被 repr / 日志顺手带出去。
        r = self._client.request(
            method, url, headers={"Authorization": f"Bearer {self._token}"}, **kw
        )
        if r.status_code >= 400:
            raise RmApiError(method, url, r.status_code, _error_field(r), r.text[:200])
        return r

    # ---- 读 --------------------------------------------------------

    def list_tree(self) -> Tree:
        return parse_tree(self._request("GET", "/ui/api/documents").json())

    def export_rmdoc(self, doc_id: str) -> bytes:
        """导出 zip（原始字节无损）。大文件可能撞 Cloudflare 100MB 边缘上限。"""
        return self._request("GET", f"/ui/api/documents/{doc_id}", params={"type": "rmdoc"}).content

    # ---- 写 --------------------------------------------------------

    def create_folder(self, name: str, parent: str = _ROOT_FOLDERS) -> Node:
        r = self._request("POST", "/ui/api/folders", json={"parentId": parent, "name": name})
        return parse_write_response(r.json())

    def upload(self, data: bytes, filename: str, parent: str = "") -> Node:
        """上传。filename 必须带正确扩展名——服务端只认后缀，不校验内容。

        这里是 CLI 与 Web 共用的唯一上路口，所以后缀 + 内容校验都在这做，
        没有 bypass 开关（纪律 5）。校验不过在本机就拒，一个请求都不发。

        可见名会被剥掉扩展名（TrimSuffix），所以 filename 传「书名.epub」。
        返回的 Document 没有 type（写响应不给 fileType）；树上刚上传文档的
        type 也不可信（REPORT §4.1），要准确类型读 export_rmdoc 的 .content。
        """
        validate(data, filename)
        r = self._request(
            "POST",
            "/ui/api/documents/upload",
            # content-type 服务端不看（REPORT §3.2），固定 octet-stream。
            files={"file": (filename, data, "application/octet-stream")},
            data={"parent": parent or _ROOT_UPLOAD},
        )
        return parse_write_response(r.json())

    def move(self, doc_id: str, parent_id: str = _ROOT_FOLDERS, name: str | None = None) -> None:
        """移动/重命名。parent_id 传空串即根级（REPORT §11 实测，回查树确认）。

        注意上传端点的根级 sentinel 是 "root"，这里是空串，两套写法别统一。

        name 无条件覆写：只想移动也必须把原名原样传回，漏传会把可见名置空
        （REPORT §9.1）。name=None 时先读树取原名，取不到就报错，绝不发空名。
        """
        if name is None:
            node = find(self.list_tree().entries, doc_id)
            if node is None:
                raise LookupError(f"{doc_id} not in tree: refusing to move without its name")
            name = node.name
        if not name:
            raise ValueError(f"refusing to move {doc_id} with an empty name")
        self._request(
            "PUT", "/ui/api/documents", json={"documentId": doc_id, "parentId": parent_id, "name": name}
        )

    def delete(self, doc_id: str, *, allowed_ids: Collection[str]) -> None:
        """硬删（不进回收站），且会同步删掉设备上的文件。

        只接受显式 UUID 白名单，绝不按名字匹配（REPORT §4.4）。
        注意复活竞态：设备端有本地变更的文档会被原 UUID 推回，删完要复查
        （REPORT §9.2）。
        """
        if doc_id not in allowed_ids:
            raise PermissionError(f"refusing to delete {doc_id}: not in the explicit allow-list")
        self._request("DELETE", f"/ui/api/documents/{doc_id}")

    def delete_many(
        self, ids: Iterable[str], *, allowed_ids: Collection[str], entries: Iterable[Node]
    ) -> list[str]:
        """按「先深后浅」批量删（HashTree.Remove 不级联，REPORT §4.5）。

        entries 是当前树的根级列表：用来定深度，同时断言没有一个 id 落在
        信箱子树里（CLAUDE.md 纪律 1）。全部检查通过后才发第一个请求。
        """
        ids = list(ids)
        entries = list(entries)
        if not_allowed := [i for i in ids if i not in allowed_ids]:
            raise PermissionError(f"refusing to delete, not in the explicit allow-list: {not_allowed}")
        locked = mailbox_ids(entries)
        if in_mailbox := [i for i in ids if i in locked]:
            raise PermissionError(f"refusing to touch the Mailbox subtree: {in_mailbox}")
        ordered = deepest_first(ids, entries)
        for doc_id in ordered:
            self.delete(doc_id, allowed_ids=allowed_ids)
        return ordered
