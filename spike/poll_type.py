#!/usr/bin/env python3
"""观察刚上传的文档在文档树里的 type 字段何时从「文件名」收敛为 fileType。"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import epub_spike as s

kept = json.loads((Path(__file__).resolve().parent / "out/results-keep.json").read_text())
doc_id = kept["uploads"][0]["id"]
u, p = s.creds(); api = s.Api(u, p); api.login()
log = []
for wait in (0, 15, 30, 60, 120, 300):
    if wait:
        time.sleep(wait)
    flat = []
    s.flatten(api.tree_raw().get("Entries") or [], "", flat)
    e = next((x for x in flat if x["id"] == doc_id), None)
    t = e["type_field"] if e else "<gone>"
    elapsed = sum((0, 15, 30, 60, 120, 300)[:(0, 15, 30, 60, 120, 300).index(wait) + 1])
    log.append({"t_plus_s": elapsed, "type": "<equals name>" if e and t == e["name"] else t})
    print(json.dumps(log[-1], ensure_ascii=False), flush=True)
(Path(__file__).resolve().parent / "out/poll_type.json").write_text(json.dumps(log, ensure_ascii=False, indent=2))
api.c.close()
