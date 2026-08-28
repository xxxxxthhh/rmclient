"""服务器地址、凭据、锁定目录。

三层，**按来源整体取用**，不跨层拼装：

    1. 环境变量        任何部署都能用，CI / 容器里最直接
    2. 配置文件        ~/.config/rmclient/config.toml（XDG_CONFIG_HOME 优先），
                       由 `rmclient setup` 写出，普通用户走这条
    3. paperpal 回落   本机原有布局（见 CLAUDE.md），只在那些文件确实存在时才用

    RMCLIENT_URL             服务器地址（含协议）
    RMCLIENT_USER            登录用户名（邮箱）
    RMCLIENT_PASSWORD        密码；或者
    RMCLIENT_PASSWORD_FILE   存密码的文件（读入后 strip，二选一）
    RMCLIENT_LOCKED_FOLDERS  锁定的根级目录名，逗号分隔，默认 Mailbox
    RMCLIENT_DATA_DIR        删除记录落盘的位置（默认 XDG state 目录）

「整体取用」是有教训的：半套 env 配置绝不能悄悄借用下一层的凭据去连另一台
服务器。配置文件同理——文件在场但没写 user 就报错，不往 paperpal 那层漏。

密码永远单独存一个文件，config.toml 里出现明文密码直接报错。
凭据只从环境或磁盘读，绝不进日志、不进 git（CLAUDE.md §凭据）。
"""

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ENV_URL = "RMCLIENT_URL"
ENV_USER = "RMCLIENT_USER"
ENV_PASSWORD = "RMCLIENT_PASSWORD"
ENV_PASSWORD_FILE = "RMCLIENT_PASSWORD_FILE"
ENV_LOCKED_FOLDERS = "RMCLIENT_LOCKED_FOLDERS"
ENV_DATA_DIR = "RMCLIENT_DATA_DIR"

# 默认锁定的根级目录：paperpal 的信箱。整树只读，写操作一律拒（CLAUDE.md 纪律 1）。
DEFAULT_LOCKED_FOLDERS = ("Mailbox",)

# ---- 向后兼容的回落（本机原有用法，细节见 CLAUDE.md）----
# 服务器域名不写进仓库：从 paperpal/.env 的 DOMAIN 键运行时读取。
_PAPERPAL = Path.home() / "Documents/paperpal"
FALLBACK_ENV_FILE = _PAPERPAL / ".env"
FALLBACK_PASSWORD_FILE = _PAPERPAL / "secrets/rmfakecloud_password"
_FALLBACK_USER_KEY = "RMFAKECLOUD_USER"

# ---- 目录（全部在调用时算，不在 import 时定死）----
#
# 装成 wheel 之后 __file__ 在 site-packages 里，任何「包目录旁边」的路径都是错的：
# uvx 跑起来会写进 uv 的缓存目录，`uv cache clean` 一抹就没。所以状态走 XDG。


def _xdg(env_key: str, default: str) -> Path:
    base = os.environ.get(env_key, "").strip()
    return (Path(base) if base else Path.home() / default) / "rmclient"


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config")


def config_file() -> Path:
    return config_dir() / "config.toml"


def default_password_file() -> Path:
    """setup 默认把密码写这儿。config.toml 里只存路径，不存密码本身。"""
    return config_dir() / "password"


def state_dir() -> Path:
    if override := os.environ.get(ENV_DATA_DIR, "").strip():
        return Path(override).expanduser()
    return _xdg("XDG_STATE_HOME", ".local/state")


def deleted_file() -> Path:
    """删除记录。是本地状态不是配置，所以在 state 目录而不是 config 目录。"""
    return state_dir() / "deleted.json"


_HOWTO = (
    "run `rmclient setup`, or set "
    f"{ENV_URL}, {ENV_USER} and one of {ENV_PASSWORD} / {ENV_PASSWORD_FILE}, "
    "to point rmclient at your rmfakecloud server"
)


class ConfigError(RuntimeError):
    """没配够，或者配得自相矛盾。消息里绝不带密码本身。"""


@dataclass(frozen=True)
class Credentials:
    user: str
    # repr=False：防止 print(creds) / 异常回溯把密码带进日志。
    password: str = field(repr=False)


def read_config() -> dict:
    """config.toml 的内容；文件不在就是空字典。

    明文密码在这里被硬拒：写进 config.toml 的密码会跟着任何一次误分享走掉，
    而单独的密码文件至少是 600 的。
    """
    path = config_file()
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        return {}
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    try:
        data = tomllib.loads(raw.decode())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc
    if "password" in data:
        raise ConfigError(
            f"{path} must not contain a plaintext password — "
            "put it in its own file and point `password_file` at it"
        )
    return data


def _fallback_available() -> bool:
    """本机原有的 paperpal 布局还在不在。"""
    return FALLBACK_ENV_FILE.is_file() and FALLBACK_PASSWORD_FILE.is_file()


def _fallback_base_url() -> str | None:
    """本机布局 .env 里的 DOMAIN=<隧道主机名>。域名只活在本地配置，不进仓库。"""
    for line in FALLBACK_ENV_FILE.read_text().splitlines():
        if line.startswith("DOMAIN="):
            host = line.split("=", 1)[1].strip().strip('"').strip("'")
            if host:
                return host.rstrip("/") if host.startswith("http") else f"https://{host}"
    return None


def base_url() -> str:
    """环境变量 → 配置文件 → paperpal 回落；一层都不成立就报错。"""
    if url := os.environ.get(ENV_URL, "").strip():
        return url.rstrip("/")
    if url := str(read_config().get("url", "")).strip():
        return url.rstrip("/")
    if _fallback_available() and (url := _fallback_base_url()):
        return url
    raise ConfigError(f"no server URL configured — {_HOWTO}")


def locked_folders() -> tuple[str, ...]:
    """锁定的根级目录名。空串表示一个都不锁（自己的部署要清楚这意味着什么）。"""
    raw = os.environ.get(ENV_LOCKED_FOLDERS)
    if raw is None:
        return DEFAULT_LOCKED_FOLDERS
    return tuple(name.strip() for name in raw.split(",") if name.strip())


def load_credentials() -> Credentials:
    """环境变量 → 配置文件 → paperpal 回落。**按来源整体取用**，不跨层拼装。"""
    if any(os.environ.get(key) for key in (ENV_USER, ENV_PASSWORD, ENV_PASSWORD_FILE)):
        return _credentials_from_env()
    data = read_config()
    if data:
        # 配置文件在场就由它说了算。半套配置不许往下漏：否则 config.toml 指着
        # 服务器 A，凭据却悄悄用了 paperpal 那套 B 的——正是 env 那层防的同一件事。
        if not str(data.get("user", "")).strip():
            raise ConfigError(f"{config_file()} has no `user` — run `rmclient setup`")
        return _credentials_from_config(data)
    if _fallback_available():
        return _credentials_from_fallback()
    raise ConfigError(f"no credentials configured — {_HOWTO}")


def _credentials_from_config(data: dict) -> Credentials:
    """config.toml 的 user + password_file（不给就用默认那份）。"""
    raw = str(data.get("password_file", "")).strip()
    path = Path(raw).expanduser() if raw else default_password_file()
    try:
        # 密码文件多半带结尾换行，不 strip 会登录失败。
        password = path.read_text().strip()
    except OSError as exc:
        raise ConfigError(f"cannot read the password file {path}: {exc}") from exc
    if not password:
        raise ConfigError(f"empty password in {path}")
    return Credentials(str(data["user"]).strip(), password)


def _credentials_from_env() -> Credentials:
    user = os.environ.get(ENV_USER, "").strip()
    if not user:
        raise ConfigError(f"{ENV_USER} is empty — {_HOWTO}")

    password = os.environ.get(ENV_PASSWORD)
    password_file = os.environ.get(ENV_PASSWORD_FILE)
    if password and password_file:
        raise ConfigError(f"set either {ENV_PASSWORD} or {ENV_PASSWORD_FILE}, not both")
    if password_file:
        # 密码文件多半带结尾换行，不 strip 会登录失败（REPORT 的老教训）。
        password = Path(password_file).read_text().strip()
    elif password is None:
        raise ConfigError(f"{ENV_USER} is set but neither {ENV_PASSWORD} nor {ENV_PASSWORD_FILE} is")
    # 环境变量里的密码按原样用（首尾空格也可能是密码的一部分），但整串都是空白
    # 就当没配——那是漏配，不是密码。
    if not password.strip():
        raise ConfigError("the configured password is empty")
    return Credentials(user, password)


def _credentials_from_fallback() -> Credentials:
    user = ""
    for line in FALLBACK_ENV_FILE.read_text().splitlines():
        if line.startswith(f"{_FALLBACK_USER_KEY}="):
            user = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not user:
        raise ConfigError(f"{_FALLBACK_USER_KEY} not found in {FALLBACK_ENV_FILE} — {_HOWTO}")
    password = FALLBACK_PASSWORD_FILE.read_text().strip()
    if not password:
        raise ConfigError(f"empty password in {FALLBACK_PASSWORD_FILE}")
    return Credentials(user, password)
