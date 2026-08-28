"""内容校验的离线单测（纪律 5）。服务端不校验内容，所以这层是唯一的防线。"""

import io
import zipfile

import pytest

from rmclient.validate import ValidationError, check_extension, validate
from tests.fixtures import tiny_epub, tiny_pdf, tiny_rmdoc


def test_valid_payloads_pass():
    assert validate(tiny_epub(), "Book One.epub") == ".epub"
    assert validate(tiny_pdf(), "Paper.pdf") == ".pdf"
    assert validate(tiny_rmdoc(), "Note.rmdoc") == ".rmdoc"


# ---- 后缀 ----------------------------------------------------------


def test_extension_is_checked_before_content():
    # 拒因必须能分开：.txt 该报「后缀不在白名单」，不是「不是合法 epub」。
    with pytest.raises(ValidationError, match="not in"):
        validate(b"whatever", "Book.txt")


def test_uppercase_extension_is_refused():
    # 大写后缀的服务端分派行为未验证（REPORT §3.1 只测过小写）。
    with pytest.raises(ValidationError, match="not in"):
        check_extension("Book.PDF")


def test_no_extension_is_refused():
    with pytest.raises(ValidationError, match="not in"):
        check_extension("Book")


# ---- 内容与后缀错配（服务端会安静地接受，见 REPORT §3.1 的 D/E 组）----


def test_pdf_bytes_named_epub_is_refused():
    with pytest.raises(ValidationError, match="not a valid EPUB"):
        validate(tiny_pdf(), "Book.epub")


def test_epub_bytes_named_pdf_is_refused():
    with pytest.raises(ValidationError, match="not a valid PDF"):
        validate(tiny_epub(), "Book.pdf")


# ---- EPUB 的 OCF 三条 ----------------------------------------------


def _epub_with(first_name="mimetype", compress=zipfile.ZIP_STORED, payload=b"application/epub+zip"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo(first_name)
        info.compress_type = compress
        z.writestr(info, payload)
        z.writestr("content.opf", "<package/>")
    return buf.getvalue()


def test_epub_mimetype_must_be_the_first_entry():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("content.opf", "<package/>")
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, "application/epub+zip")
    with pytest.raises(ValidationError, match="first zip entry"):
        validate(buf.getvalue(), "Book.epub")


def test_epub_mimetype_must_be_stored_uncompressed():
    with pytest.raises(ValidationError, match="uncompressed"):
        validate(_epub_with(compress=zipfile.ZIP_DEFLATED), "Book.epub")


def test_epub_mimetype_content_must_be_right():
    with pytest.raises(ValidationError, match="must contain"):
        validate(_epub_with(payload=b"application/zip"), "Book.epub")


def test_epub_that_is_not_a_zip_is_refused():
    with pytest.raises(ValidationError, match="not a zip archive"):
        validate(b"just some text", "Book.epub")


def test_empty_zip_named_epub_is_refused():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w"):
        pass
    with pytest.raises(ValidationError, match="empty"):
        validate(buf.getvalue(), "Book.epub")


# ---- PDF / rmdoc 魔数 ----------------------------------------------


def test_pdf_magic_must_be_at_offset_zero():
    with pytest.raises(ValidationError, match="magic bytes"):
        validate(b"\n%PDF-1.4", "Paper.pdf")


def test_rmdoc_must_be_a_zip():
    with pytest.raises(ValidationError, match="not a valid .rmdoc"):
        validate(b"%PDF-1.4", "Note.rmdoc")
