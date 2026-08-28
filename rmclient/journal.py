"""删除记录：删掉的 UUID 落到本地文件，等设备同步一轮之后还能复查。

为什么要落盘：删除是硬删，且设备端对该文档有本地变更时会把它**原 UUID 推回**
（REPORT §9.2）。复活要等设备同步一轮——几分钟到几小时——那会儿页面早刷新过了，
UUID 不能只活在浏览器内存里。

文件是本地状态：默认落在 XDG state 目录（~/.local/state/rmclient/deleted.json），
不进 git，也不在包目录旁边——装成 wheel 之后那里根本不该写。
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from .config import deleted_file


class DeletionJournal:
    def __init__(self, path: Path | None = None):
        # 默认路径在调用时算：装成 wheel 之后包目录旁边没有可写的地方，
        # 而且 uvx 那种缓存目录一 clean 记录就没了（见 config.deleted_file）。
        self.path = Path(path) if path is not None else deleted_file()

    def load(self) -> list[dict]:
        """没有文件、或者文件被人改坏了，都当空记录——复查是辅助手段，不该拦住主流程。"""
        try:
            data = json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    def append(self, items: Iterable[dict]) -> list[dict]:
        """记下刚删掉的每一项：UUID / 可见名 / 原路径 / 删除时间。"""
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        records = self.load()
        records += [
            {
                "id": item["id"],
                "name": item.get("name", ""),
                "path": item.get("path", ""),
                "kind": item.get("kind", ""),
                "deleted_at": stamp,
            }
            for item in items
        ]
        self._write(records)
        return records

    def remove(self, ids: Iterable[str]) -> int:
        """清掉指定 UUID 的记录，返回清掉的条数。"""
        ids = set(ids)
        records = self.load()
        kept = [r for r in records if r.get("id") not in ids]
        self._write(kept)
        return len(records) - len(kept)

    def clear(self) -> int:
        count = len(self.load())
        self._write([])
        return count

    def _write(self, records: list[dict]) -> None:
        # 先写临时文件再替换：中途挂掉也不会留下半截 JSON。
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records, ensure_ascii=False, indent=2))
        os.replace(tmp, self.path)
