#!/usr/bin/env python3
"""rmclient 可行性 spike：从本机推一本 epub 到自建云（rmfakecloud v0.0.31）。

    python3 spike/epub_spike.py            # 建→传→查→读回→删 闭环，跑完自己清理
    python3 spike/epub_spike.py --keep     # 同上但不清理，留给设备端肉眼验收

在一个临时根级目录 rmclient-spike-<8位随机> 里走完 建→传→查→读回→删 全流程，
全程只碰本脚本自己创建的对象。核心待验证问题：epub 与 PDF 在上传路径上的差异。

变量隔离：六次上传打进同一个临时目录，把「扩展名 / 真实内容 / 声明的 content-type」
三个变量逐一拆开（含 epub 字节挂 .pdf 名、pdf 字节挂 .epub 名的交叉错配，以及
.txt 的白名单探针），用来判定服务端到底按什么分派。

参考实现是 ~/Documents/paperpal 的 pipeline/rm_api.py 与 scripts/m0_spike.py（只读，
不 import：那边的 Config 依赖 paperpal 的容器环境）。
"""

import hashlib
import io
import json
import secrets
import sys
import time
import traceback
import zipfile
from pathlib import Path

import httpx

ENV_FILE = Path.home() / "Documents/paperpal/.env"
PW_FILE = Path.home() / "Documents/paperpal/secrets/rmfakecloud_password"
OUT = Path(__file__).resolve().parent / "out"


def _base() -> str:
    """隧道域名读本地配置（DOMAIN 键），不写进仓库。"""
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("DOMAIN="):
            return "https://" + line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError(f"DOMAIN not found in {ENV_FILE}")


BASE = _base()

OK, BAD, SKIP = "✓", "✗", "–"

results: dict = {"base_url": BASE, "started": time.strftime("%Y-%m-%d %H:%M:%S %z"), "steps": []}
created: list[tuple[str, str]] = []  # (uuid, label) 由浅入深；只有这里的 id 允许被删


def step(title, fn):
    """跑一步，打印 ✓/✗。失败不中断，让后面能独立验证的步骤继续。"""
    try:
        detail = fn()
    except Exception as exc:
        results["steps"].append({"title": title, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        print(f"  {BAD} {title}\n      {type(exc).__name__}: {exc}")
        if "-v" in sys.argv:
            traceback.print_exc()
        return None
    results["steps"].append({"title": title, "ok": True, "detail": str(detail)})
    print(f"  {OK} {title}" + (f" — {detail}" if detail else ""))
    return detail


# ---- 凭据 ----------------------------------------------------------


def creds() -> tuple[str, str]:
    user = ""
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("RMFAKECLOUD_USER="):
            user = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not user:
        raise RuntimeError(f"RMFAKECLOUD_USER not found in {ENV_FILE}")
    return user, PW_FILE.read_text().strip()


# ---- 载荷构造 ------------------------------------------------------

_CHAPTERS = [
    ("ch1", "Chapter One — The Tunnel",
     "This book exists for exactly one reason: to prove that an EPUB pushed from a laptop, "
     "through a Cloudflare tunnel, into a self-hosted rmfakecloud instance, arrives on an "
     "e-ink device as a readable book. Nothing here is meant to be interesting. It is meant "
     "to be legible. If you are reading this sentence on a reMarkable, the upload path works "
     "end to end and the byte stream survived every hop between the client and the device. "
     "The three chapters differ in their opening words so that chapter navigation can be "
     "checked by eye without counting pages. Each one carries several paragraphs so that "
     "pagination has something to do. "),
    ("ch2", "Chapter Two — The Discriminator",
     "The open question this spike answers is narrow: does the server treat an EPUB the same "
     "way it treats a PDF? The reference implementation claims dispatch happens on the file "
     "extension, and that the extension is stripped from the visible name before the document "
     "is stored. If that claim holds, the title shown in the device library is the filename "
     "with its suffix removed, and the content type declared by the HTTP client never matters. "
     "This chapter exists so that a reader can confirm the middle of the book renders as well "
     "as the beginning. Text reflow, margins, and font size are all worth a glance here. "),
    ("ch3", "Chapter Three — CJK Probe",
     "The last chapter carries a deliberate probe for non-Latin script support. The line below "
     "is Chinese; whether it renders as characters or as empty boxes is a finding either way, "
     "and it says nothing about whether the upload path itself succeeded. "
     "CJK probe line: 这一行是中文字形探针，用来判断设备端 EPUB 阅读器是否内置中日韩字体。"
     "If the Latin text on this page is readable, the transfer was successful regardless of "
     "how the Chinese line above appears. "),
]

BOOK_TITLE = "rmclient EPUB Spike"


def build_epub(uid: str) -> bytes:
    """最小但 OCF 合规的 EPUB 3：mimetype 必须是第一个条目且不压缩。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        zi = zipfile.ZipInfo("mimetype")
        zi.compress_type = zipfile.ZIP_STORED
        z.writestr(zi, "application/epub+zip")  # 必须第一个写

        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
                   '  <rootfiles><rootfile full-path="OEBPS/content.opf" '
                   'media-type="application/oebps-package+xml"/></rootfiles>\n</container>\n')

        items = "\n".join(
            f'    <item id="{cid}" href="{cid}.xhtml" media-type="application/xhtml+xml"/>'
            for cid, _, _ in _CHAPTERS)
        spine = "\n".join(f'    <itemref idref="{cid}"/>' for cid, _, _ in _CHAPTERS)
        z.writestr("OEBPS/content.opf",
                   '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bid">\n'
                   '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
                   f'    <dc:identifier id="bid">urn:uuid:{uid}</dc:identifier>\n'
                   f'    <dc:title>{BOOK_TITLE}</dc:title>\n'
                   '    <dc:language>en</dc:language>\n'
                   '    <dc:creator>rmclient spike</dc:creator>\n'
                   '    <meta property="dcterms:modified">2026-08-28T00:00:00Z</meta>\n'
                   '  </metadata>\n  <manifest>\n'
                   '    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>\n'
                   f'{items}\n  </manifest>\n  <spine>\n{spine}\n  </spine>\n</package>\n')

        nav_items = "\n".join(f'      <li><a href="{cid}.xhtml">{title}</a></li>'
                              for cid, title, _ in _CHAPTERS)
        z.writestr("OEBPS/nav.xhtml",
                   '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">\n'
                   f'<head><title>{BOOK_TITLE}</title></head><body>\n'
                   '  <nav epub:type="toc" id="toc"><h1>Contents</h1><ol>\n'
                   f'{nav_items}\n  </ol></nav>\n</body></html>\n')

        for cid, title, body in _CHAPTERS:
            paras = "\n".join(f"  <p>{body}</p>" for _ in range(4))
            z.writestr(f"OEBPS/{cid}.xhtml",
                       '<?xml version="1.0" encoding="UTF-8"?>\n'
                       '<html xmlns="http://www.w3.org/1999/xhtml">\n'
                       f'<head><title>{title}</title></head><body>\n  <h1>{title}</h1>\n'
                       f'{paras}\n</body></html>\n')
    return buf.getvalue()


def check_epub(data: bytes) -> str:
    """上传前本地自检：epub 坏了的话设备端不显示就无从归因。"""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if infos[0].filename != "mimetype":
            raise AssertionError(f"first zip entry is {infos[0].filename!r}, must be 'mimetype'")
        if infos[0].compress_type != zipfile.ZIP_STORED:
            raise AssertionError("mimetype entry must be STORED (uncompressed)")
        if z.read("mimetype") != b"application/epub+zip":
            raise AssertionError("mimetype content wrong")
        if z.testzip() is not None:
            raise AssertionError("zip CRC check failed")
        import xml.etree.ElementTree as ET
        for name in ("META-INF/container.xml", "OEBPS/content.opf", "OEBPS/nav.xhtml"):
            ET.fromstring(z.read(name))
        names = [i.filename for i in infos]
    return f"{len(data)} B，{len(names)} 个条目，OCF 结构与 XML 均合法"


def minimal_pdf() -> bytes:
    """一页 A5 PDF，手搓（本机没有 pypdf；PDF 只作为 epub 的对照组）。"""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 420 595] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        None,  # 内容流，下面填
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = b"BT /F1 18 Tf 50 500 Td (rmclient spike control PDF) Tj ET"
    objs[3] = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n").encode() + b"%%EOF\n"
    return bytes(out)


# ---- API（照抄 pipeline/rm_api.py 的端点契约，不 import）-------------


class Api:
    def __init__(self, user, password):
        self.user, self.password = user, password
        self.token = None
        self.c = httpx.Client(base_url=BASE, timeout=httpx.Timeout(120.0, connect=10.0),
                              follow_redirects=False)

    def login(self):
        r = self.c.post("/ui/api/login", json={"email": self.user, "password": self.password})
        if r.status_code != 200:
            raise RuntimeError(f"login failed: HTTP {r.status_code}")  # 绝不打印响应体
        self.token = r.text.strip()
        if not self.token:
            raise RuntimeError("login returned an empty token")

    def req(self, method, url, **kw):
        r = self.c.request(method, url, headers={"Authorization": f"Bearer {self.token}"}, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"{method} {url} -> HTTP {r.status_code}: {r.text[:200]}")
        return r

    def tree_raw(self) -> dict:
        return self.req("GET", "/ui/api/documents").json()

    def create_folder(self, name, parent=""):
        r = self.req("POST", "/ui/api/folders", json={"parentId": parent, "name": name})
        d = r.json()
        return str(d.get("ID") or d.get("id")), d

    def upload(self, data, filename, content_type, parent):
        r = self.req("POST", "/ui/api/documents/upload",
                     files={"file": (filename, data, content_type)},
                     data={"parent": parent or "root"})
        payload = r.json()
        d = payload[0] if isinstance(payload, list) else payload
        return str(d.get("ID") or d.get("id")), payload

    def delete(self, doc_id):
        assert any(doc_id == cid for cid, _ in created), f"refusing to delete {doc_id}: not created here"
        self.req("DELETE", f"/ui/api/documents/{doc_id}")


def rec_bytes(rec):
    return _PAYLOADS[rec["payload"]]


_PAYLOADS: dict = {}


def flatten(entries, parent, out):
    for e in entries:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        is_folder = bool(e.get("isFolder")) or "children" in e
        out.append({"id": str(e["id"]), "name": e.get("name") or "", "parent": parent,
                    "kind": "folder" if is_folder else "doc",
                    "type_field": (e.get("type") or "") if not is_folder else "",
                    "raw": e if not is_folder else {k: v for k, v in e.items() if k != "children"}})
        if is_folder:
            flatten(e.get("children") or [], str(e["id"]), out)


# ---- 主流程 --------------------------------------------------------


def main() -> int:
    user, password = creds()
    api = Api(user, password)
    sandbox = f"rmclient-spike-{secrets.token_hex(4)}"
    results["sandbox_folder"] = sandbox
    print(f"\nrmclient epub spike → {BASE}\n临时目录 {sandbox!r}（全程只碰本次自建对象）\n")

    uploads: list[dict] = []
    try:
        # ---- 1. 登录 ----
        if step("登录 POST /ui/api/login", lambda: (api.login(), "拿到 token")[1]) is None:
            return 1

        # ---- 2. 文档树（只读）----
        def read_tree():
            raw = api.tree_raw()
            entries = raw.get("Entries") or raw.get("entries") or []
            flat: list[dict] = []
            flatten(entries, "", flat)
            roots = [e for e in flat if not e["parent"]]
            results["tree_top_keys"] = sorted(raw.keys())
            results["tree_entry_keys"] = sorted(flat[0]["raw"].keys()) if flat else []
            results["tree_summary"] = {
                "total": len(flat),
                "folders": sum(1 for e in flat if e["kind"] == "folder"),
                "root_level": [{"name": e["name"], "kind": e["kind"]} for e in roots],
                "trash_count": len(raw.get("Trash") or raw.get("trash") or []),
            }
            return (f"{len(flat)} 个条目（{results['tree_summary']['folders']} 目录），"
                    f"根级 {len(roots)} 项；顶层键 {results['tree_top_keys']}")

        if step("列出文档树 GET /ui/api/documents（只读）", read_tree) is None:
            return 1

        # ---- 3. 建临时根级目录 ----
        def mkroot():
            fid, raw = api.create_folder(sandbox, "")
            created.append((fid, f"临时目录 {sandbox!r}"))
            results["folder_response_raw"] = raw
            return f"UUID {fid}"

        if step(f"创建根级临时目录 {sandbox!r} POST /ui/api/folders", mkroot) is None:
            return 1
        folder_id = created[0][0]

        # ---- 4. 造 epub 并本地自检 ----
        book_uid = secrets.token_hex(16)
        epub = build_epub(book_uid)
        pdf = minimal_pdf()
        results["epub_sha256"] = hashlib.sha256(epub).hexdigest()
        results["epub_size"] = len(epub)
        results["pdf_size"] = len(pdf)
        results["pdf_sha256"] = hashlib.sha256(pdf).hexdigest()
        _PAYLOADS.update(epub=epub, pdf=pdf)
        if step("本地构造 EPUB 3 并自检 OCF 合规", lambda: check_epub(epub)) is None:
            return 1

        # ---- 5. 上传矩阵 ----
        stamp = time.strftime("%Y%m%d-%H%M%S")
        # 三个变量各自隔离：扩展名 / 真实内容 / 声明的 content-type
        plan = [
            (f"{BOOK_TITLE} A {stamp}.epub", "application/epub+zip", epub, "A epub 内容 + .epub + 正确 MIME"),
            (f"{BOOK_TITLE} B {stamp}.epub", "application/octet-stream", epub, "B epub 内容 + .epub + 通用 MIME"),
            (f"rmclient control PDF {stamp}.pdf", "application/pdf", pdf, "C pdf 内容 + .pdf + 正确 MIME（对照）"),
            (f"rmclient mismatch epub-as-pdf {stamp}.pdf", "application/epub+zip", epub, "D epub 内容 + .pdf 扩展名"),
            (f"rmclient mismatch pdf-as-epub {stamp}.epub", "application/pdf", pdf, "E pdf 内容 + .epub 扩展名"),
            (f"rmclient unsupported ext {stamp}.txt", "text/plain", epub, "F epub 内容 + .txt（预期被拒）"),
        ]
        if KEEP:   # 人工验收轮：只留一本干净的书，别把探针也推到设备上
            plan = plan[:1]
        for filename, ctype, data, label in plan:
            rec = {"label": label, "filename": filename, "content_type": ctype, "size": len(data),
                   "payload": "epub" if data is epub else "pdf"}

            def do(filename=filename, ctype=ctype, data=data, rec=rec):
                did, payload = api.upload(data, filename, ctype, folder_id)
                created.append((did, f"{label} {filename!r}"))
                rec.update(id=did, response=payload, ok=True)
                return f"UUID {did}"

            expect_reject = label.startswith("F")
            r = step(f"上传 {label}", do)
            if r is None:
                rec["ok"] = False
                if expect_reject:      # 被拒是预期结果，不算失败
                    results["steps"][-1]["ok"] = True
                    results["steps"][-1]["expected_rejection"] = True
                    print(f"      ↑ 预期内的拒绝（.txt 不在白名单）")
            uploads.append(rec)
        results["uploads"] = uploads

        # ---- 6. 回查文档树 ----
        def verify():
            flat: list[dict] = []
            raw = api.tree_raw()
            flatten(raw.get("Entries") or raw.get("entries") or [], "", flat)
            by_id = {e["id"]: e for e in flat}
            lines = []
            for rec in uploads:
                if not rec.get("ok"):
                    continue
                e = by_id.get(rec["id"])
                if e is None:
                    raise AssertionError(f"{rec['filename']!r} ({rec['id']}) 不在文档树里")
                if e["parent"] != folder_id:
                    raise AssertionError(f"{rec['id']} 父目录是 {e['parent']}，期望 {folder_id}")
                rec["visible_name"] = e["name"]
                rec["tree_type_field"] = e["type_field"]
                rec["tree_raw"] = e["raw"]
                rec["ext_trimmed"] = (e["name"] == rec["filename"].rsplit(".", 1)[0])
                lines.append(f"{e['name']!r} type={e['type_field']!r}")
            docs = [e for e in flat if e["kind"] == "doc"]
            results["type_equals_name"] = {
                "docs_checked": len(docs),
                "type_field_equals_name": sum(1 for e in docs if e["type_field"] == e["name"]),
            }
            results["folder_entry_raw"] = by_id.get(folder_id, {}).get("raw")
            return " | ".join(lines)

        step("回查文档树：父目录 / 可见名 / file_type", verify)

        # ---- 7. 读回：每份都拉 rmdoc，解出 .content/.metadata（真正的类型判别位）----
        def readback():
            lines = []
            for rec in uploads:
                if not rec.get("ok"):
                    continue
                r = api.req("GET", f"/ui/api/documents/{rec['id']}", params={"type": "rmdoc"})
                blob = r.content
                info = {"http_content_type": r.headers.get("content-type", ""), "bytes": len(blob)}
                sent_sha = hashlib.sha256(rec_bytes(rec)).hexdigest()
                try:
                    with zipfile.ZipFile(io.BytesIO(blob)) as z:
                        info["zip_entries"] = [{"name": i.filename, "size": i.file_size} for i in z.infolist()]
                        for i in z.infolist():
                            body = z.read(i.filename)
                            if hashlib.sha256(body).hexdigest() == sent_sha:
                                info["byte_identical_entry"] = i.filename
                            if i.filename.endswith(".content"):
                                info["content_json"] = json.loads(body)
                            elif i.filename.endswith(".metadata"):
                                info["metadata_json"] = json.loads(body)
                except zipfile.BadZipFile:
                    info["zip_entries"] = None
                    info["raw_is_payload"] = hashlib.sha256(blob).hexdigest() == sent_sha
                rec["readback"] = info
                ft = (info.get("content_json") or {}).get("fileType")
                ext = info.get("byte_identical_entry", "").rsplit(".", 1)[-1] if info.get("byte_identical_entry") else None
                lines.append(f"{rec['label'][:1]}: fileType={ft!r} blob=.{ext} 全同={bool(info.get('byte_identical_entry'))}")
            return " | ".join(lines)

        step("读回 rmdoc 并解出 fileType / 载荷字节比对", readback)

        return 0
    finally:
        # ---- 8. 清理：先深后浅（HashTree.Remove 不级联，先删父会把子项甩成根级孤儿）----
        if KEEP:
            print("\n  ⏸  --keep：保留本次对象供设备端肉眼验收。人工清理用：")
            for cid, label in reversed(created):
                print(f"       DELETE /ui/api/documents/{cid}   # {label}")
            results["cleanup"] = {"kept_for_device_check": [{"id": c, "label": l} for c, l in created]}
        else:
            leftovers = []
            for cid, label in reversed(created):
                try:
                    api.delete(cid)
                    print(f"  {OK} 清理 {label} — {cid}")
                except Exception as exc:
                    print(f"  {BAD} 清理 {label} — {cid} 删不掉：{type(exc).__name__}: {exc}")
                    leftovers.append({"id": cid, "label": label, "error": str(exc)})
            results["cleanup"] = {"created": [{"id": c, "label": l} for c, l in created],
                                  "leftovers": leftovers}
            try:
                flat = []
                raw = api.tree_raw()
                flatten(raw.get("Entries") or raw.get("entries") or [], "", flat)
                still = [c for c, _ in created if any(e["id"] == c for e in flat)]
                print(f"  {OK if not still else BAD} 清理复核：文档树中残留 {len(still)} 项")
                results["cleanup"]["still_in_tree"] = still
            except Exception as exc:
                print(f"  {SKIP} 清理复核失败：{exc}")
                results["cleanup"]["recheck_error"] = str(exc)
        OUT.mkdir(exist_ok=True)
        (OUT / ("results-keep.json" if KEEP else "results.json")).write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"\n结果已写入 {OUT / ('results-keep.json' if KEEP else 'results.json')}\n")
        api.c.close()


KEEP = "--keep" in sys.argv   # 保留上传物供设备端人工验收（默认跑完即清理）

if __name__ == "__main__":
    raise SystemExit(main())
