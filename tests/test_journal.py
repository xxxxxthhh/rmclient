"""删除记录文件的离线单测。"""

import json

import pytest

from rmclient.journal import DeletionJournal


@pytest.fixture
def journal(tmp_path):
    return DeletionJournal(tmp_path / "var" / "deleted.json")


ITEMS = [
    {"id": "b1", "name": "Book One", "path": "Books", "kind": "doc"},
    {"id": "books", "name": "Books", "path": "", "kind": "folder"},
]


def test_missing_file_reads_as_empty(journal):
    assert journal.load() == []


def test_append_records_uuid_name_path_and_time(journal):
    journal.append(ITEMS)
    records = journal.load()
    assert [(r["id"], r["name"], r["path"]) for r in records] == [
        ("b1", "Book One", "Books"),
        ("books", "Books", ""),
    ]
    assert all(r["deleted_at"] for r in records)
    # 目录自己也记，路径为空串表示根级
    assert records[1]["kind"] == "folder"


def test_append_accumulates_across_calls(journal):
    journal.append(ITEMS[:1])
    journal.append(ITEMS[1:])
    assert [r["id"] for r in journal.load()] == ["b1", "books"]


def test_remove_only_the_named_ids(journal):
    journal.append(ITEMS)
    assert journal.remove(["b1"]) == 1
    assert [r["id"] for r in journal.load()] == ["books"]
    assert journal.remove(["ghost"]) == 0


def test_clear_empties_the_file(journal):
    journal.append(ITEMS)
    assert journal.clear() == 2
    assert journal.load() == []
    assert json.loads(journal.path.read_text()) == []


def test_a_corrupt_file_reads_as_empty_instead_of_blowing_up(journal):
    journal.path.parent.mkdir(parents=True)
    journal.path.write_text("{ not json")
    assert journal.load() == []


def test_writes_are_atomic_and_leave_no_temp_file(journal):
    journal.append(ITEMS)
    assert [p.name for p in sorted(journal.path.parent.iterdir())] == ["deleted.json"]
