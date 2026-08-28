"""配置解析的离线单测：三层来源的优先级、回落条件、报错文案、锁定目录解析。"""

import pytest

from rmclient import config
from rmclient.config import (
    ENV_DATA_DIR,
    ENV_LOCKED_FOLDERS,
    ENV_PASSWORD,
    ENV_PASSWORD_FILE,
    ENV_URL,
    ENV_USER,
    ConfigError,
    base_url,
    config_file,
    deleted_file,
    default_password_file,
    load_credentials,
    locked_folders,
    read_config,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    """每个测试从零开始：清掉所有 RMCLIENT_*，XDG 指到空目录，回落路径指到空目录。

    XDG 一定要隔离：否则开发机上真有一份 ~/.config/rmclient/config.toml 时，
    「什么都没配」这类用例会读到它，测出来的东西就不是代码而是这台机器了。
    """
    for key in (ENV_URL, ENV_USER, ENV_PASSWORD, ENV_PASSWORD_FILE, ENV_LOCKED_FOLDERS,
                ENV_DATA_DIR):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setattr(config, "FALLBACK_ENV_FILE", tmp_path / "nope/.env")
    monkeypatch.setattr(config, "FALLBACK_PASSWORD_FILE", tmp_path / "nope/password")


@pytest.fixture
def config_toml(tmp_path):
    """写一份 config.toml（外加密码文件），返回写入函数。"""
    def write(body: str, password: str | None = "config-secret") -> None:
        path = config_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
        if password is not None:
            default_password_file().write_text(password + "\n")
    return write


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


# ---- 配置文件（第二层）---------------------------------------------


def test_config_file_supplies_url_and_credentials(config_toml):
    config_toml('url = "https://cfg.example.test/"\nuser = "cfg@example.test"\n')
    assert base_url() == "https://cfg.example.test"        # 结尾斜杠照样去掉
    creds = load_credentials()
    assert (creds.user, creds.password) == ("cfg@example.test", "config-secret")


def test_environment_beats_the_config_file(monkeypatch, config_toml):
    config_toml('url = "https://cfg.example.test"\nuser = "cfg@example.test"\n')
    monkeypatch.setenv(ENV_URL, "https://env.example.test")
    monkeypatch.setenv(ENV_USER, "env@example.test")
    monkeypatch.setenv(ENV_PASSWORD, "env-secret")
    assert base_url() == "https://env.example.test"
    assert load_credentials() == config.Credentials("env@example.test", "env-secret")


def test_the_config_file_beats_the_paperpal_fallback(config_toml, fallback):
    config_toml('url = "https://cfg.example.test"\nuser = "cfg@example.test"\n')
    assert base_url() == "https://cfg.example.test"
    assert load_credentials().user == "cfg@example.test"


def test_the_fallback_still_works_when_there_is_no_config_file(fallback):
    """本机现状零影响：没有 config.toml 时，paperpal 那条路一点没变。"""
    assert base_url() == "https://fallback.example.test"
    assert load_credentials().user == "fallback@example.test"


def test_a_config_file_without_a_user_never_borrows_fallback_credentials(config_toml, fallback):
    # 半套配置指着服务器 A，凭据却用了 paperpal 那套 B 的——正是要防的事故。
    config_toml('url = "https://cfg.example.test"\n', password=None)
    with pytest.raises(ConfigError, match="has no `user`"):
        load_credentials()


def test_a_plaintext_password_in_the_config_file_is_refused(config_toml):
    config_toml('user = "cfg@example.test"\npassword = "s3cret"\n')
    with pytest.raises(ConfigError, match="password_file"):
        load_credentials()
    assert "s3cret" not in str(pytest.raises(ConfigError, read_config).value)


def test_a_custom_password_file_path_is_honoured(config_toml, tmp_path):
    elsewhere = tmp_path / "somewhere" / "pw"
    elsewhere.parent.mkdir()
    elsewhere.write_text("elsewhere-secret\n")
    config_toml(f'user = "cfg@example.test"\npassword_file = "{elsewhere}"\n', password=None)
    assert load_credentials().password == "elsewhere-secret"


def test_a_missing_password_file_says_which_one(config_toml):
    config_toml('user = "cfg@example.test"\n', password=None)
    with pytest.raises(ConfigError) as exc:
        load_credentials()
    assert str(default_password_file()) in str(exc.value)


def test_broken_toml_is_reported_not_swallowed(config_toml):
    config_toml("this is not = = toml\n", password=None)
    with pytest.raises(ConfigError, match="not valid TOML"):
        read_config()


def test_no_config_file_reads_as_empty():
    assert read_config() == {}


# ---- 目录解析 ------------------------------------------------------


def test_config_and_state_live_under_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert config_file() == tmp_path / "cfg/rmclient/config.toml"
    assert default_password_file() == tmp_path / "cfg/rmclient/password"
    assert deleted_file() == tmp_path / "state/rmclient/deleted.json"


def test_the_defaults_are_under_the_home_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: tmp_path))
    assert config_file() == tmp_path / ".config/rmclient/config.toml"
    assert deleted_file() == tmp_path / ".local/state/rmclient/deleted.json"


def test_the_journal_never_lands_next_to_the_installed_package(monkeypatch, tmp_path):
    """装成 wheel 后包目录在 site-packages 里，往那儿写记录是错的（uvx 会丢）。"""
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(config.Path, "home", classmethod(lambda cls: tmp_path))
    package_dir = config.Path(config.__file__).resolve().parent
    assert package_dir not in deleted_file().parents


def test_the_data_dir_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path / "elsewhere"))
    assert deleted_file() == tmp_path / "elsewhere/deleted.json"


def test_the_journal_defaults_to_the_state_directory(monkeypatch, tmp_path):
    from rmclient.journal import DeletionJournal

    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path / "j"))
    assert DeletionJournal().path == tmp_path / "j/deleted.json"
