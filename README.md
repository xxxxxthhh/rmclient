# rmclient

跑在本机的 reMarkable 自建云内容管理客户端：推书（epub/pdf）、看笔记、增删移。

独立项目，**消费** [`~/Documents/paperpal`](../paperpal/) 部署的 rmfakecloud v0.0.31
（volc1）——服务端一行不动，本项目只是它的又一个 API 消费者。paperpal 仓库仅作
只读参考。思考原稿在 `~/Documents/mind-center/archive/remarkable-cloud-client.md`。

## 现状（2026-08-28）

- ✅ **可行性 spike 完成**（`spike/REPORT.md`，权威契约文档）：
  - epub 推书**端到端闭环**（本机 → 云 → 设备真机验收：真 EPUB 阅读器、中文正常）。
  - 增（上传）、删（DELETE）、移（PUT 移动/重命名）三大操作的服务端契约全部摸清，
    含各自的坑（详见 REPORT §4、§9）。
- ✅ **M0 API 客户端库**（`rmclient/`）：登录 / 列树 / 建目录 / 上传 / 移动 / 删除 / 导出，
  REPORT §4、§9 的坑逐条固化成代码层防御 + 离线测试。
- ✅ **M1 推书**：CLI `rmclient push` 与本地 Web 拖拽页（`rmclient serve`）走同一条
  校验 + 上传路径；重复上传语义已补测（REPORT §10：无条件新建，不覆盖不去重）。
- ✅ **M2 树浏览与管理**：`/tree` 页展示完整文档树（目录可折叠，`Mailbox/` 显示但整棵
  子树锁死只读），支持新建目录 / 重命名 / 移动 / 删除；删除前列出整棵子树并写明硬删后果，
  删后记录落到 `var/deleted.json`（不进 git），页面常驻「删除记录待复查」区块，等设备
  同步一轮后一键复活复查、确认干净再清记录。移动到根级的 `parentId` 已补测（REPORT §11：空串）。
- ✅ **M3 看笔记**：`/tree` 文档行「预览」→ 逐页 SVG 渲染（rmscene 解析 .rm v6）+ 整本
  导出 PDF。类型以 rmdoc 内 `.content` 为准，非 notebook 明确回「不支持预览」；信箱里的
  笔记可只读预览（锁只针对写操作）。
- ✅ **v1 内容管理器**：`/tree` 单页管理——搜索过滤（命中自动展开祖先）、按名字/时间/大小
  排序、目录行显示子项数与「传到这里」、多选批量移动与批量删除（合并成一份计划）、
  文档原件下载（`?package=1` 给整包 .rmdoc，含设备端批注）、全库重名检测（只报告，不自动删）。
- ✅ **UI 增强**：三页统一顶栏 + 纸感设计体系（CSS token，暗色模式跟随系统）；删除确认
  红色警示分级、批量悬浮操作条、toast 反馈、预览页键盘 ←→ 翻页。

## 快速上手

```bash
uv sync                                       # 装依赖
uv run rmclient push book.epub --to Books/CS  # 推一本书（--to 按树上的可见名路径）
uv run rmclient serve                         # 本地 Web → http://127.0.0.1:8000
                                              #   /      拖拽上传
                                              #   /tree  文档树浏览与管理（增删移改）
                                              #   /preview/<uuid>  笔记预览 + 导出 PDF
uv run python scripts/dump_tree.py            # 只读：打印云上完整文档树（含回收站）
uv run pytest                                 # 离线单元测试（不打真实 API）
python3 spike/epub_spike.py                   # epub 上传契约闭环测试（自清理）
uv run python spike/dup_upload_spike.py       # 重复上传契约补测（自清理）
uv run python spike/move_root_spike.py        # 移动到根级契约补测（自清理）
```

重名会被拒（退出码 3）并列出已有副本 —— 服务端不覆盖也不去重，确实要再传一份加 `--force`。

已知限制：`serve` 进程内的登录态不自动续期，长跑到 JWT 过期会开始 401，重启进程即可。

凭据暂读 paperpal（同一账户）：用户名 `~/Documents/paperpal/.env` 的
`RMFAKECLOUD_USER`，密码 `~/Documents/paperpal/secrets/rmfakecloud_password`。
入口 `https://rmfakecloud.example.com`（只能走隧道域名，direct 域名对 `/ui*` 403）。

## 结构

```
README.md        # 本文件
CLAUDE.md        # 项目纪律与上下文（agent 干活前必读）
SPEC.md          # v0 spec 草案
rmclient/        # 库 + 前端：config / models / api / validate / push / manage / render / cli / web
                 #   pages/ 是三个页面的 HTML + app.css（无构建链）
tests/           # 离线单元测试
spike/           # 可行性验证代码 + REPORT.md（契约权威）
scripts/         # 小工具（dump_tree.py）
```

## 已验证契约速查

| 操作 | 端点 | 关键坑 |
|---|---|---|
| 登录 | `POST /ui/api/login` | body 是 JWT 明文；用 `Authorization: Bearer` |
| 列树 | `GET /ui/api/documents` | 读小写键/写大写键两套字段名；刚上传文档的 `type` 回显文件名不可信 |
| 上传 | `POST /ui/api/documents/upload` | 100% 按扩展名分派（白名单 .pdf/.epub/.rmdoc），不校验内容；错误回 500 需解析 body |
| 移动/重命名 | `PUT /ui/api/documents` | `name` 无条件覆写——只移动也必须回传原名 |
| 删除 | `DELETE /ui/api/documents/{id}` | **硬删不进回收站**；活跃设备会把有本地变更的文档原 UUID 推回（复活） |
| 导出 | `GET /ui/api/documents/{id}?type=rmdoc` | zip，原始字节无损；`.content` 才是准确的 fileType |
