# rmclient

跑在本机的 [rmfakecloud](https://github.com/ddvk/rmfakecloud) 内容管理客户端：
推书到 reMarkable、整理文档树、预览笔记、取回原件、查重名——全部在自己电脑上
完成，通过服务器的 `/ui/api` 端点通信。

*[English](README.md)*

服务端一行不动，设备端什么也不装：rmclient 只是它的又一个 API 消费者。整个东西
是一个 Python 进程，Web 界面是纯 HTML/CSS/JS，无构建链、无外部资源，离线可用。

**状态**：在 rmfakecloud **v0.0.31** 上实测可用，也只在这个版本上测过。端点契约
与各种坑记在 [`spike/REPORT.md`](spike/REPORT.md)。

## 有什么

| 页面 | 干什么 |
|---|---|
| `/` | 把 epub/pdf/rmdoc 拖进来，选目标目录，上传。逐文件进度与结果。 |
| `/tree` | 整棵文档树：搜索、排序、新建/重命名/移动/删除（单个或多选）、往任意目录上传、下载原件（也可取整包 `.rmdoc`——设备端的批注在包里）、重名报告。 |
| `/preview/<id>` | 把笔记逐页渲染成 SVG，翻页浏览，整本导出 PDF。 |

CLI 负责推书：

```bash
rmclient push book.epub                    # 传到根级
rmclient push book.epub --to Books/CS      # 按树上的可见名路径指定目录
rmclient push book.epub --to Books --force # 明知重名也要再传一份
rmclient serve --port 8000                 # 起 Web 界面
```

## 快速上手

需要 Python 3.14 和 [uv](https://docs.astral.sh/uv/)。

```bash
git clone <本仓库> && cd rmclient
uv sync

export RMCLIENT_URL=https://cloud.example.com
export RMCLIENT_USER=you@example.com
export RMCLIENT_PASSWORD_FILE=~/.config/rmclient/password   # 或者 RMCLIENT_PASSWORD

uv run rmclient serve            # → http://127.0.0.1:8000
```

动手之前先跑个只读的确认能连通：

```bash
uv run python scripts/dump_tree.py    # 打印整棵树，含回收站
```

## 配置

配置全部走环境变量，没有配置文件。

| 变量 | 默认 | 含义 |
|---|---|---|
| `RMCLIENT_URL` | — | rmfakecloud 地址，要带协议。结尾斜杠会被忽略。 |
| `RMCLIENT_USER` | — | 登录邮箱。 |
| `RMCLIENT_PASSWORD` | — | 密码，按原样使用。 |
| `RMCLIENT_PASSWORD_FILE` | — | 存密码的文件路径，读入后 strip。与 `RMCLIENT_PASSWORD` **二选一**，不能都设。 |
| `RMCLIENT_LOCKED_FOLDERS` | `Mailbox` | 要保护的**根级**目录名，逗号分隔。设成空串表示一个都不锁。 |

一个都不设时，rmclient 会回落到它原始部署的本机布局（细节在 `CLAUDE.md`），
且只在那些文件确实存在时才回落。否则直接拒绝启动并告诉你该设哪几个变量——
绝不会悄悄连到一个你没想到的地方去。

凭据只从环境变量或磁盘读，不进日志、不打印、不进仓库。

## 界面语言

Web 界面自带**英文（默认）与中文**，语言是每个浏览器自己的选择，服务端不受影响。

- 三个页面的顶栏都有 `EN / 中文` 切换。选择存在 `localStorage` 的
  `rmclient.lang` 里，三页一致。
- 没存过时按 `navigator.language` 判断：`zh` 开头给中文，其余给英文。
- CLI 只有英文；服务端错误消息也是英文。页面按错误的 `reason` 码给本地化主提示，
  下面附上服务端自己的 `message` 作详情。
- 徽章里的文档类型（`notebook` / `epub` / `pdf`）是数据不是界面文案，不翻译。

### 加一门语言

全部在 [`rmclient/pages/i18n.js`](rmclient/pages/i18n.js) 一个文件里，没有构建步骤：

1. 把 `STRINGS` 里整个 `"en"` 块复制一份，键改成你的 BCP-47 基础标签
   （`"de"`、`"ja"`……），再翻译值。键一个都不能少，`{大括号}` 占位符原样保留。
2. 把 `"lang.label"` 设成你想显示在切换按钮上的文字。切换控件是按
   `Object.keys(STRINGS)` 生成的，别处不用改。
3. 想让它被自动识别，就在 `detect()` 里加上你的标签。不加也能从切换控件选到。

`STRINGS` 特意写成严格 JSON：`uv run pytest tests/test_i18n.py` 会把它解析出来，
任何一门语言少了键、或者占位符和英文对不上，测试就红。

## 锁定目录

锁定目录是指某个**根级**目录，它整棵子树只读：

- 树上照常**显示**，标上锁标记，但不给任何写操作按钮；
- 不出现在任何批量操作里，也没有勾选框；
- 新建 / 重命名 / 移动 / 删除 / 上传只要落在里面一律拒绝，而且这道检查在
  **服务端**再做一遍，不只是界面过滤；
- 只读访问照旧：里面的文档可以预览、可以下载。

嵌套的同名目录不算——锁的是根级那一个。

## 安全须知

下面这些都是对真实服务器实测出来的，证据在 [`spike/REPORT.md`](spike/REPORT.md)。

- **删除是硬删，而且会传到设备上。** 这个操作在服务端没有回收站：删掉之后设备
  下次同步就把本地那份也丢掉。rmclient 在你确认之前会把整棵将被删除的子树列
  出来，按先深后浅删（服务端不级联），并且只删显式白名单里的 UUID。
- **删掉的文档可能复活。** 如果设备上对某个文档有本地改动，它下次同步会把这个
  文档按**原 UUID** 推回来。rmclient 把每次删除记进 `var/deleted.json`（不进
  git），并在树页面常驻一个「复活复查」面板——这个竞态要等一轮设备同步之后才
  看得出来。
- **上传对不对，责任全在客户端。** 服务端**只看文件名后缀**（`.pdf`/`.epub`/
  `.rmdoc`）分派，完全不看内容；遇到不认识的后缀回的是 HTTP 500，真正的原因在
  响应体里。rmclient 在本机同时校验后缀**和**内容（EPUB 的 OCF 结构、PDF/zip
  魔数），对不上就不发。
- **重复上传不会合并。** 同一个文件名传两次会得到两个独立文档、同一个可见名。
  rmclient 会警告并要求你显式确认，而不是悄悄让你多出一本书。
- **移动会顺带改名。** 移动端点无条件覆写名字，所以只想移动时 rmclient 总是把
  原名原样回传。
- **重名报告不删任何东西。** 它只按可见名分组、告诉你它们在哪；哪一份该留是你
  的决定。
- **「下载」给的是原件，不含你的批注。** 在设备上批注过的 epub，包里还有一份
  设备生成的 PDF 渲染件，笔迹落在那上面；要批注就用整包下载（`?package=1`）。

## 契约速查

rmclient 依赖的端点，以及每个端点各自的坑。完整证据在
[`spike/REPORT.md`](spike/REPORT.md)。

| 操作 | 端点 | 关键坑 |
|---|---|---|
| 登录 | `POST /ui/api/login` | 响应体**就是** JWT；用 `Authorization: Bearer` 回传，别依赖 cookie。 |
| 列树 | `GET /ui/api/documents` | 读响应小写键、写响应大写键两套字段名。刚上传的文档 `type` 回显的是它的名字，不可信。 |
| 上传 | `POST /ui/api/documents/upload` | 100% 按文件名后缀分派（`.pdf`/`.epub`/`.rmdoc`），完全不校验内容。后缀不在白名单回 HTTP 500，原因在响应体里。 |
| 移动/重命名 | `PUT /ui/api/documents` | `name` 无条件覆写，只想移动也必须把原名回传。`parentId: ""` 表示根级。 |
| 删除 | `DELETE /ui/api/documents/{id}` | 硬删、不进回收站、且会同步到设备。设备上有本地改动时会把文档按原 UUID 推回来。 |
| 导出 | `GET /ui/api/documents/{id}?type=rmdoc` | zip，原始字节无损。包里的 `.content` 才是可信的 `fileType`。 |

## 兼容性

- 只在 **rmfakecloud v0.0.31** 上测过。别的版本可能不一样；实测到的契约都写在
  `spike/REPORT.md` 里。
- 认证用 `Authorization: Bearer`，不依赖 cookie。
- 如果你的服务器在 Cloudflare 隧道后面，注意免费边缘每请求 100MB 的上限：导出
  大笔记或下载大部头可能撞上。导出还会整份缓冲进内存，并且压着 120 秒读超时。
- 树上文档的 `size` 是它所有 blob 之和，不是原件的大小。

### 已知限制

- `serve` 只登录一次、不自动续期，长跑到 JWT 过期会开始 401，重启进程即可。
- 每个写操作都会重读一次文档树；个人库够用，大库没做优化。
- 回收站只展示，不做还原和清空。

## 一路是怎么走过来的

每一轮都对真实服务器验证过才开下一轮；契约结论都在
[`spike/REPORT.md`](spike/REPORT.md)。

| 阶段 | 做成了什么 |
|---|---|
| spike | 用一本真 EPUB 把「本机 → 自建云 → 设备」整条路走通，并把 `/ui/api` 契约和其中每个坑记录下来。 |
| M0 | API 客户端库：登录、列树、建目录、上传、移动、删除、导出——每个已知的坑都固化成代码层防御，并由离线测试钉住。 |
| M1 | 推书：`rmclient push` 命令行与拖拽页共用同一条校验加上传的路径。补测了重复上传语义（REPORT §10）。 |
| M2 | 树浏览与管理：新建、重命名、移动、删除——不可逆的删除前先摊开整棵子树，配删除记录与复活复查。补测了移到根级的 sentinel（§11）。 |
| M3 | 笔记预览：用 rmscene 解析 `.rm` v6，逐页渲染 SVG，整本导出 PDF。 |
| v1 | 内容管理器：搜索与排序、多选批量移动与删除、原件/整包下载、全库重名报告（§12）。 |
| UI | 三个页面统一做了一轮呈现层：CSS token 设计体系与暗色模式、统一顶栏、吸附工具栏、底部悬浮批量条、toast、骨架态、键盘翻页。 |
| i18n | 默认英文、中文完整保留：三页共用一份字符串表，顶栏可切换，服务端错误码给本地化主提示，CLI 全英文。 |

## 仓库结构

```
rmclient/
  config.py     服务器地址、凭据、锁定目录（环境变量优先）
  models.py     文档树模型、两套字段名、锁定目录助手
  api.py        /ui/api 客户端，关键的守卫都在这
  validate.py   上传前的后缀与内容校验
  push.py       目标校验、重名检测、上传
  manage.py     新建/重命名/移动/删除的策略与删除计划
  render.py     rmdoc → 页 → SVG / PDF，以及原件取出
  journal.py    删除记录，落在 var/deleted.json
  cli.py        rmclient push / serve
  web.py        FastAPI 路由
  pages/        push.html（拖拽推书）、tree.html（管理器）、
                preview.html（笔记预览）、app.css（共用设计 token）、
                i18n.js（三页共用的字符串表与 t()）
scripts/        dump_tree.py —— 只读打印文档树
spike/          可行性验证代码与 REPORT.md（端点契约）
tests/          离线测试
```

## 开发

```bash
uv run pytest        # 离线测试，全程不碰真实服务器
```

测试统一用 `httpx.MockTransport` 和 FastAPI 的 `TestClient`，渲染那部分用合成的
`.rm` 场景数据，所以整套跑起来不需要任何凭据。

`spike/` 下的脚本确实会写真实服务器。它们把动作限制在临时目录
`rmclient-spike-<随机>` 里，跑完自己清理。

## License

MIT 许可证——见 [LICENSE](LICENSE)。
