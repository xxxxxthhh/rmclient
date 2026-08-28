"""i18n 的离线测试：字典对齐、页面接线、语言切换控件。不打真实云，不跑浏览器。

STRINGS 在 i18n.js 里是严格 JSON（双引号键值、无注释、无尾逗号），所以这里能
直接 json.loads 出来逐键比对——漏翻一门语言在测试里就红，不用等用户看见。
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rmclient.journal import DeletionJournal
from rmclient.web import app, get_client, get_journal
from tests.fixtures import logged_in

PAGES = ("/", "/tree", "/preview/b1")


@pytest.fixture
def web(tmp_path):
    client, _ = logged_in()
    app.dependency_overrides[get_client] = lambda: client
    app.dependency_overrides[get_journal] = lambda: DeletionJournal(tmp_path / "deleted.json")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def source(web):
    return web.get("/static/i18n.js").text


def strings(source: str) -> dict:
    """i18n.js 里的 STRINGS 字面量。JSON 岛的边界就是 `};` 顶格那一行。"""
    start = source.index("{", source.index("const STRINGS"))
    return json.loads(source[start : source.index("\n};", start) + 2])


# ---- 字典 ----------------------------------------------------------


def test_strings_is_served_and_parses_as_strict_json(web):
    r = web.get("/static/i18n.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert r.headers["cache-control"] == "no-store"   # 改完刷新就见，同 app.css
    assert set(strings(r.text)) >= {"en", "zh"}


def test_every_language_has_exactly_the_same_keys(source):
    table = strings(source)
    english = set(table["en"])
    assert len(english) > 50, "解析出来的键太少，八成是 JSON 岛的边界找错了"
    for code, dictionary in table.items():
        assert set(dictionary) == english, f"{code} 的键与 en 不一致"


def test_every_language_names_itself_for_the_switcher(source):
    for code, dictionary in strings(source).items():
        assert dictionary["lang.label"].strip(), f"{code} 缺 lang.label"


def test_placeholders_match_across_languages(source):
    """{name} 这类占位符漏一个就是运行时缺字段——en 是权威，其它照抄。"""
    table = strings(source)
    assert len(table["en"]) > 50
    holes = lambda text: set(re.findall(r"\{(\w+)\}", text))
    for code, dictionary in table.items():
        for key, value in dictionary.items():
            assert holes(value) == holes(table["en"][key]), f"{code} 的 {key} 占位符对不上"


def test_english_is_the_default_and_chinese_is_auto_detected(source):
    assert "localStorage.getItem(LANG_KEY)" in source
    assert "nav.startsWith('zh')" in source and "return 'en';" in source
    assert "document.documentElement.lang = LANG" in source


def test_document_types_are_data_and_never_translated(web):
    """徽章里的 notebook/epub/pdf 是服务端给的类型值：直接渲染，不过字符串表。"""
    tree = web.get("/tree").text
    assert "el('span', 'badge', node.type)" in tree          # 树上的类型徽章
    assert "item.type || '?'" in tree                        # 重名报告里的类型
    preview = web.get("/preview/b1").text
    assert "t('preview.kind', {type: d.fileType," in preview  # 类型是参数，不是被翻译的词


# ---- 三个页面 ------------------------------------------------------


@pytest.mark.parametrize("path", PAGES)
def test_every_page_loads_the_shared_string_table(web, path):
    html = web.get(path).text
    assert '<script src="/static/i18n.js"></script>' in html
    assert '<html lang="en">' in html           # 默认英文，i18n.js 再按语言改写


@pytest.mark.parametrize("path", PAGES)
def test_every_page_has_the_language_switcher_in_the_topbar(web, path):
    head = web.get(path).text
    head = head[: head.index("</header>")]
    assert 'id="langpick"' in head


@pytest.mark.parametrize("path", PAGES)
def test_every_page_fills_its_static_text_from_the_table(web, path):
    assert 'data-i18n="' in web.get(path).text


def test_the_switcher_is_generated_from_the_table_not_hardcoded(source):
    """加一门语言 = 加一个字典对象，切换按钮自己长出来。"""
    assert "Object.keys(STRINGS)" in source
    assert "localStorage.setItem(LANG_KEY, code)" in source
    assert "rmclient:lang" in source


@pytest.mark.parametrize("path", ("/tree", "/preview/b1"))
def test_pages_with_rendered_text_redraw_on_a_language_change(web, path):
    assert "rmclient:lang" in web.get(path).text


def test_a_language_switch_does_not_overwrite_the_notebook_name(web):
    """可见名不归字符串表管：标题和面包屑拿到名字后必须摘掉 data-i18n，
    否则换语言时 applyStatic 会把「Book One」刷回「读取中…」（真机上撞到过）。"""
    html = web.get("/preview/b1").text
    assert "document.querySelector('title').removeAttribute('data-i18n')" in html
    assert "crumb.removeAttribute('data-i18n')" in html


def test_a_language_switch_drops_text_it_cannot_redraw(web):
    """已弹出的 toast 和重名报告是上一门语言的：换语言时收掉，别留半中半英的一屏。"""
    html = web.get("/tree").text
    block = html[html.index("rmclient:lang") :][:400]
    assert "getElementById('toasts').textContent = ''" in block
    assert "getElementById('dups').hidden = true" in block


def test_every_key_used_by_the_pages_exists_in_the_table(web, source):
    table = strings(source)
    for path in PAGES:
        html = web.get(path).text
        used = set(re.findall(r"\bt\('([\w.]+)'", html))
        used |= set(re.findall(r'data-i18n(?:-[a-z-]+)?="([\w.]+)"', html))
        assert len(used) > 5, f"{path} 没抓到几个 key——正则八成失效了，测试会一直空过"
        missing = sorted(used - set(table["en"]))
        assert not missing, f"{path} 用了字符串表里没有的 key: {missing}"


def test_server_error_reasons_all_have_a_localised_headline(web, source):
    """web.py 抛的每个 reason 码，前端都得有对应的主提示（服务端 message 作详情）。"""
    import rmclient.web as web_module

    reasons = set(re.findall(r'"reason": "(\w+)"', Path(web_module.__file__).read_text()))
    english = strings(source)["en"]
    assert reasons, "web.py 里应该找得到 reason 码"
    for reason in reasons:
        assert f"error.{reason}" in english, f"reason={reason} 没有本地化主提示"
    assert "httpError(" in web.get("/tree").text and "httpError(" in web.get("/").text
