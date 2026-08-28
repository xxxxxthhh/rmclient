"""上传前的本地内容校验（CLAUDE.md 纪律 5）。

服务端 100% 按文件名扩展名分派，既不看内容也不看 content-type，而且**不做任何
内容校验**（REPORT §3.1）：epub 字节挂个 .pdf 名会被原样登记成 PDF 推到设备上，
不报错，只是设备端打不开且看不出原因。所以「内容与扩展名一致」只能客户端把关。

校验故意只做「能不能证伪」这一层：格式明显不对就拒，不做深度解析。
"""

from __future__ import annotations

import io
import os
import zipfile

# 服务端白名单（REPORT §3.1 的 F 组：.txt 被 500 + "unsupported extension" 拒掉）。
# 大小写敏感：只测过小写，大写后缀的分派行为未验证。
UPLOAD_EXTENSIONS = frozenset({".pdf", ".epub", ".rmdoc"})

_EPUB_MIMETYPE = b"application/epub+zip"
_ZIP_MAGIC = b"PK\x03\x04"
_PDF_MAGIC = b"%PDF-"


class ValidationError(ValueError):
    """内容或扩展名不合格，拒绝上传。"""


def check_extension(filename: str) -> str:
    """返回后缀（大小写敏感，未验证过的大写后缀一律拒）；不在白名单就拒。"""
    ext = os.path.splitext(filename)[1]
    if ext not in UPLOAD_EXTENSIONS:
        raise ValidationError(
            f"refusing to upload {filename!r}: extension {ext!r} not in "
            f"{sorted(UPLOAD_EXTENSIONS)} (server dispatches on the suffix alone)"
        )
    return ext


def check_content(data: bytes, ext: str) -> None:
    if ext == ".epub":
        _check_epub(data)
    elif ext == ".pdf":
        _check_pdf(data)
    elif ext == ".rmdoc":
        _check_rmdoc(data)
    else:  # 到不了：调用方先过 check_extension
        raise ValidationError(f"no content check for extension {ext!r}")


def validate(data: bytes, filename: str) -> str:
    """先查后缀再查内容——两种拒因的报错必须能分开。返回后缀。"""
    ext = check_extension(filename)
    check_content(data, ext)
    return ext


def _check_epub(data: bytes) -> None:
    """OCF 合规：mimetype 必须是 zip 的第一个条目、不压缩、值正确（REPORT §4.10）。

    这三条不满足的 epub，设备端打不开时无法归因是传输坏了还是书本来就坏。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            if not infos:
                raise ValidationError("not a valid EPUB: the zip is empty")
            first = infos[0]
            if first.filename != "mimetype":
                raise ValidationError(
                    f"not a valid EPUB: first zip entry is {first.filename!r}, must be 'mimetype'"
                )
            if first.compress_type != zipfile.ZIP_STORED:
                raise ValidationError(
                    "not a valid EPUB: the 'mimetype' entry must be stored uncompressed"
                )
            if z.read("mimetype").strip() != _EPUB_MIMETYPE:
                raise ValidationError(
                    f"not a valid EPUB: 'mimetype' must contain {_EPUB_MIMETYPE.decode()}"
                )
    except zipfile.BadZipFile as exc:
        raise ValidationError(f"not a valid EPUB: not a zip archive ({exc})") from exc


def _check_pdf(data: bytes) -> None:
    if not data.startswith(_PDF_MAGIC):
        raise ValidationError(
            f"not a valid PDF: missing the {_PDF_MAGIC.decode()} magic bytes at offset 0"
        )


def _check_rmdoc(data: bytes) -> None:
    if not data.startswith(_ZIP_MAGIC):
        raise ValidationError("not a valid .rmdoc: missing the zip magic bytes at offset 0")
