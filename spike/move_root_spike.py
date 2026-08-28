#!/usr/bin/env python3
"""M2 契约补测：移动到根级时 `parentId` 该传什么。

    uv run python spike/move_root_spike.py

M0 在 api.move 的注释里留了这个开放问题：建目录用空串表示根级、上传用 "root"，
两个端点不一样，移动到底认哪个没实测过。

在根级临时目录 rmclient-spike-<8hex> 里：建目录 → 传一本合成书进去 → 移到根级 →
回查 → 移回目录 → 清理。**判据是回查树里该文档的实际 parent，不是状态码**：
服务端完全可能 200 但什么都没做。
"""

import json
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from epub_spike import build_epub  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rmclient import RmApiError, RmClient  # noqa: E402
from rmclient.models import find  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
results: dict = {"started": time.strftime("%Y-%m-%d %H:%M:%S %z"), "steps": []}


def record(title, **detail):
    results["steps"].append({"title": title, **detail})
    print(f"  · {title}: " + ", ".join(f"{k}={v!r}" for k, v in detail.items()))


def main() -> int:
    sandbox = f"rmclient-spike-{secrets.token_hex(4)}"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"Move Probe {stamp}.epub"
    visible = filename[: -len(".epub")]
    results["sandbox"], results["filename"] = sandbox, filename
    print(f"\n移动到根级契约补测 → 临时目录 {sandbox!r}\n")

    created: list[str] = []
    client = RmClient()
    try:
        client.login()
        box = client.create_folder(sandbox)
        created.append(box.id)
        print(f"  沙箱目录 UUID {box.id}（进程中途死掉就按这个 UUID 手工清理）\n")

        doc = client.upload(build_epub("dddddddd-0000-0000-0000-000000000004"), filename, parent=box.id)
        created.append(doc.id)
        record("上传到沙箱", id=doc.id, name=doc.name)

        def observe(label: str) -> tuple[str, str]:
            """回查树：该文档真实的 parent 与可见名（判据在这，不在状态码）。"""
            node = find(client.list_tree().entries, doc.id)
            if node is None:
                record(f"回查 {label}", gone=True)
                return "<gone>", "<gone>"
            record(f"回查 {label}", parent=node.parent or "(根级)", name=node.name)
            return node.parent, node.name

        observe("初始")

        # ---- 候选 1：空串（建目录端点表示根级用的就是它）----
        landed = ""
        for sentinel in ("", "root"):
            try:
                client.move(doc.id, sentinel, name=visible)
                record(f"PUT parentId={sentinel!r}", ok=True)
            except RmApiError as exc:
                record(f"PUT parentId={sentinel!r}", failed=True, status=exc.status, error=exc.error)
                continue
            parent, name = observe(f"parentId={sentinel!r} 之后")
            results.setdefault("attempts", []).append(
                {"sentinel": sentinel, "parent_after": parent, "name_after": name,
                 "at_root": parent == "", "name_preserved": name == visible}
            )
            if parent == "":
                landed = sentinel
                break

        results["root_sentinel"] = landed if landed != "" or results.get("attempts") else None
        results["conclusion"] = (
            f"parentId={landed!r} 把文档移到了根级" if landed is not None else "两个 sentinel 都没能移到根级"
        )

        # ---- 移回沙箱 ----
        client.move(doc.id, box.id, name=visible)
        parent, name = observe("移回沙箱之后")
        results["move_back_ok"] = parent == box.id and name == visible

    finally:
        print("\n清理：")
        try:
            entries = client.list_tree().entries
            present = [i for i in created if find(entries, i)]
            ordered = client.delete_many(present, allowed_ids=set(created), entries=entries)
            after = client.list_tree().entries
            residue = [i for i in created if find(after, i)]
            results["cleanup"] = {"deleted": ordered, "residue": residue}
            print(f"  · 已删 {len(ordered)} 项\n  {'✓' if not residue else '✗'} 回查残留 {len(residue)} 项")
        except Exception as exc:
            results["cleanup"] = {"error": f"{type(exc).__name__}: {exc}", "created": created}
            print(f"  ✗ 清理失败：{exc}\n     需手工清理：{created}")
        client.close()

    OUT.mkdir(exist_ok=True)
    (OUT / "move_root.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n结论：{results.get('conclusion')}\n原始记录 → {OUT / 'move_root.json'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
