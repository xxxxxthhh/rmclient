"""wheel 内容的离线断言。

这条是给 PyPI 那条路守门的：HTML/CSS/JS 是运行时资源，漏掉一个 wheel 照样能装、
照样能 import，只有真去开页面时才 500——而那时候人已经在 `uvx rmclient serve` 了。
纯 Python 的测试跑不出这个问题，只能真构建一次再拆开看。

构建走 `uv build --offline`：uv sync 时为了可编辑安装本项目已经把构建后端拉进
缓存了，所以这一步不出网。拉不到（没有 uv / 缓存是冷的）就跳过，并且把跳过原因
写清楚——CI 里静默跳过才是真正的失败模式。
"""

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PAGES = REPO / "rmclient" / "pages"


def _build_wheel(out_dir: Path) -> Path:
    if shutil.which("uv") is None:
        pytest.skip("wheel packaging NOT verified: uv is not on PATH")
    result = subprocess.run(
        ["uv", "build", "--wheel", "--offline", "--out-dir", str(out_dir)],
        cwd=REPO, capture_output=True, text=True, timeout=600,
    )
    if result.returncode != 0:
        pytest.skip("wheel packaging NOT verified: offline `uv build` failed "
                    f"(cold build cache?): {result.stderr.strip()[-300:]}")
    wheels = list(out_dir.glob("*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


@pytest.fixture(scope="module")
def wheel_names(tmp_path_factory) -> set[str]:
    wheel = _build_wheel(tmp_path_factory.mktemp("dist"))
    return set(zipfile.ZipFile(wheel).namelist())


def test_the_wheel_ships_every_page_asset(wheel_names):
    """pages/ 下的每一个文件都得进 wheel——少一个，装完就是个开不了页面的壳。"""
    on_disk = {f"rmclient/pages/{p.name}" for p in PAGES.iterdir() if p.is_file()}
    assert on_disk, "pages/ 不该是空的"
    assert on_disk <= wheel_names, sorted(on_disk - wheel_names)


def test_the_page_assets_are_the_ones_we_expect(wheel_names):
    """加了新页面/新资源却忘了想打包这回事时，这条会提醒一句。"""
    shipped = {n.rsplit("/", 1)[-1] for n in wheel_names if n.startswith("rmclient/pages/")}
    assert shipped == {"app.css", "i18n.js", "preview.html", "push.html", "tree.html"}


def test_the_wheel_ships_the_demo_so_uvx_can_run_it(wheel_names):
    """`uvx rmclient demo` 不克隆仓库：demo 与数据集必须在包里。"""
    assert "rmclient/demo.py" in wheel_names
    assert "rmclient/wizard.py" in wheel_names


def test_the_wheel_does_not_ship_tests_or_local_state(wheel_names):
    strays = [n for n in wheel_names
              if n.startswith(("tests/", "scripts/", "spike/", "var/"))]
    assert strays == []


def test_the_console_script_is_declared(wheel_names):
    entry = [n for n in wheel_names if n.endswith("entry_points.txt")]
    assert entry, "wheel 里没有 entry_points.txt，`rmclient` 命令就不存在"
