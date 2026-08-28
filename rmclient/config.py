"""服务器地址、凭据、锁定目录。

优先读环境变量，任何 rmfakecloud 部署都能用：

    RMCLIENT_URL             服务器地址（含协议）
    RMCLIENT_USER            登录用户名（邮箱）
    RMCLIENT_PASSWORD        密码；或者
    RMCLIENT_PASSWORD_FILE   存密码的文件（读入后 strip，二选一）
    RMCLIENT_LOCKED_FOLDERS  锁定的根级目录名，逗号分隔，默认 Mailbox

一个都没设时回落到本机原有的 paperpal 布局（见 CLAUDE.md），且**只在那些文件
确实存在时**才回落——否则直接报错告诉你该设哪几个变量，绝不静默连错服务器。

凭据只从环境或磁盘读，绝不进日志、不进 git（CLAUDE.md §凭据）。
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

ENV_URL = "RMCLIENT_URL"
ENV_USER = "RMCLIENT_USER"
ENV_PASSWORD = "RMCLIENT_PASSWORD"
ENV_PASSWORD_FILE = "RMCLIENT_PASSWORD_FILE"
ENV_LOCKED_FOLDERS = "RMCLIENT_LOCKED_FOLDERS"

# 默认锁定的根级目录：paperpal 的信箱。整树只读，写操作一律拒（CLAUDE.md 纪律 1）。
DEFAULT_LOCKED_FOLDERS = ("Mailbox",)

# ---- 向后兼容的回落（本机原有用法，细节见 CLAUDE.md）----
FALLBACK_BASE_URL = "https://rmfakecloud.example.com"
_PAPERPAL = Path.home() / "Documents/paperpal"
FALLBACK_ENV_FILE = _PAPERPAL / ".env"
FALLBACK_PASSWORD_FILE = _PAPERPAL / "secrets/rmfakecloud_password"
_FALLBACK_USER_KEY = "RMFAKECLOUD_USER"

# 本地状态（删除记录）。仓库内的 var/ 已在 .gitignore，不进 git。
VAR_DIR = Path(__file__).resolve().parent.parent / "var"
DELETED_FILE = VAR_DIR / "deleted.json"

_HOWTO = (
    f"set {ENV_URL}, {ENV_USER} and one of {ENV_PASSWORD} / {ENV_PASSWORD_FILE} "
    "to point rmclient at your rmfakecloud server"
)


class ConfigError(RuntimeError):
    """没配够，或者配得自相矛盾。消息里绝不带密码本身。"""


@dataclass(frozen=True)
class Credentials:
    user: str
    # repr=False：防止 print(creds) / 异常回溯把密码带进日志。
    password: str = field(repr=False)


def _fallback_available() -> bool:
    """本机原有的 paperpal 布局还在不在。"""
    return FALLBACK_ENV_FILE.is_file() and FALLBACK_PASSWORD_FILE.is_file()


def base_url() -> str:
    """环境变量优先；没有就回落，回落不成立直接报错。"""
    if url := os.environ.get(ENV_URL, "").strip():
        return url.rstrip("/")
    if _fallback_available():
        return FALLBACK_BASE_URL
    raise ConfigError(f"{ENV_URL} is not set and no local fallback config exists — {_HOWTO}")


def locked_folders() -> tuple[str, ...]:
    """锁定的根级目录名。空串表示一个都不锁（自己的部署要清楚这意味着什么）。"""
    raw = os.environ.get(ENV_LOCKED_FOLDERS)
    if raw is None:
        return DEFAULT_LOCKED_FOLDERS
    return tuple(name.strip() for name in raw.split(",") if name.strip())


def load_credentials() -> Credentials:
    """环境变量优先，否则回落到 paperpal 布局。"""
    if any(os.environ.get(key) for key in (ENV_USER, ENV_PASSWORD, ENV_PASSWORD_FILE)):
        return _credentials_from_env()
    if _fallback_available():
        return _credentials_from_fallback()
    raise ConfigError(f"no credentials configured — {_HOWTO}")


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
