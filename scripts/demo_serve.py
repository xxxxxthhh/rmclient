#!/usr/bin/env python3
"""离线 demo：完整的 rmclient Web，跑在一个内存假云上。全程零网络请求。

    uv run python scripts/demo_serve.py              # → http://127.0.0.1:8001
    uv run python scripts/demo_serve.py --port 9000

两个用途：给公开 README 截图（数据是公版书，绝不碰任何真实书库），以及让没有
rmfakecloud 的人零门槛试玩界面。

假云是 httpx.MockTransport：走的是和真部署**完全同一条**代码路径
（rmclient.api → manage → web），只是没有 socket。所以上传、移动、重命名、
删除计划、复活复查、重名检测、预览、PDF 导出全都是真的在跑，不是画出来的壳。

笔迹用 tests/fixtures.py 的 rm_page / rm_line 合成——那套 .rm v6 块序列拼装
只此一份，demo 借用它，不另抄一遍。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path

import httpx
import uvicorn
from fastapi import Request

# 仓库根进 sys.path：本脚本要借 tests/ 里的 .rm 构造器。可编辑安装下 .pth 已经
# 把仓库根放进去了，但那是构建后端的实现细节——不赌它，自己插一份。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rmscene import scene_items as si  # noqa: E402

from rmclient.api import RmClient  # noqa: E402
from rmclient.config import Credentials  # noqa: E402
from rmclient.journal import DeletionJournal  # noqa: E402
from tests.fixtures import rm_line, rm_page, rmdoc, tiny_epub, tiny_pdf  # noqa: E402

BASE_URL = "https://demo.invalid"          # 哨兵域名：真发出去也解析不了
TOKEN = "demo.header.payload.signature"

# 复活演示：删掉这一份，点「复活复查」时假设备把它原 UUID 推回来一次（REPORT §9.2）。
RESURRECTS = "n-sketchbook"


# ---- 合成笔迹 ------------------------------------------------------
#
# v6 坐标：x 以页面中线为 0（约 -700..700），y 从顶端往下（0..1872）。

def _curve(fn, t0: float, t1: float, steps: int) -> list[tuple[float, float]]:
    return [fn(t0 + (t1 - t0) * i / steps) for i in range(steps + 1)]


def _wobble(points, amp: float = 4.0) -> list[tuple[float, float]]:
    """给线条加一点确定性抖动：手画的东西不该是完美的函数图像。

    不用随机数——demo 数据要可复现，同一次截图两次跑出来得一模一样。
    """
    return [(x + amp * math.sin(i * 0.7), y + amp * math.cos(i * 1.1))
            for i, (x, y) in enumerate(points)]


def _pen(points, color=si.PenColor.BLACK, width=16):
    return rm_line(points, color=color, tool=si.Pen.FINELINER_1, width=width)


def _marker(points, color=si.PenColor.HIGHLIGHT):
    return rm_line(points, color=color, tool=si.Pen.HIGHLIGHTER_1, width=120)


def _sine(x: float) -> tuple[float, float]:
    """一段正弦：周期 440，振幅 200，基线 y=900。"""
    return x, 900 - 200 * math.sin((x + 400) * math.pi / 220)


def _calculus_page_one() -> bytes:
    """分隔线 + 坐标轴 + 正弦曲线 + 第一拱下的竖线阴影 + 荧光笔 + 一个 ∫。"""
    lines = [
        _pen(_wobble([(-560, 250), (0, 246), (500, 250)], 3), width=16),   # 页首分隔线
        _pen(_wobble([(-450, 900), (500, 900)], 2)),                       # x 轴
        _pen(_wobble([(-400, 620), (-400, 1160)], 2)),                     # y 轴
        _pen(_wobble(_curve(_sine, -400, 480, 88), 3),
             color=si.PenColor.BLUE, width=18),
    ]
    # 第一拱（x ∈ [-400, -180]）下方的竖线：积分面积的手绘表示
    for x in range(-380, -181, 24):
        lines.append(_pen([(x, _sine(x)[1]), (x, 900)], width=8))
    for x in (-180, 40, 260, 480):                                         # x 轴刻度
        lines.append(_pen([(x, 888), (x, 912)], width=10))
    lines.append(_marker(_curve(_sine, -350, -230, 12)))                   # 荧光笔盖住峰
    # ∫：一整个正弦周期竖着画就是积分号那条 S（半个周期只会得到一段弧）。
    lines.append(_pen(_wobble(_curve(
        lambda t: (-600 + 42 * math.sin(t), 600 + 58 * t), 0, 2 * math.pi, 44), 2), width=16))
    return rm_page(lines)


def _calculus_page_two() -> bytes:
    """单位圆 + 半径 + 内接直角三角形 + 圆心处的角弧。"""
    cx, cy, r = 0.0, 950.0, 260.0
    angle = math.radians(55)
    px, py = cx + r * math.cos(angle), cy - r * math.sin(angle)
    return rm_page([
        _pen(_wobble([(-560, 250), (0, 246), (500, 250)], 3), width=16),   # 页首分隔线
        _pen(_wobble(_curve(
            lambda t: (cx + r * math.cos(t), cy - r * math.sin(t)), 0, 2 * math.pi, 72), 3)),
        _pen(_wobble([(cx - 360, cy), (cx + 360, cy)], 2), width=10),      # x 轴
        _pen(_wobble([(cx, cy - 360), (cx, cy + 360)], 2), width=10),      # y 轴
        _pen([(cx, cy), (px, py)], color=si.PenColor.BLUE, width=18),     # 半径
        _pen([(px, py), (px, cy)], width=14),                             # 对边
        _pen([(cx, cy), (px, cy)], width=14),                             # 邻边
        _pen(_curve(lambda t: (cx + 70 * math.cos(t), cy - 70 * math.sin(t)), 0, angle, 16),
             color=si.PenColor.RED, width=12),                            # 角弧
    ])


def _journal_page() -> bytes:
    """标题横线 + 三个勾选框（两个打了勾）+ 几条横格。"""
    lines = [_pen([(-500, 260), (-40, 256)], width=22)]
    for i, ticked in enumerate((True, True, False)):
        top = 420 + i * 130
        lines.append(_pen([(-500, top), (-420, top), (-420, top + 80),
                           (-500, top + 80), (-500, top)], width=12))
        if ticked:
            lines.append(_pen([(-486, top + 44), (-458, top + 68), (-406, top + 12)],
                              color=si.PenColor.BLUE, width=20))
    for i in range(4):
        y = 900 + i * 110
        lines.append(_pen(_wobble([(-500, y), (0, y), (420, y)], 3), width=8))
    return rm_page(lines)


def _sketch_page() -> bytes:
    """山、太阳、地平线——一眼看得出是手画的，不是渲染的图形。"""
    return rm_page([
        _pen([(-520, 1100), (-260, 660), (-90, 900), (60, 700), (420, 1100)], width=20),
        # 雪线：两条山坡在 y=760 处的交点之间来回一趟，才像雪帽而不像划痕
        _pen([(-319, 760), (-290, 733), (-260, 766), (-224, 734), (-189, 760)], width=12),
        _pen(_wobble(_curve(lambda t: (330 + 110 * math.cos(t), 440 - 110 * math.sin(t)),
                            0, 2 * math.pi, 40), 4), color=si.PenColor.RED, width=16),
        _pen(_wobble([(-560, 1100), (520, 1100)], 3), width=14),          # 地平线
        _pen([(-380, 520), (-330, 490), (-280, 520)], width=10),          # 远处的鸟
        _pen([(-300, 560), (-250, 530), (-200, 560)], width=10),
    ])


def _letter_page() -> bytes:
    """信箱里那封信：几条横格加一笔签名。"""
    lines = [_pen([(-500, 300 + i * 120), (300 + i * 40, 296 + i * 120)], width=10)
             for i in range(4)]
    lines.append(_pen(_curve(
        lambda t: (-460 + 46 * t, 900 + 70 * math.sin(t * 1.9)), 0, 7.0, 40),
        color=si.PenColor.BLUE, width=16))
    return rm_page(lines)


# ---- demo 数据集 ---------------------------------------------------
#
# 全英文、全公版书，没有任何个人色彩：README 截图可以直接用。

def _notebook(pages: list[bytes], doc_id: str) -> bytes:
    return rmdoc({f"{doc_id}-p{i}": data for i, data in enumerate(pages)}, doc_id=doc_id)


def _seed() -> tuple[dict, dict[str, bytes]]:
    """返回 (树载荷, {doc_id: rmdoc 字节})。两者的 id 必须一一对上。"""
    exports = {
        "n-calculus": _notebook([_calculus_page_one(), _calculus_page_two()], "n-calculus"),
        "n-journal": _notebook([_journal_page()], "n-journal"),
        RESURRECTS: _notebook([_sketch_page()], RESURRECTS),
        "mb-letter": _notebook([_letter_page()], "mb-letter"),
    }
    # epub / pdf 的导出是整包，包里那份原件按扩展名取回（render.original_bytes）。
    for doc_id, kind in (
        ("b-odyssey", "epub"), ("b-moby", "epub"), ("b-frankenstein", "epub"),
        ("b-timemachine", "epub"), ("r-odyssey", "epub"),
        ("p-turing", "pdf"), ("p-shannon", "pdf"), ("mb-list", "pdf"), ("n-list", "pdf"),
    ):
        payload = tiny_epub("Public domain sample") if kind == "epub" else tiny_pdf()
        exports[doc_id] = rmdoc({}, file_type=kind, doc_id=doc_id, payload=payload)

    def doc(doc_id, name, kind, size, date):
        return {"id": doc_id, "name": name, "type": kind, "size": size,
                "lastModified": f"{date}T09:30:00Z"}

    payload = {
        "Entries": [
            # 锁定目录：整棵子树只读，任何写操作都会被拒（CLAUDE.md 纪律 1）。
            {"id": "mb", "name": "Mailbox", "isFolder": True,
             "lastModified": "2026-08-02T08:00:00Z", "children": [
                 doc("mb-letter", "Welcome Letter", "notebook", 24_118, "2026-08-02"),
                 doc("mb-list", "Reading List", "pdf", 41_902, "2026-07-28"),
             ]},
            {"id": "books", "name": "Books", "isFolder": True,
             "lastModified": "2026-08-20T10:00:00Z", "children": [
                 doc("b-odyssey", "The Odyssey", "epub", 812_446, "2026-08-11"),
                 doc("b-moby", "Moby-Dick", "epub", 1_403_881, "2026-08-14"),
                 doc("b-frankenstein", "Frankenstein", "epub", 496_204, "2026-08-06"),
                 {"id": "fiction", "name": "Fiction", "isFolder": True,
                  "lastModified": "2026-08-18T10:00:00Z", "children": [
                      doc("b-timemachine", "The Time Machine", "epub", 328_770, "2026-08-18"),
                  ]},
             ]},
            {"id": "papers", "name": "Papers", "isFolder": True,
             "lastModified": "2026-08-19T14:00:00Z", "children": [
                 doc("p-turing", "On Computable Numbers", "pdf", 2_207_339, "2026-08-09"),
                 doc("p-shannon", "A Mathematical Theory of Communication", "pdf",
                     1_884_015, "2026-08-19"),
             ]},
            {"id": "notes", "name": "Notes", "isFolder": True,
             "lastModified": "2026-08-25T19:00:00Z", "children": [
                 doc("n-calculus", "Calculus Notes", "notebook", 186_552, "2026-08-25"),
                 doc("n-journal", "Reading Journal", "notebook", 92_310, "2026-08-22"),
                 doc(RESURRECTS, "Sketchbook", "notebook", 74_881, "2026-08-24"),
                 doc("n-list", "Reading List", "pdf", 38_640, "2026-08-05"),
             ]},
            # 根级这份和 Books/ 里那份同名——重名检测报出来的就是它。
            doc("r-odyssey", "The Odyssey", "epub", 799_120, "2026-07-30"),
        ],
        "Trash": [
            doc("t-outline", "Draft Outline", "pdf", 22_004, "2026-06-12"),
            doc("t-syllabus", "Old Syllabus", "pdf", 61_777, "2026-05-30"),
        ],
    }
    return payload, exports


# ---- 内存假云 ------------------------------------------------------


class DemoCloud:
    """rmfakecloud 的最小行为模型：真改状态，只是没有 socket。

    只实现界面走得到的那几条路由，不是模拟器；不对的地方一律大声报错，
    别让 demo 里出现「看起来成功了其实什么都没发生」。
    """

    def __init__(self) -> None:
        self.state, self.exports = _seed()
        self.seen: list[httpx.Request] = []
        self._counter = 0
        self._pending_resurrection = False
        self._resurrection_left = True     # 只演一次：再删就是真删干净

    # -- 树操作 --

    def _locate(self, nodes: list, node_id: str, parent: list | None = None):
        for node in nodes:
            if node["id"] == node_id:
                return node, (parent if parent is not None else nodes)
            if "children" in node:
                hit = self._locate(node["children"], node_id, node["children"])
                if hit[0] is not None:
                    return hit
        return None, None

    def _container(self, parent_id: str) -> list:
        if not parent_id:
            return self.state["Entries"]
        node, _ = self._locate(self.state["Entries"], parent_id)
        if node is None or "children" not in node:
            raise LookupError(f"demo cloud: {parent_id} is not a folder")
        return node["children"]

    def _new_id(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}{self._counter}"

    # -- 路由 --

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path, method = request.url.path, request.method
        if path == "/ui/api/login":
            return httpx.Response(200, text=TOKEN)
        if path == "/ui/api/documents" and method == "GET":
            return httpx.Response(200, json=self.state)
        if path == "/ui/api/documents" and method == "PUT":
            return self._move(request)
        if path == "/ui/api/folders" and method == "POST":
            return self._create_folder(request)
        if path == "/ui/api/documents/upload" and method == "POST":
            return self._upload(request)
        if method == "DELETE":
            return self._delete(path.rsplit("/", 1)[1])
        if method == "GET" and request.url.params.get("type") == "rmdoc":
            return self._export(path.rsplit("/", 1)[1])
        return httpx.Response(404, json={"error": f"demo cloud: no route for {method} {path}"})

    def _move(self, request: httpx.Request) -> httpx.Response:
        """移动 + 重命名走同一条 PUT，name 无条件覆写（REPORT §9.1）。"""
        body = json.loads(request.content)
        node, siblings = self._locate(self.state["Entries"], body["documentId"])
        if node is None:
            return httpx.Response(404, json={"error": "demo cloud: no such document"})
        siblings.remove(node)
        node["name"] = body["name"]
        self._container(body["parentId"]).append(node)
        return httpx.Response(200, json={})

    def _create_folder(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        new = {"id": self._new_id("f"), "name": body["name"], "isFolder": True,
               "lastModified": "2026-08-29T12:00:00Z", "children": []}
        self._container(body["parentId"]).append(new)
        return httpx.Response(200, json={
            "ID": new["id"], "Type": "CollectionType", "Parent": body["parentId"],
            "Name": new["name"], "Version": 1})

    def _upload(self, request: httpx.Request) -> httpx.Response:
        """收下上传：进内存树，并且做成 rmdoc 存起来，之后下载/预览也能用。"""
        filename, data, parent = _parse_multipart(request)
        kind = filename.rsplit(".", 1)[-1].lower()
        name = filename.rsplit(".", 1)[0]           # 服务端 TrimSuffix，可见名不带扩展名
        doc_id = self._new_id("up")
        # .rmdoc 原样存（它本来就是个包）；epub/pdf 包一层，导出路径才走得通。
        self.exports[doc_id] = (
            data if kind == "rmdoc"
            else rmdoc({}, file_type=kind, doc_id=doc_id, payload=data))
        self._container(parent if parent != "root" else "").append({
            "id": doc_id,
            "name": name,
            # 刚上传的文档树上回显的 type 是**文件名**而不是类型（REPORT §4.1）——
            # 界面靠 display_type 把这个假值过滤掉，demo 照实复现，不粉饰。
            "type": name,
            "size": len(data),
            "lastModified": "2026-08-29T12:00:00Z",
        })
        return httpx.Response(200, json=[{
            "ID": doc_id, "Type": "DocumentType", "Parent": parent, "Name": name, "Version": 1}])

    def _delete(self, doc_id: str) -> httpx.Response:
        node, siblings = self._locate(self.state["Entries"], doc_id)
        if node is not None:
            siblings.remove(node)
        if doc_id == RESURRECTS and self._resurrection_left:
            self._pending_resurrection = True
        return httpx.Response(204)

    def _export(self, doc_id: str) -> httpx.Response:
        data = self.exports.get(doc_id)
        if data is None:
            return httpx.Response(404, json={"error": "demo cloud: nothing to export"})
        return httpx.Response(200, content=data)

    # -- 复活演示 --

    def resurrect_if_due(self) -> None:
        """假设备把删掉的那份原 UUID 推回来——只推一次，再删就真的删掉了。

        挂在 /api/resurrection 上而不是数树读了几次：那条路由就是为这件事存在的，
        用户点「复活复查」的那一刻正是该看见它的一刻，中间刷几次树都不影响。

        只演一次——不然「再删一次」这条正确的应对动作在 demo 里永远无解。
        """
        if not self._pending_resurrection:
            return
        self._pending_resurrection = False
        self._resurrection_left = False
        if self._locate(self.state["Entries"], RESURRECTS)[0] is not None:
            return
        notes = self._container("notes")
        notes.append({"id": RESURRECTS, "name": "Sketchbook", "type": "notebook",
                      "size": 74_881, "lastModified": "2026-08-29T12:05:00Z"})


def _parse_multipart(request: httpx.Request) -> tuple[str, bytes, str]:
    """从 multipart 体里取出 (文件名, 字节, 目标目录)。"""
    message = BytesParser(policy=email_policy).parsebytes(
        b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n"
        + request.content)
    filename, data, parent = "", b"", ""
    for part in message.iter_parts():
        field = part.get_param("name", header="content-disposition")
        if field == "file":
            filename, data = part.get_filename() or "", part.get_payload(decode=True) or b""
        elif field == "parent":
            parent = (part.get_payload(decode=True) or b"").decode()
    if not filename or not data:
        raise ValueError("demo cloud: multipart upload carried no file")
    return filename, data, parent


# ---- 接线 ----------------------------------------------------------


def build_client(cloud: DemoCloud) -> RmClient:
    """指向假云的真 RmClient：登录、读树、上传全走 rmclient.api 自己的代码。"""
    client = RmClient(
        Credentials("demo@example.com", "demo"),
        base_url=BASE_URL,
        transport=httpx.MockTransport(cloud.handle),
    )
    client.login()
    return client


def build_app(cloud: DemoCloud, journal_path: Path):
    """真 app + 依赖覆盖。凭据、真实云地址、仓库里的 var/ 一概不碰。"""
    from rmclient.web import app, get_client, get_journal

    client = build_client(cloud)
    journal = DeletionJournal(journal_path)

    def demo_client(request: Request) -> RmClient:
        # 复活就挂在这：/api/resurrection 是唯一该看见它的路由，而每条路由都要
        # 先拿 client。比数树读了几次稳——中间刷新几次、切个语言都不影响。
        if request.url.path == "/api/resurrection":
            cloud.resurrect_if_due()
        return client

    app.dependency_overrides[get_client] = demo_client
    app.dependency_overrides[get_journal] = lambda: journal
    return app


BANNER = """
rmclient demo — offline, in-memory, no network at all.

  open        http://127.0.0.1:{port}/          push page
              http://127.0.0.1:{port}/tree      document tree

  try         · Preview "Notes/Calculus Notes" and export it as PDF
              · Rename, move, or multi-select and batch-move anything
              · "Duplicate report" finds the two "The Odyssey" and the two
                "Reading List" (one of them inside the locked Mailbox)
              · Try to touch anything under Mailbox — every write is refused
              · Delete "Notes/Sketchbook", then hit "Resurrection re-check":
                the demo device pushes it back under its original UUID, once
              · Drop any .epub / .pdf onto the push page — it lands in the tree

  data        public-domain titles only; nothing here is anybody's real library
  state       in memory, thrown away when you stop this process
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="demo_serve", description="Run the rmclient web UI against an in-memory demo cloud")
    parser.add_argument("--port", type=int, default=8001, help="port to listen on (default 8001)")
    args = parser.parse_args(argv)

    # demo 自带锁定目录，不看使用者的环境；也绝不落盘到仓库的 var/。
    os.environ["RMCLIENT_LOCKED_FOLDERS"] = "Mailbox"
    journal = Path(tempfile.mkdtemp(prefix="rmclient-demo-")) / "deleted.json"

    app = build_app(DemoCloud(), journal)
    # flush：stdout 重定向到文件/管道时是块缓冲的，不刷用户先看到的是一片空白
    print(BANNER.format(port=args.port), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
