"""本地 Web：拖一本书进去就上传。单进程，无构建链。

    rmclient serve            # → http://127.0.0.1:8000

上传走的是和 CLI 完全同一条路径（push → api.upload → validate），Web 这层只负责
把结果翻译成 HTTP 状态码和页面提示。目录下拉框里没有信箱，服务端还会再查一次
（下拉框过滤只是展示，拦不住直接带 id 打过来的请求）。
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, Response

from .api import RmApiError, RmClient
from .journal import DeletionJournal
from .manage import (
    TreeChanged,
    check_resurrection,
    create_folder,
    delete_subtrees,
    move,
    plan_delete_many,
    rename,
)
from .models import Folder, PathError, Tree, find, mailbox_ids, walk
from .push import DuplicateName, push
from .render import Notebook, page_to_svg, pages_to_pdf, parse_rmdoc
from .validate import ValidationError

app = FastAPI(title="rmclient")

_PAGES = Path(__file__).resolve().parent / "pages"


def page(name: str) -> str:
    """每次请求重读一遍：改完 HTML 刷新页面就行，不用重启进程。"""
    return (_PAGES / name).read_text()

_client: RmClient | None = None


def get_client() -> RmClient:
    """惰性建连：import 这个模块不该去读凭据、更不该打云端（测试要能覆盖掉它）。"""
    global _client
    if _client is None:
        client = RmClient()
        client.login()
        _client = client
    return _client


def get_journal() -> DeletionJournal:
    """删除记录文件。测试覆盖掉它，绝不写到仓库里的 var/。"""
    return DeletionJournal()


def folder_options(tree: Tree) -> list[dict]:
    """可选目标目录（信箱整棵子树不出现在选项里）。"""
    options = [{"id": "", "path": "（根级）"}]
    options += sorted(
        (
            {"id": node.id, "path": "/".join(path + (node.name,))}
            for path, node in walk(tree.entries, skip_mailbox=True)
            if isinstance(node, Folder)
        ),
        key=lambda o: o["path"],
    )
    return options


def tree_json(tree: Tree) -> dict:
    """整棵树给页面用。locked = 信箱子树，页面据此标只读并且不给任何操作按钮。"""
    locked = mailbox_ids(tree.entries)

    def node_json(node) -> dict:
        base = {
            "id": node.id,
            "name": node.name,
            "parent": node.parent,
            "lastModified": node.last_modified,
            "locked": node.id in locked,
        }
        if isinstance(node, Folder):
            return base | {"kind": "folder", "children": [node_json(c) for c in node.children]}
        return base | {"kind": "doc", "type": node.type, "size": node.size}

    return {
        "entries": [node_json(n) for n in tree.entries],
        "trash": [node_json(n) for n in tree.trash],
    }


@app.get("/api/tree")
def api_tree(client: RmClient = Depends(get_client)) -> dict:
    return tree_json(client.list_tree())


def _manage(action) -> dict:
    """把策略层的拒绝翻译成 HTTP。信箱、空名、移进自己子孙都在这被挡住。"""
    try:
        return action()
    except PermissionError as exc:
        raise HTTPException(403, {"reason": "mailbox", "message": str(exc)}) from exc
    except (PathError, LookupError) as exc:
        raise HTTPException(404, {"reason": "not_found", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(400, {"reason": "invalid", "message": str(exc)}) from exc
    except RmApiError as exc:
        raise HTTPException(502, {"reason": "upstream", "message": str(exc)}) from exc


@app.post("/api/folders")
def api_create_folder(
    name: str = Form(...), parent: str = Form(""), client: RmClient = Depends(get_client)
) -> dict:
    node = _manage(lambda: create_folder(client, name, parent))
    return {"id": node.id, "name": node.name}


@app.post("/api/rename")
def api_rename(
    id: str = Form(...), name: str = Form(...), client: RmClient = Depends(get_client)
) -> dict:
    return {"id": id, "name": _manage(lambda: rename(client, id, name))}


@app.post("/api/move")
def api_move(
    id: str = Form(...), parent: str = Form(""), client: RmClient = Depends(get_client)
) -> dict:
    _manage(lambda: move(client, id, parent))
    return {"id": id, "parent": parent}


@app.post("/api/delete/plan")
def api_delete_plan(roots: list[str] = Form(...), client: RmClient = Depends(get_client)) -> dict:
    """这一刀会删掉的每一项，先深后浅。对话框必须把整棵子树摊给用户看。

    roots 是用户选中的若干项（单删就是 1 个）；父子同选会合并成一棵。
    """
    items = _manage(lambda: plan_delete_many(client.list_tree(), roots))
    return {"items": items, "ids": [i["id"] for i in items]}


@app.post("/api/delete")
def api_delete(
    roots: list[str] = Form(...),
    ids: list[str] = Form(...),
    client: RmClient = Depends(get_client),
    journal: DeletionJournal = Depends(get_journal),
) -> dict:
    """硬删整棵子树。ids 是用户在对话框里确认过的那份清单，只用来比对；
    真正的白名单是服务端此刻重算出来的（中间树变了就 409 让用户重看）。

    删成功后把每一项落到记录文件——复活要等设备同步一轮，那会儿页面早刷新过了。"""
    try:
        result = _manage(lambda: delete_subtrees(client, roots, ids))
        deleted = set(result["deleted"])
        journal.append(item for item in result["items"] if item["id"] in deleted)
        return {"deleted": result["deleted"], "residue": result["residue"]}
    except TreeChanged as exc:
        raise HTTPException(
            409,
            {"reason": "tree_changed", "message": str(exc), "added": exc.added, "removed": exc.removed},
        ) from exc


@app.get("/api/deleted")
def api_deleted(journal: DeletionJournal = Depends(get_journal)) -> dict:
    """待复查的删除记录。页面一加载就读它，UUID 不再只活在浏览器内存里。"""
    return {"records": journal.load()}


@app.post("/api/resurrection")
def api_resurrection(
    client: RmClient = Depends(get_client), journal: DeletionJournal = Depends(get_journal)
) -> dict:
    """复活复查：记录文件里的 UUID 有没有被设备端原样推回来（REPORT §9.2）。"""
    records = journal.load()
    return {"checked": len(records), "back": check_resurrection(client, [r["id"] for r in records])}


@app.post("/api/deleted/clear")
def api_deleted_clear(
    ids: list[str] | None = Form(None), journal: DeletionJournal = Depends(get_journal)
) -> dict:
    """清记录：给了 ids 就清这几条，没给就整个清空。清的只是本地记录，不碰云。"""
    return {"cleared": journal.remove(ids) if ids else journal.clear()}


# ---- 预览（全程只读）------------------------------------------------

# 导出一本要走网络 + 解析，翻页时不该每次重来。键里带 lastModified：设备上改过
# 再同步回来的笔记 UUID 不变，只有这个字段会动。
_CACHE_SIZE = 4
_notebooks: dict[tuple[str, str], Notebook] = {}


def _load(client: RmClient, doc_id: str) -> tuple[str, Notebook]:
    """返回 (可见名, 解析好的本子)。

    这是**唯一接受信箱 id 的路由族** —— 只读导出正是 SPEC M3 的验收路径，
    锁只针对写操作。这里从头到尾只有 GET。
    """
    node = find(client.list_tree().entries, doc_id)
    if node is None:
        raise HTTPException(404, {"reason": "not_found", "message": f"{doc_id} not in tree"})
    if isinstance(node, Folder):
        raise HTTPException(400, {"reason": "invalid", "message": "folders have no preview"})
    key = (doc_id, node.last_modified)
    notebook = _notebooks.get(key)
    if notebook is None:
        notebook = parse_rmdoc(client.export_rmdoc(doc_id))
        if len(_notebooks) >= _CACHE_SIZE:
            _notebooks.pop(next(iter(_notebooks)))
        _notebooks[key] = notebook
    return node.name, notebook


def _notebook_or_415(name: str, notebook: Notebook) -> Notebook:
    if notebook.file_type != "notebook":
        raise HTTPException(
            415,
            {
                "reason": "unsupported",
                "fileType": notebook.file_type,
                "message": f"「{name}」是 {notebook.file_type or '未知类型'}，只有原生笔记（notebook）能预览",
            },
        )
    return notebook


@app.get("/api/preview/{doc_id}")
def api_preview(doc_id: str, client: RmClient = Depends(get_client)) -> dict:
    name, notebook = _load(client, doc_id)
    _notebook_or_415(name, notebook)
    return {"id": doc_id, "name": name, "fileType": notebook.file_type,
            "pages": len(notebook.pages)}


@app.get("/api/preview/{doc_id}/page/{number}")
def api_preview_page(doc_id: str, number: int, client: RmClient = Depends(get_client)) -> Response:
    name, notebook = _load(client, doc_id)
    _notebook_or_415(name, notebook)
    if not 1 <= number <= len(notebook.pages):
        raise HTTPException(404, {"reason": "not_found", "message": f"没有第 {number} 页"})
    return Response(page_to_svg(notebook.pages[number - 1]), media_type="image/svg+xml")


@app.get("/api/preview/{doc_id}/pdf")
def api_preview_pdf(doc_id: str, client: RmClient = Depends(get_client)) -> Response:
    name, notebook = _load(client, doc_id)
    _notebook_or_415(name, notebook)
    filename = quote(f"{name}.pdf")
    return Response(
        pages_to_pdf(notebook.pages),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@app.get("/preview/{doc_id}", response_class=HTMLResponse)
def preview_page(doc_id: str) -> str:
    return page("preview.html")


@app.get("/tree", response_class=HTMLResponse)
def tree_page() -> str:
    return page("tree.html")


@app.get("/api/folders")
def api_folders(client: RmClient = Depends(get_client)) -> dict:
    return {"folders": folder_options(client.list_tree())}


@app.post("/api/upload")
async def api_upload(
    file: UploadFile = File(...),
    parent: str = Form(""),
    force: bool = Form(False),
    client: RmClient = Depends(get_client),
) -> dict:
    data = await file.read()
    try:
        node, existing = push(client, data, file.filename or "", parent_id=parent, force=force)
    except ValidationError as exc:
        raise HTTPException(400, {"reason": "invalid", "message": str(exc)}) from exc
    except PathError as exc:
        raise HTTPException(400, {"reason": "bad_target", "message": str(exc)}) from exc
    except PermissionError as exc:
        raise HTTPException(403, {"reason": "mailbox", "message": str(exc)}) from exc
    except DuplicateName as exc:
        raise HTTPException(
            409,
            {
                "reason": "duplicate",
                "message": str(exc),
                "existing": [{"id": d.id, "name": d.name, "size": d.size} for d in exc.existing],
            },
        ) from exc
    except RmApiError as exc:
        raise HTTPException(502, {"reason": "upstream", "message": str(exc)}) from exc
    return {
        "id": node.id,
        "name": node.name,
        "duplicates": len(existing),
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return page("push.html")
