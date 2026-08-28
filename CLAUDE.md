# rmclient — 项目纪律与上下文

跑在本机的 reMarkable 自建云内容管理客户端。服务端是 paperpal 项目部署的
rmfakecloud v0.0.31，本项目**只做 API 消费者**。契约权威文档：`spike/REPORT.md`。

## 硬纪律（每条都有实证教训在背后）

1. **`Mailbox/` 及其整棵子树绝不触碰**——那是 paperpal 的命脉（根级唯一信箱按名字
   解析，动了会破坏 pipeline）。任何遍历/批量操作必须显式排除它。
2. **删除是硬删，不进回收站，且会同步删掉设备上的文件。** 任何删除必须经用户确认；
   批量删除必须走白名单 UUID 断言（参照 `spike/epub_spike.py` 的做法）。
3. **删除有复活竞态**：设备端有本地变更的文档，服务端删掉后会被设备原 UUID 推回。
   删除逻辑要考虑二次确认/复查。
4. **移动/重命名（`PUT /ui/api/documents`）的 `name` 字段无条件覆写**——只想移动
   也必须把原名原样传回，漏传会把可见名置空。
5. **上传扩展名的正确性完全由客户端负责**：服务端只认文件名后缀（.pdf/.epub/.rmdoc
   白名单），不校验内容。传错后缀不报错，会安静地把书弄坏在设备端。
6. **入口只用 Cloudflare 隧道域名**（读 `~/Documents/paperpal/.env` 的 `DOMAIN`，
   域名不写进本仓库）；direct 域名对 `/ui*` 固定 403。注意 CF 免费边缘有 100MB
   单请求上限（大文件导出可能撞）。
7. **paperpal 仓库（`~/Documents/paperpal`）只读参考，一个字节都不许改。**
   不 ssh volc1，不 ssh 设备。
8. 对生产云的实验只在 `rmclient-spike-<随机>` 临时根级目录里做，跑完清理。

## 凭据

优先读环境变量 `RMCLIENT_URL` / `RMCLIENT_USER` / `RMCLIENT_PASSWORD`（或
`RMCLIENT_PASSWORD_FILE`）；锁定目录用 `RMCLIENT_LOCKED_FOLDERS`（默认 `Mailbox`）。
一个都不设时才回落到下面这套本机布局——本机日常用法不受影响。

暂与 paperpal 共用账户（rmfakecloud 文档树按 user 隔离，换账户就看不到设备的树）：
用户名 `~/Documents/paperpal/.env` 的 `RMFAKECLOUD_USER`，密码
`~/Documents/paperpal/secrets/rmfakecloud_password`（读文件须 `.strip()`）。
凭据不进日志、不进 git。

## 参考实现（只读）

- `paperpal/pipeline/rm_api.py` — UI API 客户端
- `paperpal/scripts/m0_spike.py` — 契约测试模板（--sandbox 模式）
- `paperpal/spike/samebook/sync15.py` — sync15 协议客户端（本项目 v0 用不到）
- rmscene（PyPI）— .rm v6 笔记解析，看笔记功能的渲染基础
