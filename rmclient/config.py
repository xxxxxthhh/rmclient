"""入口与凭据。

凭据只从磁盘读，绝不进日志、不进 git（CLAUDE.md §凭据）。
"""

from dataclasses import dataclass, field
from pathlib import Path

# 只能走 Cloudflare 隧道域名：direct 域名对 /ui* 固定 403（REPORT §4.8）。
# 注意 CF 免费边缘有 100MB 单请求上限，大文件导出可能撞（REPORT/CLAUDE.md 纪律 6）。
BASE_URL = "https://rmfakecloud.example.com"

# 暂与 paperpal 共用账户（rmfakecloud 文档树按 user 隔离）。paperpal 仓库只读。
_PAPERPAL = Path.home() / "Documents/paperpal"
ENV_FILE = _PAPERPAL / ".env"
PASSWORD_FILE = _PAPERPAL / "secrets/rmfakecloud_password"

_USER_KEY = "RMFAKECLOUD_USER"

# 本地状态（删除记录）。仓库内的 var/ 已在 .gitignore，不进 git。
VAR_DIR = Path(__file__).resolve().parent.parent / "var"
DELETED_FILE = VAR_DIR / "deleted.json"


@dataclass(frozen=True)
class Credentials:
    user: str
    # repr=False：防止 print(creds) / 异常回溯把密码带进日志。
    password: str = field(repr=False)


def load_credentials(
    env_file: Path = ENV_FILE, password_file: Path = PASSWORD_FILE
) -> Credentials:
    """用户名取 .env 的 RMFAKECLOUD_USER，密码取密码文件。

    密码文件末尾带换行（32 字节含 \\n），必须 .strip()，否则登录失败。
    """
    user = ""
    for line in env_file.read_text().splitlines():
        if line.startswith(f"{_USER_KEY}="):
            user = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not user:
        raise RuntimeError(f"{_USER_KEY} not found in {env_file}")
    password = password_file.read_text().strip()
    if not password:
        raise RuntimeError(f"empty password in {password_file}")
    return Credentials(user, password)
