"""配置解析的离线单测：环境变量优先、回落条件、报错文案、锁定目录解析。"""

import pytest

from rmclient import config
from rmclient.config import (
    ENV_LOCKED_FOLDERS,
    ENV_PASSWORD,
    ENV_PASSWORD_FILE,
    ENV_URL,
    ENV_USER,
    ConfigError,
    base_url,
    load_credentials,
    locked_folders,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """每个测试从零开始：清掉所有 RMCLIENT_*，并把回落路径指到空目录（=不可用）。"""
    for key in (ENV_URL, ENV_USER, ENV_PASSWORD, ENV_PASSWORD_FILE, ENV_LOCKED_FOLDERS):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config, "FALLBACK_ENV_FILE", tmp_path / "nope/.env")
    monkeypatch.setattr(config, "FALLBACK_PASSWORD_FILE", tmp_path / "nope/password")


@pytest.fixture
def fallback(monkeypatch, tmp_path):
    """摆一套本机原有布局的假文件。"""
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nDOMAIN=fallback.example.test\nRMFAKECLOUD_USER=fallback@example.test\n")
    pw = tmp_path / "password"
    pw.write_text("fallback-secret\n")
    monkeypatch.setattr(config, "FALLBACK_ENV_FILE", env)
    monkeypatch.setattr(config, "FALLBACK_PASSWORD_FILE", pw)
    return env, pw


# ---- 地址 ----------------------------------------------------------


def test_url_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv(ENV_URL, "https://rm.example.test/")
    assert base_url() == "https://rm.example.test"  # 结尾斜杠去掉


def test_url_falls_back_only_when_the_local_files_exist(fallback):
    assert base_url() == "https://fallback.example.test"


def test_url_without_env_or_fallback_says_what_to_set():
    with pytest.raises(ConfigError) as exc:
        base_url()
    assert ENV_URL in str(exc.value) and ENV_USER in str(exc.value)
    assert ENV_PASSWORD in str(exc.value) and ENV_PASSWORD_FILE in str(exc.value)


def test_env_url_wins_over_the_fallback(monkeypatch, fallback):
    monkeypatch.setenv(ENV_URL, "https://rm.example.test")
    assert base_url() == "https://rm.example.test"


# ---- 凭据 ----------------------------------------------------------


def test_credentials_from_environment(monkeypatch):
    monkeypatch.setenv(ENV_USER, "me@example.test")
    monkeypatch.setenv(ENV_PASSWORD, "s3cret")
    creds = load_credentials()
    assert (creds.user, creds.password) == ("me@example.test", "s3cret")


def test_password_file_is_stripped(monkeypatch, tmp_path):
    # 密码文件多半带结尾换行，不 strip 会登录失败。
    pw = tmp_path / "password"
    pw.write_text("  s3cret\n")
    monkeypatch.setenv(ENV_USER, "me@example.test")
    monkeypatch.setenv(ENV_PASSWORD_FILE, str(pw))
    assert load_credentials().password == "s3cret"


def test_env_credentials_win_over_the_fallback(monkeypatch, fallback):
    monkeypatch.setenv(ENV_USER, "me@example.test")
    monkeypatch.setenv(ENV_PASSWORD, "s3cret")
    assert load_credentials().user == "me@example.test"


def test_credentials_fall_back_to_the_local_layout(fallback):
    creds = load_credentials()
    assert (creds.user, creds.password) == ("fallback@example.test", "fallback-secret")


def test_both_password_forms_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_USER, "me@example.test")
    monkeypatch.setenv(ENV_PASSWORD, "s3cret")
    monkeypatch.setenv(ENV_PASSWORD_FILE, str(tmp_path / "password"))
    with pytest.raises(ConfigError, match="not both"):
        load_credentials()


def test_user_without_any_password_is_an_error(monkeypatch):
    monkeypatch.setenv(ENV_USER, "me@example.test")
    with pytest.raises(ConfigError) as exc:
        load_credentials()
    assert ENV_PASSWORD in str(exc.value) and ENV_PASSWORD_FILE in str(exc.value)


def test_password_without_user_is_an_error_not_a_silent_fallback(monkeypatch, fallback):
    # 半套 env 配置绝不能悄悄用回落那套凭据连上另一个账户。
    monkeypatch.setenv(ENV_PASSWORD, "s3cret")
    with pytest.raises(ConfigError, match=ENV_USER):
        load_credentials()


def test_empty_password_is_an_error(monkeypatch):
    monkeypatch.setenv(ENV_USER, "me@example.test")
    monkeypatch.setenv(ENV_PASSWORD, "   ")
    with pytest.raises(ConfigError, match="empty"):
        load_credentials()


def test_missing_credentials_say_what_to_set():
    with pytest.raises(ConfigError) as exc:
        load_credentials()
    assert ENV_USER in str(exc.value) and ENV_PASSWORD_FILE in str(exc.value)


def test_the_password_never_shows_up_in_a_repr(monkeypatch):
    monkeypatch.setenv(ENV_USER, "me@example.test")
    monkeypatch.setenv(ENV_PASSWORD, "s3cret")
    assert "s3cret" not in repr(load_credentials())


# ---- 锁定目录 ------------------------------------------------------


def test_locked_folders_default_to_mailbox():
    assert locked_folders() == ("Mailbox",)


def test_locked_folders_can_be_several(monkeypatch):
    monkeypatch.setenv(ENV_LOCKED_FOLDERS, "Mailbox, Inbox ,Archive")
    assert locked_folders() == ("Mailbox", "Inbox", "Archive")


def test_empty_locked_folders_means_nothing_is_locked(monkeypatch):
    monkeypatch.setenv(ENV_LOCKED_FOLDERS, "")
    assert locked_folders() == ()
