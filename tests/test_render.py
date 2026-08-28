"""渲染的离线测试：合成的 .rm 场景数据，不打真实云。"""

import zlib

import pytest
from rmscene import scene_items as si

from rmclient.render import (
    PAGE_HEIGHT,
    PAGE_WIDTH,
    X_OFFSET,
    Page,
    Stroke,
    original_bytes,
    page_to_svg,
    pages_to_pdf,
    parse_rmdoc,
)
from tests.fixtures import rm_line, rm_page, rmdoc


# ---- rmdoc 解析 ----------------------------------------------------


def test_pages_follow_the_content_order_not_the_zip_order():
    # 页序的唯一可信来源是 .content 的 cPages.pages。
    pages = {
        "aaa": rm_page([rm_line([(0, 0), (10, 10)])]),
        "bbb": rm_page([rm_line([(0, 0), (1, 1)]), rm_line([(2, 2), (3, 3)])]),
    }
    nb = parse_rmdoc(rmdoc(pages, listed=[{"id": "bbb"}, {"id": "aaa"}]))
    assert [len(p.strokes) for p in nb.pages] == [2, 1]


def test_deleted_pages_are_skipped():
    pages = {"aaa": rm_page([]), "bbb": rm_page([rm_line([(0, 0), (1, 1)])])}
    nb = parse_rmdoc(rmdoc(pages, listed=[{"id": "aaa", "deleted": {"value": 1}}, {"id": "bbb"}]))
    assert len(nb.pages) == 1 and len(nb.pages[0].strokes) == 1


def test_non_notebook_reports_its_type_and_no_pages():
    # 类型以 rmdoc 里的 .content 为准——树上的 type 对刚上传的文档不可信（REPORT §4.1）。
    nb = parse_rmdoc(rmdoc({}, file_type="epub"))
    assert (nb.file_type, nb.pages) == ("epub", [])


def test_a_listed_page_without_its_rm_becomes_a_placeholder():
    nb = parse_rmdoc(rmdoc({}, listed=[{"id": "ghost"}]))
    assert len(nb.pages) == 1 and "没有对应的 .rm" in nb.pages[0].note


def test_one_unreadable_page_does_not_sink_the_notebook():
    pages = {"bad": b"not a rm file at all", "good": rm_page([rm_line([(0, 0), (1, 1)])])}
    nb = parse_rmdoc(rmdoc(pages, listed=[{"id": "bad"}, {"id": "good"}]))
    assert nb.pages[0].note.startswith("这一页解析失败")
    assert len(nb.pages[1].strokes) == 1


def test_rmdoc_without_content_is_an_error():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.metadata", "{}")
    with pytest.raises(ValueError, match="no .content"):
        parse_rmdoc(buf.getvalue())


# ---- 笔画 ----------------------------------------------------------


def one_page(lines):
    return parse_rmdoc(rmdoc({"p": rm_page(lines)})).pages[0]


def test_x_is_shifted_to_the_page_and_y_kept():
    page = one_page([rm_line([(0, 100), (-200, 300)])])
    assert page.strokes[0].points == [(X_OFFSET, 100.0), (X_OFFSET - 200, 300.0)]


def test_eraser_strokes_are_dropped():
    page = one_page([
        rm_line([(0, 0), (1, 1)], tool=si.Pen.ERASER),
        rm_line([(2, 2), (3, 3)], tool=si.Pen.ERASER_AREA),
        rm_line([(4, 4), (5, 5)]),
    ])
    assert len(page.strokes) == 1


def test_width_is_the_mean_point_width_over_four():
    # v6 存的 width 是真实宽度的 4 倍（rmscene point_from_stream）。
    assert one_page([rm_line([(0, 0), (1, 1)], width=16)]).strokes[0].width == 4.0
    assert one_page([rm_line([(0, 0), (1, 1)], width=1)]).strokes[0].width == 1.0  # 下限


def test_colors_map_and_highlighter_gets_opacity():
    page = one_page([
        rm_line([(0, 0), (1, 1)], color=si.PenColor.RED),
        rm_line([(2, 2), (3, 3)], tool=si.Pen.HIGHLIGHTER_1, color=si.PenColor.HIGHLIGHT),
    ])
    assert page.strokes[0].color == "#d63b3b" and page.strokes[0].opacity == 1.0
    assert page.strokes[1].opacity == 0.35


def test_page_grows_when_the_writing_runs_past_the_screen():
    assert one_page([rm_line([(0, 10), (0, 20)])]).height == PAGE_HEIGHT
    assert one_page([rm_line([(0, 10), (0, 3000)])]).height == 3040


# ---- SVG -----------------------------------------------------------


def test_empty_page_is_still_a_valid_blank_svg():
    svg = page_to_svg(Page())
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert f'viewBox="0 0 {PAGE_WIDTH} {PAGE_HEIGHT}"' in svg
    assert "polyline" not in svg


def test_svg_draws_one_polyline_per_stroke():
    svg = page_to_svg(Page(strokes=[Stroke([(1, 2), (3, 4)], "#112233", 2.5, 0.35)]))
    assert svg.count("<polyline") == 1
    assert 'points="1.0,2.0 3.0,4.0"' in svg
    assert 'stroke="#112233"' in svg and 'stroke-width="2.5"' in svg
    assert 'stroke-opacity="0.35"' in svg


def test_svg_escapes_the_placeholder_note():
    assert "&lt;bad&gt;" in page_to_svg(Page(note="<bad>"))


# ---- PDF -----------------------------------------------------------


def test_pdf_has_one_page_per_notebook_page():
    pdf = pages_to_pdf([Page(strokes=[Stroke([(0, 0), (10, 10)])]), Page()])
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    assert b"/Count 2" in pdf and pdf.count(b"/Type /Page ") == 2


def test_pdf_streams_are_compressed_and_carry_the_strokes():
    pdf = pages_to_pdf([Page(strokes=[Stroke([(100, 200), (300, 400)])])])
    assert b"/Filter /FlateDecode" in pdf
    body = pdf[pdf.index(b"stream\n") + 7 : pdf.index(b"\nendstream")]
    ops = zlib.decompress(body).decode()
    assert "100.0 200.0 m" in ops and "300.0 400.0 l S" in ops
    assert "cm" in ops  # y 翻转


def test_pdf_of_an_empty_notebook_is_still_a_one_page_pdf():
    pdf = pages_to_pdf([])
    assert pdf.startswith(b"%PDF") and b"/Count 1" in pdf


# ---- 原件取回 ------------------------------------------------------


def test_original_bytes_unpacks_an_epub():
    from tests.fixtures import tiny_epub

    payload = tiny_epub("Real Book")
    data, ext = original_bytes(rmdoc({}, file_type="epub", payload=payload))
    assert (data, ext) == (payload, "epub")


def test_original_bytes_unpacks_a_pdf():
    from tests.fixtures import tiny_pdf

    payload = tiny_pdf()
    data, ext = original_bytes(rmdoc({}, file_type="pdf", payload=payload))
    assert (data, ext) == (payload, "pdf")


def test_original_bytes_gives_the_whole_package_for_a_notebook():
    book = rmdoc({"p": rm_page([])})
    assert original_bytes(book) == (book, "rmdoc")


def test_original_bytes_falls_back_to_the_package_when_the_member_is_missing():
    # 声明了 epub 但包里没有对应成员——给整包，别 500。
    book = rmdoc({}, file_type="epub")
    assert original_bytes(book) == (book, "rmdoc")
