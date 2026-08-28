"""demo 的离线测试：数据集能被现有管线吃下、关键路由通、全程不出网。

demo 是给公开 README 截图和陌生人试玩用的门面，坏了不会有人在日常使用里发现——
所以这里把「树合法」「笔迹渲染得出来」「路由 200」钉死。
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from rmclient.models import Document, parse_tree, walk
from rmclient.render import original_bytes, page_to_svg, pages_to_pdf, parse_rmdoc
from tests.fixtures import tiny_epub, tiny_pdf

REPO = Path(__file__).resolve().parent.parent


def _load_demo():
    """scripts/ 不是包，按路径加载。"""
    spec = importlib.util.spec_from_file_location("demo_serve", REPO / "scripts" / "demo_serve.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("demo_serve", module)
    spec.loader.exec_module(module)
    return module


demo = _load_demo()


@pytest.fixture
def cloud():
    return demo.DemoCloud()


@pytest.fixture
def client(cloud, tmp_path, monkeypatch):
    """demo app + 临时记录文件。绝不写仓库里的 var/。"""
    monkeypatch.setenv("RMCLIENT_LOCKED_FOLDERS", "Mailbox")
    app = demo.build_app(cloud, tmp_path / "deleted.json")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# ---- 数据集 --------------------------------------------------------


def test_the_demo_tree_parses_with_the_real_model(cloud):
    tree = parse_tree(cloud.state)
    names = [n.name for n in tree.entries]
    assert names == ["Mailbox", "Books", "Papers", "Notes", "The Odyssey"]
    assert [n.name for n in tree.trash] == ["Draft Outline", "Old Syllabus"]
    # 每个节点都得有 id 和可见名，否则界面上会出现空行
    assert all(node.id and node.name for _, node in walk(tree.entries))


def test_every_document_in_the_tree_has_an_export(cloud):
    """预览/下载全靠 export：树上有而 exports 里没有的文档一点就 404。"""
    docs = [n.id for _, n in walk(parse_tree(cloud.state).entries) if isinstance(n, Document)]
    assert docs, "demo 树上应该有文档"
    assert not [d for d in docs if d not in cloud.exports]


def test_the_dataset_carries_no_personal_traces(cloud):
    """公开 README 截图用的数据：只准出现公版书和通用目录名。"""
    names = {n.name for _, n in walk(parse_tree(cloud.state).entries)}
    names |= {n.name for n in parse_tree(cloud.state).trash}
    assert names == {
        "Mailbox", "Welcome Letter", "Reading List",
        "Books", "The Odyssey", "Moby-Dick", "Frankenstein", "Fiction", "The Time Machine",
        "Papers", "On Computable Numbers", "A Mathematical Theory of Communication",
        "Notes", "Calculus Notes", "Reading Journal", "Sketchbook",
        "Draft Outline", "Old Syllabus",
    }, "公开截图数据集：改名字之前先确认没有真实书名混进来"
    assert all(name.isascii() for name in names)


def test_the_notebook_really_renders_strokes(cloud):
    """合成笔迹必须真解析得出笔画——能 200 但画的是白纸，截图就白给了。"""
    notebook = parse_rmdoc(cloud.exports["n-calculus"])
    assert notebook.file_type == "notebook" and len(notebook.pages) == 2
    assert all(page.strokes for page in notebook.pages)
    assert len(notebook.pages[0].strokes) > 10
    svg = page_to_svg(notebook.pages[0])
    assert svg.count("<polyline") == len(notebook.pages[0].strokes)
    # 荧光笔那一笔：render._stroke 的 opacity 分支只有它走得到
    assert "stroke-opacity" in svg
    assert pages_to_pdf(notebook.pages).startswith(b"%PDF")


@pytest.mark.parametrize("doc_id", ["n-calculus", "n-journal", demo.RESURRECTS, "mb-letter"])
def test_every_seeded_notebook_has_at_least_one_page_of_ink(cloud, doc_id):
    notebook = parse_rmdoc(cloud.exports[doc_id])
    assert notebook.file_type == "notebook"
    assert any(page.strokes for page in notebook.pages)


def test_seeded_books_come_back_as_their_original_file(cloud):
    """epub/pdf 的导出是整包，原件按扩展名从包里取（render.original_bytes）。"""
    assert original_bytes(cloud.exports["b-odyssey"])[1] == "epub"
    assert original_bytes(cloud.exports["p-turing"])[1] == "pdf"


def test_the_dataset_sets_up_the_features_it_means_to_show(client):
    groups = client.get("/api/duplicates").json()["groups"]
    assert {g["name"] for g in groups} == {"Reading List", "The Odyssey"}
    # 其中一组有一份在锁定目录里：报告要显示 🔒，且不给任何操作
    assert any(item["locked"] for g in groups for item in g["items"])
    assert [n["locked"] for n in client.get("/api/tree").json()["entries"]][0] is True


# ---- 路由 ----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/", "/tree", "/preview/n-calculus",
        "/api/tree", "/api/folders", "/api/duplicates", "/api/deleted",
        "/api/preview/n-calculus", "/api/preview/n-calculus/page/1",
        "/api/preview/n-calculus/pdf",
        "/api/download/b-odyssey", "/api/download/n-calculus?package=1",
        "/static/app.css", "/static/i18n.js",
    ],
)
def test_demo_routes_answer_200(client, path):
    assert client.get(path).status_code == 200


def test_uploading_lands_in_the_tree_and_stays_downloadable(client):
    r = client.post(
        "/api/upload",
        files={"file": ("Meditations.epub", tiny_epub(), "application/epub+zip")},
        data={"parent": "books"},
    )
    assert r.status_code == 200
    new_id = r.json()["id"]
    books = next(n for n in client.get("/api/tree").json()["entries"] if n["id"] == "books")
    fresh = next(n for n in books["children"] if n["id"] == new_id)
    assert fresh["name"] == "Meditations"          # 服务端 TrimSuffix
    # 刚上传的文档 type 回显文件名（REPORT §4.1）：demo 照实复现，展示层过滤掉
    assert fresh["type"] == ""
    assert client.get(f"/api/download/{new_id}").status_code == 200


def test_the_locked_folder_refuses_writes_but_allows_reading(client):
    assert client.post("/api/rename", data={"id": "mb-letter", "name": "x"}).status_code == 403
    assert client.post("/api/move", data={"id": "mb-letter", "parent": ""}).status_code == 403
    assert client.post("/api/delete/plan", data={"roots": ["mb"]}).status_code == 403
    assert client.post(
        "/api/upload", files={"file": ("x.pdf", tiny_pdf(), "x")}, data={"parent": "mb"}
    ).status_code == 403
    assert client.get("/api/preview/mb-letter").status_code == 200      # 只读放行


def test_rename_and_move_really_change_the_tree(client):
    assert client.post("/api/rename", data={"id": "b-moby", "name": "Moby Dick"}).status_code == 200
    assert client.post("/api/move", data={"id": "b-moby", "parent": "fiction"}).status_code == 200
    books = next(n for n in client.get("/api/tree").json()["entries"] if n["id"] == "books")
    fiction = next(n for n in books["children"] if n["id"] == "fiction")
    assert "Moby Dick" in [n["name"] for n in fiction["children"]]


def test_the_resurrection_case_fires_once_and_only_once(client):
    """删 → 树干净 → 点复活复查 → 原 UUID 回来；再删一次就真的干净了。"""
    def delete_sketchbook():
        plan = client.post("/api/delete/plan", data={"roots": [demo.RESURRECTS]}).json()
        assert plan["ids"] == [demo.RESURRECTS]
        r = client.post("/api/delete", data={"roots": [demo.RESURRECTS], "ids": plan["ids"]})
        assert r.status_code == 200 and r.json()["residue"] == []   # 立刻复查干净
        return r

    def on_tree() -> bool:
        notes = next(n for n in client.get("/api/tree").json()["entries"] if n["id"] == "notes")
        return demo.RESURRECTS in [n["id"] for n in notes["children"]]

    delete_sketchbook()
    assert not on_tree()                                    # 刷新树也看不见它
    assert client.get("/api/deleted").json()["records"][0]["name"] == "Sketchbook"
    back = client.post("/api/resurrection").json()
    assert [b["id"] for b in back["back"]] == [demo.RESURRECTS]
    assert on_tree()                                        # 被原 UUID 推回来了

    delete_sketchbook()
    assert client.post("/api/resurrection").json()["back"] == []
    assert not on_tree()


def test_creating_a_folder_works_and_shows_up_as_a_target(client):
    assert client.post("/api/folders", data={"name": "Essays", "parent": ""}).status_code == 200
    assert "Essays" in [f["path"] for f in client.get("/api/folders").json()["folders"]]


# ---- 入口 ----------------------------------------------------------


def test_the_readme_command_actually_starts(tmp_path):
    """按 README 写的那条命令跑真文件，而且从别的目录跑。

    上面的用例都是 importlib 直接加载模块，绕过了脚本自己的 import 路径——
    脚本导入链断了它们照样绿。这里跑的是真入口：--help 之前整个模块已经导完了。
    """
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "demo_serve.py"), "--help"],
        cwd=tmp_path, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "--port" in result.stdout and "8001" in result.stdout


# ---- 零网络 --------------------------------------------------------


def test_every_request_went_to_the_in_memory_cloud(client, cloud):
    """证据是正面的：所有流量都被假云捕获，且主机名只有那个哨兵域名。"""
    client.get("/api/tree")
    client.get("/api/preview/n-calculus")
    client.post("/api/upload", files={"file": ("A.pdf", tiny_pdf(), "x")}, data={"parent": ""})
    assert cloud.seen, "假云应该收到请求"
    assert {r.url.host for r in cloud.seen} == {"demo.invalid"}


def test_no_demo_path_ever_touches_the_real_transport(monkeypatch, cloud):
    """把真 transport 钉死：demo 全流程跑完还活着，就说明一个包都没发出去。

    不去 connect 一个解析不了的域名来「证明」——那本身就是一次 DNS 查询。
    """
    def forbidden(*args, **kwargs):
        raise AssertionError("demo 走到了真实网络传输层")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    client = demo.build_client(cloud)          # login 也在这条路上
    assert client.list_tree().entries
    assert client.export_rmdoc("n-calculus")
    client.upload(tiny_pdf(), "Probe.pdf", "")


def test_the_demo_never_reads_real_credentials(monkeypatch, cloud):
    """demo 起来不该碰凭据：读到就说明 RmClient 走了 load_credentials 那条路。"""
    import rmclient.api

    monkeypatch.setattr(rmclient.api, "load_credentials",
                        lambda: pytest.fail("demo 不该读凭据"))
    assert demo.build_client(cloud).list_tree().entries
