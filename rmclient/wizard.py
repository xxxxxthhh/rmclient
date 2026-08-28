"""`rmclient setup`：问三个问题，写配置，然后真连一次确认它是通的。

存在的理由是降门槛：非开发者不该为了用这个工具去学环境变量怎么导出。写完之后
立刻 login + list_tree —— 「配置写好了」和「配置是对的」是两件事，只报告前者
等于把排错推给用户。

密码永远单独一个文件（0600），config.toml 里只留路径。向导本身不打印密码，
报错也不带（config.ConfigError 的约定）。
"""

from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path

import httpx

from .api import RmApiError, RmClient
from .config import (
    ENV_PASSWORD,
    ENV_PASSWORD_FILE,
    ENV_URL,
    ENV_USER,
    ConfigError,
    config_file,
    default_password_file,
    read_config,
)

# env 这一层压着配置文件（config 模块的优先级）。设了 env 还跑向导，
# 写出来的东西不会生效——那种沉默最坑人，所以写完要提醒一句。
_SHADOWING_ENV = (ENV_URL, ENV_USER, ENV_PASSWORD, ENV_PASSWORD_FILE)


class Abort(RuntimeError):
    """没法交互（--non-interactive、或者 stdin 不是终端）。"""


def _ask(label: str, current: str = "") -> str:
    """问一个可见的值。有现值时回车表示保留；没有现值就一直问到给出非空。"""
    while True:
        prompt = f"{label} [{current}]: " if current else f"{label}: "
        try:
            answer = input(prompt).strip()
        except EOFError as exc:
            raise Abort("no terminal to ask on") from exc
        if answer:
            return answer
        if current:
            return current
        print("  (required)", file=sys.stderr)


def _ask_secret(label: str, *, has_current: bool) -> str | None:
    """问密码。回车 = 保留现有的那份，用 None 表示——别拿哨兵字符串占坑：
    密码正好就是那个词的人会被静默地不写文件，然后收到一句莫名其妙的报错。"""
    prompt = f"{label} [keep current]: " if has_current else f"{label}: "
    while True:
        try:
            answer = getpass.getpass(prompt).strip()
        except EOFError as exc:
            raise Abort("no terminal to ask on") from exc
        if answer:
            return answer
        if has_current:
            return None
        print("  (required)", file=sys.stderr)


def _toml_string(value: str) -> str:
    """TOML 基本字符串的转义规则和 JSON 的一致，借 json 来做，不引依赖。"""
    return json.dumps(value)


def write_config(url: str, user: str, password: str | None, *,
                 password_file: Path | None = None) -> tuple[Path, Path]:
    """写 config.toml 与密码文件，返回两者的路径。password=None 表示不动密码。"""
    target = password_file or default_password_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    if password is not None:
        # 先 touch 再 chmod 再写：别让密码有哪怕一瞬间躺在 0644 的文件里。
        target.touch(mode=0o600, exist_ok=True)
        target.chmod(0o600)
        target.write_text(password + "\n")

    lines = [
        "# rmclient configuration — written by `rmclient setup`.",
        "# The password is NOT here; it lives in its own file (mode 600).",
        f"url = {_toml_string(url.rstrip('/'))}",
        f"user = {_toml_string(user)}",
    ]
    if password_file is not None:
        lines.append(f"password_file = {_toml_string(str(target))}")
    path = config_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path, target


def run(non_interactive: bool = False) -> int:
    if non_interactive:
        print(
            "`rmclient setup` is interactive. For scripts, set "
            f"{ENV_URL}, {ENV_USER} and one of {ENV_PASSWORD} / {ENV_PASSWORD_FILE} instead.",
            file=sys.stderr,
        )
        return 2

    try:
        existing = read_config()
    except ConfigError as exc:
        # 坏掉的旧配置不该挡住重新配置——说一句，然后当作空的重来。
        print(f"note: ignoring the current config ({exc})", file=sys.stderr)
        existing = {}

    print(f"Configuring rmclient. Values are written to {config_file()}.")
    if existing:
        print("Press Enter to keep a current value.")

    try:
        url = _ask("Server URL", str(existing.get("url", "")))
        user = _ask("Email", str(existing.get("user", "")))
        has_password = default_password_file().is_file() or bool(existing.get("password_file"))
        password = _ask_secret("Password", has_current=has_password)
    except Abort:
        print(
            "cannot prompt: stdin is not a terminal. Set "
            f"{ENV_URL}, {ENV_USER} and one of {ENV_PASSWORD} / {ENV_PASSWORD_FILE} instead.",
            file=sys.stderr,
        )
        return 2

    if not url.startswith(("http://", "https://")):
        url = "https://" + url          # 光贴主机名是最常见的输入，别为此报错
    config_path, password_path = write_config(url, user, password)
    print(f"\nwrote {config_path}")
    if password is not None:
        print(f"wrote {password_path} (mode 600)")

    if shadowing := [key for key in _SHADOWING_ENV if os.environ.get(key)]:
        print(f"warning: {', '.join(shadowing)} is set in your environment and takes "
              "precedence over this file — unset it or rmclient will keep using it.",
              file=sys.stderr)

    return _verify()


def _verify() -> int:
    """真连一次。走的是 load_credentials 的正路，所以顺带证明刚写的配置读得回来。"""
    print("\nchecking the connection…")
    try:
        with RmClient() as client:
            client.login()
            tree = client.list_tree()
    except ConfigError as exc:
        print(f"the configuration is still incomplete: {exc}", file=sys.stderr)
        return 2
    except RmApiError as exc:
        # 配置已经写下了：告诉用户改哪儿，别让他们从头再来一遍。
        print(f"could not sign in: HTTP {exc.status} {exc.error or exc.body}", file=sys.stderr)
        print(f"the settings are saved in {config_file()} — fix them and run "
              "`rmclient setup` again.", file=sys.stderr)
        return 1
    except httpx.HTTPError as exc:
        # httpx 的传输错误不是 OSError，得单独接——不然拼错域名的人收到的是
        # 一整页 traceback，而这正是向导要替他们挡掉的东西。
        print(f"could not reach the server: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("check the URL (and that the server is up), then run `rmclient setup` again.",
              file=sys.stderr)
        return 1

    print(f"✓ signed in. The root holds {len(tree.entries)} entries "
          f"({len(tree.trash)} in the trash).")
    print("\nnext:  rmclient serve --open")
    return 0
