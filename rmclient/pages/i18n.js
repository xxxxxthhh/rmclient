/* rmclient 的字符串表。三个页面（push / tree / preview）共用这一份。
   English is the default; Chinese ships complete. No build chain, no dependencies.

   ---- DIY: adding a language --------------------------------------------
   1. Copy the whole "en" block below, rename the key to your BCP-47 base tag
      (e.g. "de", "ja", "fr"), and translate the values. Keep every key.
   2. Give it a "lang.label" — that is the text on the top-bar switcher button,
      which is built from Object.keys(STRINGS), so nothing else needs editing.
   3. Placeholders are {braces}; keep them (and their spelling) in your copy.
      "\n" starts a new line in toasts and dialog bodies.
   4. Optional: teach detect() about your tag. Without that, your language is
      still reachable from the switcher, just not auto-detected.

   There is no plural engine on purpose: the English strings are phrased so
   they read correctly at any count ("3 inside", "1 inside"). If your language
   needs real plural forms, Intl.PluralRules is available in every browser —
   but reaching for phrasing that works at any count is usually enough.

   STRINGS below is strict JSON on purpose (double-quoted keys and values, no
   comments, no trailing commas): the offline test parses it to prove the
   dictionaries have identical key sets. Keep it that way.
   ------------------------------------------------------------------------ */

const STRINGS = {
"en": {
"lang.label": "EN",
"lang.aria": "Language",
"nav.aria": "Page navigation",
"nav.push": "Push",
"nav.tree": "Tree",
"toast.close": "Dismiss",
"dialog.cancel": "Cancel",
"folder.root": "(root)",
"error.http": "Failed: HTTP {status}",
"error.mailbox": "Refused: that folder is locked.",
"error.not_found": "Not found on the server.",
"error.invalid": "Refused: the request is not valid.",
"error.upstream": "The cloud server rejected the request.",
"error.bad_target": "That target folder will not do.",
"error.duplicate": "A book with this name is already there.",
"error.tree_changed": "The list you confirmed is out of date.",
"error.unsupported": "This document cannot be previewed.",
"push.title": "rmclient — Push",
"push.crumb": "Push",
"push.heading": "Push a book to your reMarkable",
"push.target": "Target folder",
"push.force": "Upload even if the name exists",
"push.drop.big": "Drop .epub / .pdf / .rmdoc here",
"push.drop.hint": "Or click to choose files. The extension has to match the content — the server does not check, so this machine rejects mismatches first.",
"push.state.uploading": "Uploading",
"push.state.done": "Uploaded",
"push.state.skipped": "Not uploaded",
"push.state.refused": "Refused",
"push.foldersFailed": "Cannot read the document tree — check the terminal for the error.",
"push.uploaded": "\"{name}\" → {target}",
"push.dupWarn": "⚠ {copies} already there under that name; the device will show {total} books called the same thing",
"push.syncNote": "The device has to sync once before it shows up",
"push.dupCard": "This name is already taken in {target} — {copies} there now.\nThe server neither overwrites nor de-duplicates: pushing again adds an independent second copy, and the device cannot tell the two apart.\nTo do it anyway: tick \"Upload even if the name exists\" and drop the file again.",
"tree.title": "rmclient — Document tree",
"tree.crumb": "Document tree",
"tree.search": "Search visible names (substring, case-insensitive)",
"tree.sort": "Sort",
"tree.sort.name": "Name",
"tree.sort.modified": "Modified",
"tree.sort.size": "Size",
"tree.newRoot": "＋ New root folder",
"tree.dupCheck": "Duplicate report",
"tree.reload": "Refresh",
"tree.batch.aria": "Batch actions",
"tree.trash": "Trash ({n} inside, read-only)",
"tree.items": "{n} inside",
"tree.loadFailed": "Cannot read the document tree — check the terminal for the error.",
"tree.empty.filtered": "Nothing here is named like \"{filter}\". Try another word, or clear the search box to see everything.",
"tree.empty": "This folder is empty. Use \"Upload here\" on a folder row to push a book into it.",
"badge.readonly": "read-only",
"badge.readonlyLock": "🔒 read-only",
"act.preview": "Preview",
"act.download": "Download",
"act.download.title": "Fetch the original (epub/pdf gives you the file itself, a notebook gives the whole package). Device annotations are not included.",
"act.package": "Package",
"act.package.title": "The whole .rmdoc: device annotations and strokes, plus the PDF the device renders for an annotated epub.",
"act.newFolder": "＋Folder",
"act.uploadHere": "Upload here",
"act.rename": "Rename",
"act.move": "Move",
"act.delete": "Delete",
"batch.selected": "{n} selected",
"batch.label": "{n} selected",
"newFolder.title": "New folder inside \"{parent}\"",
"newFolder.titleRoot": "New root-level folder",
"newFolder.placeholder": "Folder name",
"newFolder.confirm": "Create",
"newFolder.done": "✓ Created folder \"{name}\"",
"rename.title": "Rename \"{name}\"",
"rename.confirm": "Rename",
"rename.done": "✓ Renamed to \"{name}\"",
"move.title": "Move \"{name}\"",
"move.note": "The name is carried over untouched",
"move.confirm": "Move",
"move.done": "✓ Moved \"{name}\"",
"move.many.title": "Move {n} selected",
"move.many.note": "Every item keeps the name it has",
"move.many.done": "Move finished: {ok} succeeded, {bad} failed",
"upload.done": "✓ Uploaded \"{name}\" → {target}",
"upload.dupTitle": "\"{target}\" already holds a book with this name",
"upload.dupBody": "The server neither overwrites nor de-duplicates: pushing again adds an independent second copy, and the device cannot tell the two apart.",
"upload.dupExisting": "Already there: {id}",
"upload.dupConfirm": "Upload anyway",
"upload.failed": "Upload failed: HTTP {status}",
"delete.title": "Delete {label}",
"delete.label": "\"{name}\"",
"delete.alarm": "Hard delete: no trash, no undo, and it removes the file from the device as well.",
"delete.resurrect": "If the device has local changes to these documents, its next sync may push them back under their original UUIDs (resurrection).",
"delete.count": "Deleting {n} in all (deepest first):",
"delete.confirm": "Delete for good",
"delete.treeChanged": "\n(A device sync most likely touched this subtree. Hit delete again and read the list once more.)",
"delete.residue": "Deleted {n}, but the re-check found {r} still on the tree: {ids}",
"delete.done": "✓ Deleted {n}; the immediate re-check found no residue.\nResurrection only shows after the device syncs once — the records are saved locally, so run \"Resurrection re-check\" above in a few minutes.",
"dups.title": "Duplicate report: {n} group(s) of same-named documents",
"dups.note": "Same name is not the same thing as duplicate — only you know which copy to keep. This reports, and never deletes anything for you.",
"dups.group": "\"{name}\" ×{n}",
"dups.none": "No same-named documents — this library is clean.",
"dups.close": "Collapse",
"dups.failed": "Duplicate report failed — check the terminal for the error.",
"pending.title": "Deletion records awaiting re-check ({n})",
"pending.note": "Deletes are hard deletes, but the device pushes documents back under their original UUIDs when it holds local changes (resurrection). Once the device has synced, hit \"Resurrection re-check\"; clear the records when it comes back clean.",
"pending.clear": "Clear",
"pending.recheck": "Resurrection re-check",
"pending.clearAll": "Clear all",
"recheck.failed": "Re-check failed — check the terminal for the error.",
"recheck.back": "⚠ {n} came back from the device under the original UUIDs:",
"recheck.backTail": "\nDelete them again, and leave them alone on the device afterwards.",
"recheck.clean": "✓ Re-checked {n}; no UUID is back on the tree. Once you are satisfied, hit \"Clear all\".",
"preview.title": "rmclient — Notebook preview",
"preview.loading": "Loading…",
"preview.failed": "Cannot open",
"preview.exportPdf": "Export PDF",
"preview.prev": "← Previous",
"preview.next": "Next →",
"preview.keyHint": "← → keys turn pages",
"preview.count": "Page {n} / {total}",
"preview.kind": "{type} · pages: {pages}",
"preview.pageAlt": "Page {n}",
"preview.pageFailed": "This page did not render"
},
"zh": {
"lang.label": "中文",
"lang.aria": "语言",
"nav.aria": "页面导航",
"nav.push": "推书",
"nav.tree": "文档树",
"toast.close": "关闭",
"dialog.cancel": "取消",
"folder.root": "（根级）",
"error.http": "失败：HTTP {status}",
"error.mailbox": "被拒绝：那是锁定目录。",
"error.not_found": "服务端找不到这一项。",
"error.invalid": "被拒绝：请求不合法。",
"error.upstream": "云端拒绝了这个请求。",
"error.bad_target": "目标目录不行。",
"error.duplicate": "那里已经有同名的书了。",
"error.tree_changed": "你确认过的那份清单已经过期了。",
"error.unsupported": "这份文档不能预览。",
"push.title": "rmclient — 推书",
"push.crumb": "推书",
"push.heading": "推书到 reMarkable",
"push.target": "目标目录",
"push.force": "重名也传",
"push.drop.big": "把 .epub / .pdf / .rmdoc 拖到这里",
"push.drop.hint": "或点击选择文件。后缀必须和内容一致——服务端不校验，本机会先拒掉。",
"push.state.uploading": "上传中",
"push.state.done": "已上传",
"push.state.skipped": "重名未传",
"push.state.refused": "被拒绝",
"push.foldersFailed": "读不到文档树，看下终端里的报错",
"push.uploaded": "「{name}」→ {target}",
"push.dupWarn": "⚠ 同名的还有 {copies} 份，设备端会看到 {total} 本同名书",
"push.syncNote": "设备端需要同步一次才会出现",
"push.dupCard": "{target} 里已经有 {copies} 份同名的书。\n服务端不覆盖也不去重：再传会多出一份独立副本，设备端两本无法区分。\n确实要传：勾上「重名也传」再拖一次。",
"tree.title": "rmclient — 文档树",
"tree.crumb": "文档树",
"tree.search": "搜索可见名（子串，不分大小写）",
"tree.sort": "排序",
"tree.sort.name": "名字",
"tree.sort.modified": "修改时间",
"tree.sort.size": "大小",
"tree.newRoot": "＋ 新建根级目录",
"tree.dupCheck": "重名检测",
"tree.reload": "刷新",
"tree.batch.aria": "批量操作",
"tree.trash": "回收站（{n} 项，只读）",
"tree.items": "{n} 项",
"tree.loadFailed": "读不到文档树，看下终端里的报错",
"tree.empty.filtered": "没有名字含「{filter}」的条目。换个词，或清空搜索框看全部。",
"tree.empty": "这个目录是空的。用目录行上的「传到这里」推一本书进来。",
"badge.readonly": "只读",
"badge.readonlyLock": "🔒 只读",
"act.preview": "预览",
"act.download": "下载",
"act.download.title": "取回原件（epub/pdf 给原文件本身，笔记给整包）。不含设备端批注。",
"act.package": "整包",
"act.package.title": "整包 .rmdoc：含设备端的批注与笔迹，以及设备为批注过的 epub 生成的 PDF 渲染件。",
"act.newFolder": "＋目录",
"act.uploadHere": "传到这里",
"act.rename": "重命名",
"act.move": "移动",
"act.delete": "删除",
"batch.selected": "已选 {n} 项",
"batch.label": "选中的 {n} 项",
"newFolder.title": "在「{parent}」里新建目录",
"newFolder.titleRoot": "新建根级目录",
"newFolder.placeholder": "目录名",
"newFolder.confirm": "新建",
"newFolder.done": "✓ 已新建目录「{name}」",
"rename.title": "重命名「{name}」",
"rename.confirm": "重命名",
"rename.done": "✓ 已重命名为「{name}」",
"move.title": "移动「{name}」",
"move.note": "原名会原样保留",
"move.confirm": "移动",
"move.done": "✓ 已移动「{name}」",
"move.many.title": "移动选中的 {n} 项",
"move.many.note": "每一项的原名都会原样保留",
"move.many.done": "移动完成：成功 {ok} 项，失败 {bad} 项",
"upload.done": "✓ 已上传「{name}」→ {target}",
"upload.dupTitle": "「{target}」里已经有同名的书",
"upload.dupBody": "服务端不覆盖也不去重：再传会多出一份独立副本，设备端两本无法区分。",
"upload.dupExisting": "已有：{id}",
"upload.dupConfirm": "仍然上传",
"upload.failed": "上传失败：HTTP {status}",
"delete.title": "删除{label}",
"delete.label": "「{name}」",
"delete.alarm": "硬删：不进回收站，不可撤销，并且会同步删掉设备上的文件。",
"delete.resurrect": "设备端如果对这些文档有本地变更，下次同步可能把它们原 UUID 推回来（复活）。",
"delete.count": "将删除 {n} 项（先深后浅）：",
"delete.confirm": "确认删除",
"delete.treeChanged": "\n（多半是设备同步动过这棵子树，重新点一次删除再看一遍清单）",
"delete.residue": "已删 {n} 项，但复查发现 {r} 项还在树上：{ids}",
"delete.done": "✓ 已删除 {n} 项，删完立刻复查未见残留。\n复活要等设备同步一轮才看得出来——记录已存到本地，过几分钟用上面的「复活复查」再查一次。",
"dups.title": "重名检测：{n} 组同名文档",
"dups.note": "同名不等于重复——哪一份该留只有你知道，这里只报告，不提供自动删除。",
"dups.group": "「{name}」×{n}",
"dups.none": "没有同名文档——这个库是干净的。",
"dups.close": "收起",
"dups.failed": "重名检测失败，看下终端里的报错",
"pending.title": "删除记录待复查（{n} 项）",
"pending.note": "删除是硬删，但设备端对这些文档有本地变更时会把它们原 UUID 推回来（复活）。设备同步一轮之后点「复活复查」确认一下，确认干净了就清掉记录。",
"pending.clear": "清除",
"pending.recheck": "复活复查",
"pending.clearAll": "全部清除",
"recheck.failed": "复查失败，看下终端里的报错",
"recheck.back": "⚠ {n} 项被设备端原 UUID 推回来了：",
"recheck.backTail": "\n再删一次，并且删完别在设备上碰它。",
"recheck.clean": "✓ 复查了 {n} 条记录，没有 UUID 回到树上。确认干净了就点「全部清除」。",
"preview.title": "rmclient — 笔记预览",
"preview.loading": "读取中…",
"preview.failed": "打不开",
"preview.exportPdf": "导出 PDF",
"preview.prev": "← 上一页",
"preview.next": "下一页 →",
"preview.keyHint": "键盘 ← → 也能翻",
"preview.count": "第 {n} / {total} 页",
"preview.kind": "{type} · {pages} 页",
"preview.pageAlt": "第 {n} 页",
"preview.pageFailed": "这一页没渲染出来"
}
};

const LANG_KEY = 'rmclient.lang';

// localStorage → navigator.language → en。存的值不认识就当没存过。
function detect() {
  let saved = null;
  try { saved = localStorage.getItem(LANG_KEY); } catch (e) { /* 隐私模式：当没存过 */ }
  if (saved && STRINGS[saved]) return saved;
  const nav = (navigator.language || '').toLowerCase();
  if (nav.startsWith('zh')) return 'zh';
  return 'en';
}

let LANG = detect();
document.documentElement.lang = LANG;

// 缺 key 时回落到英文，再回落到 key 本身——漏翻是看得见的，不是空白。
function t(key, vars) {
  const raw = (STRINGS[LANG] && STRINGS[LANG][key]) || STRINGS.en[key] || key;
  if (!vars) return raw;
  return raw.replace(/\{(\w+)\}/g, (m, name) => (name in vars ? String(vars[name]) : m));
}

// 服务端 HTTP 错误：reason 码给本地化主提示，服务端 message 原样作详情。
function httpError(status, detail) {
  const reason = detail && detail.reason;
  const known = reason && STRINGS.en['error.' + reason];
  const head = known ? t('error.' + reason) : t('error.http', {status});
  const message = detail && detail.message;
  return message ? head + '\n' + message : head;
}

// 静态文案：HTML 里写 data-i18n（以及 -placeholder / -title / -aria-label）。
const ATTRS = {'data-i18n-placeholder': 'placeholder', 'data-i18n-title': 'title',
               'data-i18n-aria-label': 'aria-label'};

function applyStatic(root) {
  for (const node of (root || document).querySelectorAll('[data-i18n]')) {
    node.textContent = t(node.getAttribute('data-i18n'));
  }
  for (const [data, attr] of Object.entries(ATTRS)) {
    for (const node of (root || document).querySelectorAll('[' + data + ']')) {
      node.setAttribute(attr, t(node.getAttribute(data)));
    }
  }
}

// 顶栏的语言切换：按钮直接从 STRINGS 的键生成，加一门语言不用碰这里。
function mountLangPicker() {
  const box = document.getElementById('langpick');
  if (!box) return;
  box.textContent = '';
  box.setAttribute('aria-label', t('lang.aria'));
  for (const code of Object.keys(STRINGS)) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = STRINGS[code]['lang.label'] || code;
    b.dataset.lang = code;
    b.setAttribute('aria-pressed', String(code === LANG));
    b.onclick = () => setLang(code);
    box.append(b);
  }
}

// 换语言：存下来，静态文案就地重刷，动态部分由各页监听 rmclient:lang 自己重画。
function setLang(code) {
  if (!STRINGS[code] || code === LANG) return;
  LANG = code;
  try { localStorage.setItem(LANG_KEY, code); } catch (e) { /* 存不下也照样切 */ }
  document.documentElement.lang = code;
  applyStatic(document);
  mountLangPicker();
  window.dispatchEvent(new CustomEvent('rmclient:lang', {detail: {lang: code}}));
}

document.addEventListener('DOMContentLoaded', () => { applyStatic(document); mountLangPicker(); });
