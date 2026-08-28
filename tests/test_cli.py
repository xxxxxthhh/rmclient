"""CLI 的离线测试：目标解析 + 各条拒绝路径的退出码与提示。不打真实云。"""

import re

import pytest

from rmclient.cli import main, resolve_target
from rmclient.models import PathError, parse_tree
from tests.fixtures import TREE_PAYLOAD, logged_in, tiny_epub, tiny_pdf

ENTRIES = parse_tree(TREE_PAYLOAD).entries


@pytest.fixture
def fake_cloud(monkeypatch):
    """让 cli 里的 RmClient() 拿到假云；返回捕获到的请求列表。"""
    client, seen = logged_in()
    monkeypatch.setattr("rmclient.cli.RmClient", lambda: client)
    return seen


# ---- 目标解析 ------------------------------------------------------


def test_resolve_target_defaults_to_root():
    assert resolve_target(ENTRIES, None) == ""
    assert resolve_target(ENTRIES, "") == ""


def test_resolve_target_walks_the_visible_path():
    assert resolve_target(ENTRIES, "Books/CS") == "cs"


def test_resolve_target_refuses_the_mailbox_by_name():
    with pytest.raises(PermissionError, match="Mailbox"):
        resolve_target(ENTRIES, "Mailbox")
    with pytest.raises(PermissionError, match="Mailbox"):
        resolve_target(ENTRIES, "Mailbox/anything")


def test_resolve_target_never_falls_back_to_root():
    with pytest.raises(PathError):
        resolve_target(ENTRIES, "Nope")


# ---- push 命令 -----------------------------------------------------


def test_push_uploads_and_reports_the_uuid(fake_cloud, tmp_path, capsys):
    book = tmp_path / "Fresh Book.epub"
    book.write_bytes(tiny_epub())
    assert main(["push", str(book), "--to", "Books/CS"]) == 0
    out = capsys.readouterr().out
    assert "uploaded 'Fresh Book'" in out and "u1" in out
    assert [r.url.path for r in fake_cloud][-1] == "/ui/api/documents/upload"


def test_push_refuses_a_missing_file(fake_cloud, tmp_path, capsys):
    assert main(["push", str(tmp_path / "nope.epub")]) == 2
    assert "no such file" in capsys.readouterr().err
    assert fake_cloud == []  # 连登录都不该发生


def test_push_refuses_a_bad_extension(fake_cloud, tmp_path, capsys):
    bad = tmp_path / "Book.txt"
    bad.write_bytes(tiny_epub())
    assert main(["push", str(bad)]) == 2
    assert "refusing to upload" in capsys.readouterr().err


def test_push_refuses_content_that_contradicts_the_extension(fake_cloud, tmp_path, capsys):
    # 服务端不校验内容，传错后缀会安静地把书弄坏在设备端（纪律 5）。
    bad = tmp_path / "Book.epub"
    bad.write_bytes(tiny_pdf())
    assert main(["push", str(bad)]) == 2
    err = capsys.readouterr().err
    assert "not a valid EPUB" in err
    assert "/ui/api/documents/upload" not in [r.url.path for r in fake_cloud]


def test_push_refuses_an_unknown_target_and_lists_candidates(fake_cloud, tmp_path, capsys):
    book = tmp_path / "Book.epub"
    book.write_bytes(tiny_epub())
    assert main(["push", str(book), "--to", "Nope"]) == 2
    err = capsys.readouterr().err
    assert "--to did not resolve" in err and "Books" in err


def test_push_refuses_the_mailbox(fake_cloud, tmp_path, capsys):
    book = tmp_path / "Book.epub"
    book.write_bytes(tiny_epub())
    assert main(["push", str(book), "--to", "Mailbox"]) == 2
    assert "Mailbox" in capsys.readouterr().err


def test_push_refuses_a_duplicate_and_points_at_force(fake_cloud, tmp_path, capsys):
    book = tmp_path / "Book One.epub"
    book.write_bytes(tiny_epub())
    assert main(["push", str(book), "--to", "Books"]) == 3
    err = capsys.readouterr().err
    assert "already holds 'Book One'" in err and "--force" in err
    assert "/ui/api/documents/upload" not in [r.url.path for r in fake_cloud]


def test_push_force_uploads_and_warns_about_the_copies(fake_cloud, tmp_path, capsys):
    book = tmp_path / "Book One.epub"
    book.write_bytes(tiny_epub())
    assert main(["push", str(book), "--to", "Books", "--force"]) == 0
    out = capsys.readouterr().out
    assert "identically named books" in out
    assert [r.url.path for r in fake_cloud][-1] == "/ui/api/documents/upload"


def test_missing_configuration_prints_one_line_not_a_traceback(monkeypatch, tmp_path, capsys):
    from rmclient import config

    for key in (config.ENV_URL, config.ENV_USER, config.ENV_PASSWORD, config.ENV_PASSWORD_FILE):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config, "FALLBACK_ENV_FILE", tmp_path / "nope/.env")
    monkeypatch.setattr(config, "FALLBACK_PASSWORD_FILE", tmp_path / "nope/password")
    book = tmp_path / "Book.epub"
    book.write_bytes(tiny_epub())

    assert main(["push", str(book)]) == 2
    err = capsys.readouterr().err
    assert "bad configuration" in err and config.ENV_USER in err
    assert "Traceback" not in err


# ---- 输出语言 ------------------------------------------------------

CJK = re.compile(r"[一-鿿]")


@pytest.mark.parametrize(
    "argv, code",
    [
        (["push", "{ok}", "--to", "Books/CS"], 0),               # 成功
        (["push", "{missing}"], 2),                              # 文件不存在
        (["push", "{bad_ext}"], 2),                              # 后缀不在白名单
        (["push", "{ok}", "--to", "Nope"], 2),                   # --to 解析不到
        (["push", "{ok}", "--to", "Mailbox"], 2),                # 锁定目录
        (["push", "{dup}", "--to", "Books"], 3),                 # 重名
        (["push", "{dup}", "--to", "Books", "--force"], 0),      # 重名照传
    ],
)
def test_cli_speaks_english_on_every_path_and_keeps_its_exit_codes(
    fake_cloud, tmp_path, capsys, argv, code
):
    """公开项目的默认脸面是英文；退出码与语义一个都不动。"""
    files = {
        "ok": tmp_path / "Fresh Book.epub",
        "dup": tmp_path / "Book One.epub",
        "bad_ext": tmp_path / "Book.txt",
        "missing": tmp_path / "nope.epub",
    }
    for key, path in files.items():
        if key != "missing":
            path.write_bytes(tiny_epub())

    assert main([a.format(**{k: str(v) for k, v in files.items()}) for a in argv]) == code
    captured = capsys.readouterr()
    assert not CJK.search(captured.out + captured.err), captured.out + captured.err


def test_the_help_text_is_english_too(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert not CJK.search(capsys.readouterr().out)
