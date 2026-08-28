#!/usr/bin/env python3
"""M1 契约补测：同名 / 重复上传语义，以及同名目录。

    uv run python spike/dup_upload_spike.py

在根级临时目录 rmclient-spike-<8hex> 里做，全程只碰本次自己创建的对象，跑完
按白名单 UUID 删除并回查残留。用的是 rmclient 库本身（顺带过一遍真实调用路径）。

要回答的问题（SPEC M1 / REPORT §8 第一条）：同一文件名传两次，是产生两份独立
UUID、覆盖、还是 409？这决定客户端「更新一本书」怎么做。
"""

import json
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from epub_spike import build_epub  # noqa: E402  只借它造合规 epub

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rmclient import RmApiError, RmClient  # noqa: E402
from rmclient.models import Folder, find, walk  # noqa: E402

OUT = Path(__file__).resolve().parent / "out"
results: dict = {"started": time.strftime("%Y-%m-%d %H:%M:%S %z"), "steps": []}
created: list[tuple[str, str]] = []  # (uuid, label)；只有这里的 id 允许被删


def record(title: str, **detail):
    results["steps"].append({"title": title, **detail})
    print(f"  · {title}: " + ", ".join(f"{k}={v!r}" for k, v in detail.items()))


def main() -> int:
    sandbox = f"rmclient-spike-{secrets.token_hex(4)}"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    filename = f"Dup Probe {stamp}.epub"
    visible = filename[: -len(".epub")]
    results["sandbox"], results["filename"] = sandbox, filename
    print(f"\n重复上传契约补测 → 临时目录 {sandbox!r}，文件名 {filename!r}\n")

    client = RmClient()
    try:
        client.login()
        box = client.create_folder(sandbox)
        created.append((box.id, f"folder {sandbox}"))
        results["sandbox_id"] = box.id
        print(f"  沙箱目录 UUID {box.id}（进程若中途死掉，按这个 UUID 手工清理）\n")

        book_a, book_b = build_epub("aaaaaaaa-0000-0000-0000-000000000001"), build_epub(
            "bbbbbbbb-0000-0000-0000-000000000002"
        )
        assert book_a != book_b

        # ---- 1/2/3：同名上传三次（同字节、同字节、不同字节）----
        for label, data in (("#1 first", book_a), ("#2 same bytes", book_a), ("#3 other bytes", book_b)):
            try:
                node = client.upload(data, filename, parent=box.id)
                created.append((node.id, f"upload {label}"))
                record(f"upload {label}", id=node.id, name=node.name, parent=node.parent,
                       version=node.version, bytes=len(data))
            except RmApiError as exc:
                record(f"upload {label}", failed=True, status=exc.status, error=exc.error)

        # ---- 4：回查沙箱里的内容 ----
        tree = client.list_tree()
        box_node = find(tree.entries, box.id)
        children = [
            {"id": n.id, "name": n.name, "type": getattr(n, "type", ""), "size": getattr(n, "size", 0)}
            for _, n in walk([box_node])
            if n.id != box.id
        ]
        results["sandbox_children"] = children
        record("回查沙箱", count=len(children), visible_names=[c["name"] for c in children],
               distinct_ids=len({c["id"] for c in children}))
        record("可见名是否即文件名去后缀", expected=visible,
               matches=sum(1 for c in children if c["name"] == visible))

        # ---- 5：同名目录建两次 ----
        for label in ("#1", "#2"):
            try:
                sub = client.create_folder("dup", parent=box.id)
                created.append((sub.id, f"folder dup {label}"))
                record(f"create_folder dup {label}", id=sub.id, name=sub.name, version=sub.version)
            except RmApiError as exc:
                record(f"create_folder dup {label}", failed=True, status=exc.status, error=exc.error)

        tree = client.list_tree()
        box_node = find(tree.entries, box.id)
        dups = [n for _, n in walk([box_node]) if isinstance(n, Folder) and n.name == "dup"]
        record("回查同名目录", count=len(dups), ids=[n.id for n in dups])

    finally:
        # ---- 6：清理（白名单 UUID + 先深后浅 + 回查残留）----
        print("\n清理：")
        try:
            entries = client.list_tree().entries
            ids = [i for i, _ in created]
            present = [i for i in ids if find(entries, i)]
            gone = [i for i in ids if i not in present]
            if gone:
                # 创建过但树上已经没有了——这本身就是覆盖语义的证据。
                record("创建后已不在树上（覆盖证据）", ids=gone)
            ordered = client.delete_many(present, allowed_ids=set(ids), entries=entries)
            print(f"  · 已删 {len(ordered)} 项（先深后浅）")
            after = client.list_tree().entries
            residue = [i for i in ids if find(after, i)]
            results["cleanup"] = {"deleted": ordered, "already_gone": gone, "residue": residue}
            print(f"  {'✓' if not residue else '✗'} 回查残留 {len(residue)} 项")
        except Exception as exc:
            results["cleanup"] = {"error": f"{type(exc).__name__}: {exc}", "created": created}
            print(f"  ✗ 清理失败：{exc}\n     需手工清理：{created}")
        client.close()

    OUT.mkdir(exist_ok=True)
    (OUT / "dup_upload.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n原始记录 → {OUT / 'dup_upload.json'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
