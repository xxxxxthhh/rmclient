"""笔记渲染：rmdoc → 页 → SVG / PDF。

只求人眼能辨认，不追求像素级还原：笔画按折线画，粗细取每笔各点宽度的均值
（v6 里 Point.width 是真实宽度的 4 倍，见 rmscene 的 point_from_stream），
橡皮擦笔画直接跳过，荧光笔加透明度。

类型判断以 rmdoc 里的 `.content` 为准 —— 树上的 `type` 对刚上传的文档不可信
（REPORT §4.1）。
"""

from __future__ import annotations

import json
import logging
import zipfile
import zlib
from dataclasses import dataclass, field
from io import BytesIO

from rmscene import read_tree
from rmscene import scene_items as si

# rmscene 0.8 读现在的固件文件会稳定抱怨「有数据没读完」——笔画照样解析得出来，
# 属预期噪音，别刷满终端。
logging.getLogger("rmscene").setLevel(logging.ERROR)

# reMarkable 2 屏幕：1404×1872。v6 坐标里 x 以页面中线为 0，y 从顶端往下。
PAGE_WIDTH = 1404
PAGE_HEIGHT = 1872
X_OFFSET = PAGE_WIDTH / 2

_COLORS = {
    si.PenColor.BLACK: "#000000",
    si.PenColor.GRAY: "#808080",
    si.PenColor.GRAY_OVERLAP: "#808080",
    si.PenColor.WHITE: "#ffffff",
    si.PenColor.YELLOW: "#f5c518",
    si.PenColor.GREEN: "#3aa757",
    si.PenColor.GREEN_2: "#3aa757",
    si.PenColor.PINK: "#e06c9f",
    si.PenColor.BLUE: "#2b5fd9",
    si.PenColor.RED: "#d63b3b",
    si.PenColor.CYAN: "#31b0c6",
    si.PenColor.HIGHLIGHT: "#f5e050",
}
_ERASERS = {si.Pen.ERASER, si.Pen.ERASER_AREA}


@dataclass
class Stroke:
    points: list[tuple[float, float]]
    color: str = "#000000"
    width: float = 2.0
    opacity: float = 1.0


@dataclass
class Page:
    strokes: list[Stroke] = field(default_factory=list)
    height: float = PAGE_HEIGHT
    note: str = ""  # 这一页没解析出来时给人看的说明


@dataclass
class Notebook:
    file_type: str
    pages: list[Page] = field(default_factory=list)


# ---- rmdoc 解析 ----------------------------------------------------


def rmdoc_content(data: bytes) -> dict:
    """rmdoc 里的 `.content`：类型与页序的唯一可信来源。"""
    with zipfile.ZipFile(BytesIO(data)) as z:
        for name in z.namelist():
            if name.endswith(".content"):
                return json.loads(z.read(name))
    raise ValueError("no .content in this rmdoc")


def original_bytes(data: bytes) -> tuple[bytes, str]:
    """原件取回：epub/pdf 从包里取原字节，其余（notebook 等）整包回 .rmdoc。

    按**扩展名**匹配 zip 成员——包里的文件名是 UUID，不是可见名。声明了 epub/pdf
    但包里找不到对应成员时退回整包，不报错：拿到手的总比 500 强。
    """
    file_type = (rmdoc_content(data).get("fileType") or "").lower()
    if file_type in ("epub", "pdf"):
        with zipfile.ZipFile(BytesIO(data)) as z:
            for name in z.namelist():
                if name.lower().endswith("." + file_type):
                    return z.read(name), file_type
    return data, "rmdoc"


def parse_rmdoc(data: bytes) -> Notebook:
    """解析整本。非 notebook 返回空页列表，由调用方给「不支持预览」。"""
    content = rmdoc_content(data)
    file_type = content.get("fileType") or ""
    if file_type != "notebook":
        return Notebook(file_type=file_type)

    with zipfile.ZipFile(BytesIO(data)) as z:
        blobs = {name.rsplit("/", 1)[-1][: -len(".rm")]: name
                 for name in z.namelist() if name.endswith(".rm")}
        pages = []
        for page_id in _page_order(content, blobs):
            name = blobs.get(page_id)
            if name is None:
                pages.append(Page(note=f"no .rm for this page in the rmdoc ({page_id[:8]})"))
                continue
            pages.append(_page_from_rm(z.read(name)))
    return Notebook(file_type=file_type, pages=pages)


def _page_order(content: dict, blobs: dict[str, str]) -> list[str]:
    """页序取 `.content` 的 cPages.pages，删掉的页跳过；没有就退回 zip 里的顺序。"""
    listed = (content.get("cPages") or {}).get("pages") or content.get("pages") or []
    order = [
        p.get("id") if isinstance(p, dict) else p
        for p in listed
        if not (isinstance(p, dict) and "deleted" in p)
    ]
    order = [p for p in order if p]
    return order or sorted(blobs)


def _page_from_rm(data: bytes) -> Page:
    """一页解析不动不该拖垮整本预览——就地降级成一句说明。"""
    try:
        tree = read_tree(BytesIO(data))
    except Exception as exc:
        return Page(note=f"this page failed to parse: {type(exc).__name__}: {exc}")

    strokes = [s for line in _lines(tree.root) if (s := _stroke(line))]
    bottom = max((y for s in strokes for _, y in s.points), default=0.0)
    return Page(strokes=strokes, height=max(PAGE_HEIGHT, bottom + 40))


def _lines(group) -> list[si.Line]:
    out: list[si.Line] = []
    for child in group.children.values():
        if isinstance(child, si.Group):
            out += _lines(child)
        elif isinstance(child, si.Line):
            out.append(child)
    return out


def _stroke(line: si.Line) -> Stroke | None:
    if line.tool in _ERASERS or not line.points:
        return None
    highlighter = si.Pen.is_highlighter(line.tool)
    if line.color_rgba:
        r, g, b, _ = line.color_rgba
        color = f"#{r:02x}{g:02x}{b:02x}"
    else:
        color = _COLORS.get(line.color, "#000000")
    # v6 存的 width 是真实宽度的 4 倍。
    width = sum(p.width for p in line.points) / len(line.points) / 4
    return Stroke(
        points=[(p.x + X_OFFSET, p.y) for p in line.points],
        color=color,
        width=max(1.0, width),
        opacity=0.35 if highlighter else 1.0,
    )


# ---- SVG -----------------------------------------------------------


def page_to_svg(page: Page) -> str:
    """一页一个 SVG。空页也要是合法的空白页，不是退化的 viewBox。"""
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {PAGE_WIDTH} {page.height:.0f}" '
        f'width="{PAGE_WIDTH}" height="{page.height:.0f}">',
        f'<rect width="100%" height="100%" fill="#ffffff"/>',
    ]
    for stroke in page.strokes:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in stroke.points)
        opacity = "" if stroke.opacity >= 1 else f' stroke-opacity="{stroke.opacity}"'
        parts.append(
            f'<polyline points="{pts}" fill="none" stroke="{stroke.color}" '
            f'stroke-width="{stroke.width:.1f}" stroke-linecap="round" '
            f'stroke-linejoin="round"{opacity}/>'
        )
    if page.note:
        parts.append(
            f'<text x="{PAGE_WIDTH / 2:.0f}" y="{PAGE_HEIGHT / 2:.0f}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="36" fill="#999">{_escape(page.note)}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---- PDF（手搓，只用到直线段，不引第三方渲染栈）---------------------

_SCALE = 0.5  # 设备像素 → PDF pt，1404×1872 → 702×936


def pages_to_pdf(pages: list[Page]) -> bytes:
    """整本导出。内容流 zlib 压过——密的笔记不压能到几十 MB。"""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)  # 1-based 对象号

    page_objs: list[int] = []
    content_objs: list[int] = []
    for page in pages or [Page()]:
        stream = zlib.compress(_page_content(page))
        content_objs.append(add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stream)
                                + stream + b"\nendstream"))
        page_objs.append(add(b""))  # 占位，父节点号确定后回填

    pages_obj = add(b"")
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj)

    for i, (page, obj) in enumerate(zip(pages or [Page()], page_objs)):
        width, height = PAGE_WIDTH * _SCALE, page.height * _SCALE
        objects[obj - 1] = (
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.1f %.1f] /Contents %d 0 R "
            b"/Resources << >> >>" % (pages_obj, width, height, content_objs[i])
        )
    kids = b" ".join(b"%d 0 R" % o for o in page_objs)
    objects[pages_obj - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_objs))

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1) + b"0000000000 65535 f \n"
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, catalog, xref)
    return bytes(out)


def _page_content(page: Page) -> bytes:
    """一页的内容流。cm 把设备坐标（y 向下）翻成 PDF 坐标（y 向上）。"""
    height = page.height * _SCALE
    ops = [b"1 J 1 j", b"%.2f 0 0 -%.2f 0 %.1f cm" % (_SCALE, _SCALE, height)]
    for stroke in page.strokes:
        r, g, b = _rgb(stroke.color, stroke.opacity)
        ops.append(b"%.3f %.3f %.3f RG %.1f w" % (r, g, b, stroke.width))
        (x0, y0), *rest = stroke.points
        path = [b"%.1f %.1f m" % (x0, y0)] + [b"%.1f %.1f l" % (x, y) for x, y in rest]
        ops.append(b" ".join(path) + b" S")
    return b"\n".join(ops)


def _rgb(color: str, opacity: float) -> tuple[float, float, float]:
    """PDF 这边不搞透明度：荧光笔按不透明度往白里兑，省一层 ExtGState。"""
    r, g, b = (int(color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    if opacity < 1:
        r, g, b = (c * opacity + (1 - opacity) for c in (r, g, b))
    return r, g, b
