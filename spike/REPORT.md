# rmclient spike：本机 → 自建云 → 设备，推一本 EPUB

**结论：EPUB 上传路径在服务端侧完全打通，与 PDF 走同一端点、同一契约，差异只在扩展名。**
六步全部 ✓，服务端侧无阻塞项。剩下唯一未闭环的是设备端渲染，需人工肉眼验收（§7）。

| | |
|---|---|
| 日期 | 2026-08-28 |
| 入口 | Cloudflare 隧道域名（本机配置 `DOMAIN` 键读取，已从仓库脱敏；direct 域名对 `/ui*` 固定 403，未使用） |
| 服务端 | rmfakecloud v0.0.31（paperpal 项目部署在 volc1） |
| 客户端 | 本机 macOS / Python 3.14 / httpx 0.28.1，脚本 `spike/epub_spike.py` |
| 凭据 | 用户名读 `~/Documents/paperpal/.env`，密码读 `~/Documents/paperpal/secrets/rmfakecloud_password`（32 字节含换行，须 `.strip()`）；本报告与日志不含任何凭据 |
| 参考实现 | `paperpal/pipeline/rm_api.py` + `scripts/m0_spike.py --sandbox`（**只读引用，未 import、未修改；paperpal 仓库零改动**） |

跑法：

    python3 spike/epub_spike.py           # 建→传→查→读回→删 闭环，跑完自己清理
    python3 spike/epub_spike.py --keep    # 只传一本干净的书且不清理，留给设备端验收
    python3 spike/cleanup_keep.py         # 验收完删掉 --keep 留下的对象

---

## 1. 逐步验证

| # | 步骤 | 结果 | 证据 |
|---|---|---|---|
| 1 | 登录 `POST /ui/api/login` | ✓ | 200，body 是 JWT 明文；请求头用 `Authorization: Bearer`（不用 cookie） |
| 2 | 列文档树 `GET /ui/api/documents`（只读） | ✓ | 70 条目 = 11 目录 + 59 文档，根级 36 项，回收站 12 项；既有文档一个字节都没下载 |
| 3 | 建根级临时目录 `POST /ui/api/folders` | ✓ | `{"parentId":"","name":"rmclient-spike-<8hex>"}` → `parentId` 空串即根级 |
| 4 | 上传 EPUB 并回查 | ✓ | 3.2 KB EPUB 3，上传后在树上按 UUID + 父目录 + 可见名三项全部核对通过 |
| 5 | EPUB vs PDF 路径差异 | ✓ | 见 §3，用 6 组对照实验把「扩展名 / 内容 / MIME」三个变量逐一隔离 |
| 6 | 清理 | ✓ | 两轮闭环共创建 10 个对象，全部删除；删后回查文档树残留 **0** 项 |

三轮实跑（`spike/out/*.json` 是原始记录）：闭环轮 → 矩阵轮（6 次上传）→ `--keep` 验收轮。

## 2. 端点契约（实测形状）

    POST   /ui/api/login              {"email","password"} -> 200, body = JWT 明文
    GET    /ui/api/documents          -> {"Entries":[...], "Trash":[...]}
    POST   /ui/api/folders            {"parentId","name"} -> Document（大写键）
    POST   /ui/api/documents/upload   multipart: file=<带扩展名>, parent=<uuid|root> -> [Document]
    GET    /ui/api/documents/{id}?type=rmdoc  -> application/octet-stream，zip
    DELETE /ui/api/documents/{id}     -> 204

**写操作的响应用大写键，读操作的树条目用小写键** —— 同一个对象两套字段名，客户端两边都得认：

```jsonc
// POST /ui/api/folders 与 /upload 的响应（upload 是单元素数组）
{"ID":"9bc59550-…","Type":"CollectionType","Parent":"","Name":"rmclient-spike-13c02ac6","Version":0}

// GET /ui/api/documents 树里的目录条目
{"id":"…","name":"…","lastModified":"2026-08-28T07:41:06.731Z","isFolder":true}
// 树里的文档条目（没有 isFolder，多了 type 和 size）
{"id":"…","name":"…","type":"epub","lastModified":"…","size":3993}
```

区分目录与文档只能靠 `isFolder` 存在与否（文档条目**没有**这个键），目录条目也没有 `size`/`type`。

## 3. 核心问题：EPUB 与 PDF 的差异

### 3.1 分派矩阵（把三个变量拆开测）

| | 载荷真实内容 | 文件名扩展名 | 声明的 content-type | → 服务端存成 | `.content` 的 `fileType` |
|---|---|---|---|---|---|
| A | epub | `.epub` | `application/epub+zip` | `<uuid>.epub` | `epub` |
| B | epub | `.epub` | `application/octet-stream` | `<uuid>.epub` | `epub` |
| C | pdf | `.pdf` | `application/pdf` | `<uuid>.pdf` | `pdf` |
| D | **epub** | **`.pdf`** | `application/epub+zip` | **`<uuid>.pdf`** | **`pdf`** |
| E | **pdf** | **`.epub`** | `application/pdf` | **`<uuid>.epub`** | **`epub`** |
| F | epub | `.txt` | `text/plain` | ✗ 拒绝 | — |

**判定：服务端 100% 按文件名扩展名分派，既不看内容也不看 content-type。**
A vs B 证明 content-type 无关；D/E 的交叉错配证明内容无关 —— epub 字节挂个 `.pdf` 名就被登记成 PDF 原样存下，反之亦然。服务端**不做任何内容校验**。

F 的拒绝形状：`HTTP 500` + `{"error":"unsupported extension: .txt"}`。白名单是 `.pdf` / `.epub` / `.rmdoc`。

### 3.2 EPUB 与 PDF 的实际差异一览

| 维度 | EPUB | PDF | 是否有差异 |
|---|---|---|---|
| 端点与 multipart 字段 | `POST /ui/api/documents/upload`，`file` + `parent` | 同 | 无 |
| 触发条件 | 文件名以 `.epub` 结尾 | `.pdf` 结尾 | **仅此一处** |
| content-type | 随便填（`application/epub+zip` 或 `application/octet-stream` 都行） | 同 | 无 |
| 服务端存储 | blob `<uuid>.epub`，**字节与上传全同**（SHA256 比对通过） | `<uuid>.pdf`，同 | 无 |
| `.content` 的 `fileType` | `"epub"` | `"pdf"` | 值不同，结构相同 |
| 可见名 | 剥掉 `.epub` | 剥掉 `.pdf` | 无（都剥） |
| 附带开销 | `tree.size` 3993 vs 载荷 3212（+781 = `.content`+`.metadata`） | 1380 vs 601（+779） | 无 |
| 服务端解析/转码 | 无，纯字节透传 | 无 | 无 |

结论：**客户端侧 EPUB 与 PDF 的代码路径可以完全共用，唯一要做对的是文件名后缀。**
paperpal `rm_api.upload_pdf` 直接改扩展名就是可用的 epub 上传实现。

### 3.3 上传后服务端生成的元数据

EPUB 上传后 `.content`（PDF 完全同构，只有 `fileType` 不同）：

```json
{"dummyDocument": false, "fileType": "epub", "pageCount": 0, "pages": [],
 "lastOpenedPage": 0, "margins": 180, "textScale": 1, "lineHeight": -1,
 "fontName": "", "orientation": "portrait",
 "extraMetadata": {"LastPen": "Finelinerv2", "LastTool": "Finelinerv2", …},
 "transform": {…单位矩阵…}}
```

`pageCount: 0` / `pages: []` 是预期的 —— EPUB 是回流排版，分页由设备端阅读器决定。
`margins/textScale/lineHeight/fontName` 是设备端 EPUB 阅读器的排版参数，服务端给了默认值；**upload 端点不接受自定义**（若要预设排版，只能走 `.rmdoc` 自带 `.content` 的路子，本 spike 未验证）。

`.metadata` 里 `visibleName` / `parent` / `version:1` / `synced:true`，与树上一致。

### 3.4 读回验证（rmdoc 导出）

`GET /ui/api/documents/{id}?type=rmdoc` 对**自己刚传的** EPUB 返回一个 zip：

    <uuid>.content   462 B
    <uuid>.epub     3212 B   ← 与上传字节 SHA256 完全一致
    <uuid>.metadata  319 B

即**原始 EPUB 可无损取回**，服务端没有重打包、没有改 zip 结构。这把剩余风险收窄到了纯设备端渲染。

## 4. 坑（客户端实现必须知道）

1. **树条目的 `type` 字段刚上传时不可信。** 既有文档的 `type` 是 `notebook`/`epub`/`pdf`（该账户实测 18/11/30），但**刚上传的文档，`type` 回显的是文件名本身**，不是 fileType。收敛观察见 §6。→ 客户端不能在上传后立刻拿 `type` 做类型判断；要准确类型就读 `?type=rmdoc` 里的 `.content`。
2. **服务端不校验内容与扩展名一致性**（§3.1 的 D/E）。传错后缀不会报错，会安静地把一本 EPUB 当 PDF 推到设备上——设备端多半打不开而看不出原因。**扩展名的正确性完全由客户端负责。**
3. **不支持的扩展名回 HTTP 500，不是 4xx**，错误信息在 body 的 `error` 字段。客户端不能靠状态码区分「我传错了」和「服务端挂了」，必须解析 body。
4. **删除会同步删掉设备上的文件。** 本 spike 的删除只作用于自己创建的 UUID（脚本里 `Api.delete` 有断言白名单，只认本次 `created` 列表里的 id，绝不按名字匹配）。
5. **`HashTree.Remove` 不级联**：必须先删文档再删父目录，否则子项会被甩成根级孤儿。脚本按「先深后浅」倒序删。
6. **可见名会被剥掉扩展名**（`TrimSuffix`）。设备上显示的是不带 `.epub` 的名字，客户端要按「书名 + `.epub`」构造 filename。
7. **认证用 `Authorization: Bearer`，别依赖 cookie**：`RM_HTTPS_COOKIE` 开着时 cookie 带 `Secure` 标记，某些路径下不回传。
8. **入口只能用隧道域名**，direct 域名对 `/ui*` 固定 403。
9. **写响应大写键 / 读响应小写键**（§2），两套都要认。
10. EPUB 本地必须 OCF 合规才有意义：`mimetype` 必须是 zip 的**第一个**条目且**不压缩**（`ZIP_STORED`）。脚本在上传前本地自检这一条 —— 否则设备端打不开时无法归因是「服务端搞坏了」还是「我造的书本来就坏」。

### 只读观察（未改动 paperpal，仅记录）

`paperpal/pipeline/scan.py` 用 `file_type in ("pdf","epub")` 把非原生笔记本挡在授权集之外，而这个 `file_type` 取自树条目的 `type`。对**既有**文档它是对的；但按坑 1，**刚上传**的文档这个字段是文件名，该判断会漏。paperpal 的信箱里文档都是设备端产生并已收敛的，所以现网大概率不受影响 —— 仅作记录，未做任何修改。

## 5. 清理状态

| 轮次 | 创建对象 | 状态 |
|---|---|---|
| 闭环轮 `rmclient-spike-13c02ac6` | 1 目录 + 3 文档 | ✓ 全部删除，回查残留 0 |
| 矩阵轮 `rmclient-spike-849fa65e` | 1 目录 + 5 文档 | ✓ 全部删除，回查残留 0 |
| 验收轮 `rmclient-spike-ab17c966` | 1 目录 + 1 EPUB | ⏳ **故意保留**，见 §7 |

全程未创建、未修改、未删除、未下载任何既有文档；既有内容只做过树列表（元数据）读取。

## 6. `type` 字段收敛观察

坑 1 的机制值得说清楚，因为它直接决定客户端怎么判断文档类型。

| 文档来源 | 树条目 `type` 字段 | 样本 |
|---|---|---|
| 既有文档（都经过设备同步） | 正确的 fileType：`notebook` 18 / `epub` 11 / `pdf` 30 | 59 份 |
| 本次刚上传（无设备同步） | **回显文件名本身** | 5 份，无一例外 |

对 `--keep` 那本书完整轮询了 8 分 45 秒（+0 / 15 / 45 / 105 / 225 / 525 秒，`spike/poll_type.py`
→ `out/poll_type.json`），六个采样点字段**全部**是文件名，无任何变化。

**推断**（未读 v0.0.31 源码，仅由上表反推）：这个字段不是上传时写入的，而是由同步侧
的索引过程填充 —— 所以它不是「等一会儿就好」的时间问题，没有设备同步就不会变。

→ 客户端结论：**刚上传的文档不要用树上的 `type` 判类型**；要准确类型就读
`GET /ui/api/documents/{id}?type=rmdoc` 里的 `.content.fileType`（上传后立即可用且准确）。
对既有文档，树上的 `type` 是可信的。

## 7. ⏳ 待人工确认（设备端）

云上**保留**了一本书供肉眼验收：

| | |
|---|---|
| 目录 | `rmclient-spike-ab17c966`（根级） |
| 书名 | `rmclient EPUB Spike A 20260828-154337` |
| 文档 UUID | `05db4f98-eb85-4b88-9b7b-46b0de4f0cf2` |
| 目录 UUID | `13b2fe15-87b5-4bde-b20e-594b78c0cc77` |

**✅ 已验收（2026-08-28，用户真机确认）**：书能打开，调字号正常（走的是 EPUB
阅读器，非固定版式），中文探针显示正常（设备端 EPUB 阅读器有 CJK 字体，§8 该项关闭）。

**端到端结论成立：本机 → 自建云 → 设备的 EPUB 推书路径全程闭环。**

验收完成后已跑 `python3 spike/cleanup_keep.py` 清理云上测试对象。

## 8. 未验证 / 开放问题

- ~~同名或重复上传：是覆盖、报 409、还是产生两份？~~ ✅ 已测，见 §10：无条件新建两份独立 UUID
- 大文件：真实几 MB~几十 MB 的 EPUB 是否触发隧道/服务端超时或体积上限（本次只测了 3.2 KB）
- 封面与书籍元数据（作者/出版信息）在设备库里如何呈现，OPF 里的 `dc:creator` 是否被使用
- 是否能预设 EPUB 阅读器排版参数（`margins`/`textScale`/`fontName`）—— 可能要走 `.rmdoc` 自带 `.content`
- ~~设备端 CJK 字体~~ ✅ 有（§7 真机验收，中文探针正常显示）

## 9. 追记（2026-08-28 晚，云端文件整理实战中确认）

1. **移动/重命名端点存在且可用**：`PUT /ui/api/documents`，body
   `{"documentId","parentId","name"}`（v0.0.31 `routes.go:74` → `UpdateBlobDocument`：
   重写 `.metadata` blob、Version+1、rehash、走 sync15 树正规更新并通知设备）。
   实战 19 次移动（含建 3 个根级目录）全部复核通过。
   **坑：`name` 无条件覆写**——只想移动也必须把原名原样传回，漏传会把可见名置空。
2. **删除与活跃设备的竞态（复活现象实证）**：服务端 DELETE 后，若设备端对该文档有
   本地变更（哪怕只是打开过一次产生的阅读状态），下次设备同步会把它**原 UUID 重新
   推回云端**（本例 3.2KB→64KB，落到根级因父目录已删）。需再删一次且设备端不再碰它
   才真正消失。另：DELETE 是硬删，**不进回收站**——客户端做删除功能必须自建确认/
   回收机制。

## 10. 追记（2026-08-28，M1 契约补测：重复上传语义）

跑法 `uv run python spike/dup_upload_spike.py`（根级沙箱 `rmclient-spike-<8hex>`，
跑完按白名单 UUID 自清理；原始记录 `spike/out/dup_upload.json`）。这一轮用的是
rmclient 库本身，顺带把 login / create_folder / upload / delete_many 的真实调用路径过了一遍。

**结论：重复上传 = 无条件新建。不覆盖、不去重、不报 409。**

| # | 文件名 | 载荷 | 结果 |
|---|---|---|---|
| 1 | `Dup Probe <ts>.epub` | epub A（3194 B） | 200，UUID₁，`Version: 0` |
| 2 | **同一文件名** | **同一字节** | 200，UUID₂（新的），`Version: 0` |
| 3 | **同一文件名** | epub B（差 1 字节） | 200，UUID₃（又一个新的），`Version: 0` |

回查沙箱：**3 个文档，UUID 互不相同，可见名三个一模一样**（都是文件名去掉 `.epub`）。
同字节那次也没有被内容哈希去重 —— 服务端对「同名」这件事完全无感。

同名目录同理：`POST /ui/api/folders` 拿同一个 `parentId` + 同一个 `name` 建两次，
得到**两个独立 UUID 的同名目录**，不报错。

### 客户端结论

1. **服务端没有「更新一本书」的原生语义。** 要做只能客户端自己「先传新的、再删旧的」，
   而删是硬删、会同步删设备端文件、还有复活竞态（§9.2）—— v0 不做替换，只做检测 + 提示。
2. **推书前必须自己查目标目录里有没有同可见名的文档。** 有就得明确告诉用户「会多出
   一本一模一样的书，设备端两本无法区分」，要用户显式确认（`rmclient push --force`）。
3. **判重只能按可见名**（文件名去掉扩展名），不能按 `type`（见下）。

### 顺带确认的两条

- 树上的 `type` 字段回显的是**可见名**（文件名去掉扩展名），比 §4.1 记的「文件名本身」
  更精确：三份的 `type` 都是 `Dup Probe <ts>`，没有 `.epub`。判类型依然只能靠
  `?type=rmdoc` 里的 `.content`。
- **upload 写响应的 `Parent` 是空串**，哪怕文档确实落在了 `parent` 指定的目录里
  （回查树确认三份都在沙箱内）。→ 客户端不能用写响应的 `Parent` 确认落点，要确认就回查树。
  （`Version` 三次都是 0；建子目录的写响应 `Parent` 本轮没记，未知。）
- 附带开销 +769 B（载荷 3194 → 树上 3963），与 §3.2 记的 +781/+779 同量级。

### 清理

本轮创建 6 个对象（1 沙箱目录 + 3 文档 + 2 同名子目录），按「先深后浅」全部删除，
回查残留 **0** 项。全程未创建、未修改、未删除沙箱外的任何对象。

## 11. 追记（2026-08-28，M2 契约补测：移动到根级的 `parentId`）

跑法 `uv run python spike/move_root_spike.py`（根级沙箱 `rmclient-spike-402755db`，自清理；
原始记录 `spike/out/move_root.json`）。M0 在 `api.move` 里留的开放问题：建目录用空串表示
根级、上传用 `"root"`，移动认哪个没测过。

**结论：`PUT /ui/api/documents` 的 `parentId` 用空串 `""` 表示根级。**

| 步骤 | 请求 | 回查树里该文档的 `parent` |
|---|---|---|
| 上传到沙箱 | `parent=<sandbox>` | `<sandbox>` |
| 移到根级 | `{"documentId":…,"parentId":"","name":<原名>}` | **`""`（根级）** |
| 移回沙箱 | `parentId=<sandbox>` | `<sandbox>` |

判据是**回查树里的实际 `parent`**，不是状态码 —— 服务端完全可能 200 但什么都没做，
所以每一步都重读了树。可见名三次回查全程保持不变（`name` 原样回传，§9.1 的覆写规则
在根级路径上同样成立）。

`"root"` 这个 sentinel **没测**：空串第一次就成了，脚本按顺序试到这里就停了。
即上传端点的 `"root"` 与移动/建目录端点的 `""` 是两套写法，别统一。

清理：创建 2 个对象（1 目录 + 1 文档），全部删除，回查残留 **0**。

## 12. 追记（2026-08-28，v1：树上的 `size` 口径与批注 epub 的包内结构）

只读观察，来自 v1 收尾时对真实库的一次导出（`GET /ui/api/documents/{id}?type=rmdoc`，
未做任何写操作）。样本是 `Articles/` 里那本 `Introducing smolagents: simple agents that
write actions in code.`（树上 `type: epub`）。

**结论一：树条目的 `size` 是该文档所有 blob 之和，不是原件大小。**

| | 字节 |
|---|---|
| 树条目 `size` | 108,195 |
| 包内 `<uuid>.epub`（**原件**） | 18,513 |
| 包内 `<uuid>.pdf`（设备生成的渲染件） | 87,511 |
| 包内 `<uuid>.content` | 2,129 |
| 包内 `<uuid>.metadata` | 350 |
| 包内 `<uuid>.pagedata` | 15 |
| 包内成员合计 | 108,518 |

原件只占树上 size 的 17%。合计与树上 `size` 差 323 B（包内是解压后大小，服务端
`size` 的确切口径未深究，不影响结论：**别拿树上的 size 当原件体积估算**，尤其是
在盘算 Cloudflare 100MB 上限时——那条限制卡的是整包导出，比原件大得多）。

**结论二：设备上批注过的 epub，包里会多一份设备生成的 `.pdf` 渲染件。**

reMarkable 的 epub 是回流排版（§3.3 的 `pageCount: 0`），要在上面批注就得先定版，
所以设备把它渲染成固定版式的 PDF 再往上画。于是这个文档同时有 `.epub`（原件）和
`.pdf`（带版式、批注笔迹落在其上的那份）。

→ 客户端结论：**「取回原件」和「取回带批注的东西」是两件事。**
`GET /api/download/{id}` 默认按 `.content` 的 `fileType` 给原件（干净但无批注），
`?package=1` 给整包 `.rmdoc`（含渲染件与笔迹）。两个入口在 `/tree` 的文档行上都有。
笔记本（notebook）没有这个分岔，本来就只能整包给。
