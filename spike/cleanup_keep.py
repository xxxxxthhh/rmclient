#!/usr/bin/env python3
"""删掉 --keep 轮留在云上的验收样本（人工肉眼确认完之后跑）。

    python3 spike/cleanup_keep.py

只删 out/results-keep.json 里记录的 UUID —— 也就是本 spike 自己创建的对象。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import epub_spike as s

f = Path(__file__).resolve().parent / "out/results-keep.json"
kept = json.loads(f.read_text())["cleanup"]["kept_for_device_check"]  # 浅→深
u, p = s.creds()
api = s.Api(u, p)
api.login()
s.created.extend((k["id"], k["label"]) for k in kept)   # delete() 的白名单
for k in reversed(kept):                                 # 先深后浅
    try:
        api.delete(k["id"])
        print(f"  ✓ 已删 {k['id']} — {k['label']}")
    except Exception as exc:
        print(f"  ✗ 删不掉 {k['id']} — {exc}")
flat = []
s.flatten(api.tree_raw().get("Entries") or [], "", flat)
still = [k["id"] for k in kept if any(e["id"] == k["id"] for e in flat)]
print(f"  {'✓' if not still else '✗'} 复核：残留 {len(still)} 项")
api.c.close()
