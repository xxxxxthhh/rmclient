"""`rmclient setup` 向导的离线单测：交互、落盘权限、验证连接、拒绝非交互。

input / getpass 全部 monkeypatch，云是 tests.fixtures 那个假云——一个真实请求都不发。
"""

import stat

import httpx
import pytest

from rmclient import config, wizard
from rmclient.config import ConfigError, config_file, default_password_file, load_credentials
from rmclient.wizard import run, write_config
from tests.fixtures import TOKEN, logged_in, make_client


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """XDG 指到 tmp，env 清空，回落路径指到空目录——绝不碰这台机器的真配置。"""
    for key in (config.ENV_URL, config.ENV_USER, config.ENV_PASSWORD,
                config.ENV_PASSWORD_FILE, config.ENV_DATA_DIR):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(config, "FALLBACK_ENV_FILE", tmp_path / "nope/.env")
    monkeypatch.setattr(config, "FALLBACK_PASSWORD_FILE", tmp_path / "nope/password")


@pytest.fixture
def answers(monkeypatch):
    """把 input / getpass 换成脚本。返回一个「装填答案」的函数。"""
    def load(typed: list[str], secret: str = "s3cret") -> list[str]:
        prompts: list[str] = []
        queue = list(typed)

        def fake_input(prompt=""):
            prompts.append(prompt)
            return queue.pop(0)

        monkeypatch.setattr("builtins.input", fake_input)
        monkeypatch.setattr(wizard.getpass, "getpass",
                            lambda prompt="": prompts.append(prompt) or secret)
        return prompts
    return load


@pytest.fixture
def fake_cloud(monkeypatch):
    """向导最后那次真连改打假云；返回捕获到的请求。"""
    client, seen = make_client()
    monkeypatch.setattr(wizard, "RmClient", lambda *a, **kw: client)
    return seen


# ---- 拒绝非交互 ----------------------------------------------------


def test_non_interactive_refuses_and_points_at_the_environment(capsys):
    assert run(non_interactive=True) == 2
    err = capsys.readouterr().err
    assert config.ENV_URL in err and config.ENV_PASSWORD_FILE in err
    assert not config_file().exists()          # 什么都别写


def test_a_pipe_instead_of_a_terminal_is_the_same_refusal(monkeypatch, capsys):
    def no_terminal(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", no_terminal)
    assert run() == 2
    assert config.ENV_URL in capsys.readouterr().err
    assert not config_file().exists()


# ---- 正常一遍 ------------------------------------------------------


def test_setup_writes_both_files_and_verifies_the_connection(answers, fake_cloud, capsys):
    answers(["https://cloud.example.test", "me@example.test"])
    assert run() == 0

    data = config_file().read_text()
    assert 'url = "https://cloud.example.test"' in data
    assert 'user = "me@example.test"' in data
    assert "s3cret" not in data                # 密码绝不进 config.toml
    assert default_password_file().read_text().strip() == "s3cret"

    out = capsys.readouterr().out
    assert "signed in" in out and "3 entries" in out    # 假云那棵树是 3 个根级条目
    assert [r.url.path for r in fake_cloud][:2] == ["/ui/api/login", "/ui/api/documents"]


def test_the_password_file_is_not_readable_by_anyone_else(answers, fake_cloud):
    answers(["https://cloud.example.test", "me@example.test"])
    run()
    mode = stat.S_IMODE(default_password_file().stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_what_setup_writes_is_what_load_credentials_reads_back(answers, fake_cloud):
    """向导和读取端必须对得上——这条断的话配置写了也白写。"""
    answers(["https://cloud.example.test/", "me@example.test"])
    run()
    assert config.base_url() == "https://cloud.example.test"     # 结尾斜杠去掉
    creds = load_credentials()
    assert (creds.user, creds.password) == ("me@example.test", "s3cret")


def test_a_bare_hostname_gets_a_scheme(answers, fake_cloud):
    answers(["cloud.example.test", "me@example.test"])
    run()
    assert 'url = "https://cloud.example.test"' in config_file().read_text()


# ---- 已有配置 ------------------------------------------------------


def test_existing_values_are_shown_and_kept_on_a_bare_enter(answers, fake_cloud, capsys):
    write_config("https://old.example.test", "old@example.test", "old-secret")
    prompts = answers(["", ""], secret="")           # 三个问题全部直接回车
    assert run() == 0
    assert "https://old.example.test" in prompts[0]  # 现值显示出来了
    assert "old@example.test" in prompts[1]
    assert "keep current" in prompts[2]              # 密码只说「保留」，不回显
    assert 'url = "https://old.example.test"' in config_file().read_text()
    assert default_password_file().read_text().strip() == "old-secret"


def test_a_new_password_replaces_the_old_one(answers, fake_cloud):
    write_config("https://old.example.test", "old@example.test", "old-secret")
    answers(["", ""], secret="new-secret")
    run()
    assert default_password_file().read_text().strip() == "new-secret"


def test_a_broken_config_does_not_block_reconfiguring(answers, fake_cloud, capsys):
    config_file().parent.mkdir(parents=True, exist_ok=True)
    config_file().write_text("this is not = = toml\n")
    answers(["https://cloud.example.test", "me@example.test"])
    assert run() == 0
    assert "ignoring the current config" in capsys.readouterr().err


def test_setup_warns_when_the_environment_shadows_the_file(monkeypatch, answers,
                                                           fake_cloud, capsys):
    """env 压着配置文件：写完不提醒，用户会以为向导没生效。"""
    monkeypatch.setenv(config.ENV_URL, "https://env.example.test")
    answers(["https://cloud.example.test", "me@example.test"])
    run()
    err = capsys.readouterr().err
    assert config.ENV_URL in err and "precedence" in err


# ---- 连接验证 ------------------------------------------------------


def test_a_rejected_login_reports_it_but_keeps_what_was_typed(monkeypatch, answers, capsys):
    def refusing(request):
        return httpx.Response(401, text="")

    client, _ = make_client(refusing)
    monkeypatch.setattr(wizard, "RmClient", lambda *a, **kw: client)
    answers(["https://cloud.example.test", "me@example.test"])
    assert run() == 1
    err = capsys.readouterr().err
    assert "could not sign in" in err and str(config_file()) in err
    # 白打一遍字是最劝退的事：配置留着，改完再跑一次就行
    assert 'user = "me@example.test"' in config_file().read_text()


def test_an_unreachable_server_gets_one_line_not_a_traceback(monkeypatch, answers, capsys):
    """打错域名是最常见的输入错误。httpx 的传输错误不是 OSError，得单独接住。"""
    def unreachable(request):
        raise httpx.ConnectError("nope")

    client, _ = make_client(unreachable)
    monkeypatch.setattr(wizard, "RmClient", lambda *a, **kw: client)
    answers(["https://typo.example.test", "me@example.test"])
    assert run() == 1
    err = capsys.readouterr().err
    assert "could not reach the server" in err and "Traceback" not in err


# ---- write_config 本身 ---------------------------------------------


def test_write_config_escapes_awkward_values():
    path, _ = write_config('https://ex.test/a"b', 'we"ird@example.test', "pw")
    assert config.read_config()["user"] == 'we"ird@example.test'
    assert path == config_file()


def test_a_custom_password_file_is_recorded_in_the_config(tmp_path):
    elsewhere = tmp_path / "vault" / "pw"
    write_config("https://ex.test", "me@example.test", "pw", password_file=elsewhere)
    assert config.read_config()["password_file"] == str(elsewhere)
    assert load_credentials().password == "pw"


def test_the_token_is_never_echoed(answers, fake_cloud, capsys):
    answers(["https://cloud.example.test", "me@example.test"])
    run()
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err
    assert "s3cret" not in captured.out + captured.err
