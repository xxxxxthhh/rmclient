"""本地 Web：拖一本书进去就上传。单进程，无构建链。

    rmclient serve            # → http://127.0.0.1:8000

上传走的是和 CLI 完全同一条路径（push → api.upload → validate），Web 这层只负责
把结果翻译成 HTTP 状态码和页面提示。目录下拉框里没有信箱，服务端还会再查一次
（下拉框过滤只是展示，拦不住直接带 id 打过来的请求）。
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from .api import RmApiError, RmClient
from .models import Folder, PathError, Tree, walk
from .push import DuplicateName, push
from .validate import ValidationError

app = FastAPI(title="rmclient")

_client: RmClient | None = None


def get_client() -> RmClient:
    """惰性建连：import 这个模块不该去读凭据、更不该打云端（测试要能覆盖掉它）。"""
    global _client
    if _client is None:
        client = RmClient()
        client.login()
        _client = client
    return _client


def folder_options(tree: Tree) -> list[dict]:
    """可选目标目录（信箱整棵子树不出现在选项里）。"""
    options = [{"id": "", "path": "（根级）"}]
    options += sorted(
        (
            {"id": node.id, "path": "/".join(path + (node.name,))}
            for path, node in walk(tree.entries, skip_mailbox=True)
            if isinstance(node, Folder)
        ),
        key=lambda o: o["path"],
    )
    return options


@app.get("/api/folders")
def api_folders(client: RmClient = Depends(get_client)) -> dict:
    return {"folders": folder_options(client.list_tree())}


@app.post("/api/upload")
async def api_upload(
    file: UploadFile = File(...),
    parent: str = Form(""),
    force: bool = Form(False),
    client: RmClient = Depends(get_client),
) -> dict:
    data = await file.read()
    try:
        node, existing = push(client, data, file.filename or "", parent_id=parent, force=force)
    except ValidationError as exc:
        raise HTTPException(400, {"reason": "invalid", "message": str(exc)}) from exc
    except PathError as exc:
        raise HTTPException(400, {"reason": "bad_target", "message": str(exc)}) from exc
    except PermissionError as exc:
        raise HTTPException(403, {"reason": "mailbox", "message": str(exc)}) from exc
    except DuplicateName as exc:
        raise HTTPException(
            409,
            {
                "reason": "duplicate",
                "message": str(exc),
                "existing": [{"id": d.id, "name": d.name, "size": d.size} for d in exc.existing],
            },
        ) from exc
    except RmApiError as exc:
        raise HTTPException(502, {"reason": "upstream", "message": str(exc)}) from exc
    return {
        "id": node.id,
        "name": node.name,
        "duplicates": len(existing),
    }


PAGE = """<!doctype html>
<meta charset="utf-8"><title>rmclient — 推书</title>
<style>
 body{font:15px/1.6 system-ui,sans-serif;max-width:44rem;margin:3rem auto;padding:0 1rem;color:#222}
 h1{font-size:1.3rem}
 #drop{border:2px dashed #bbb;border-radius:10px;padding:3rem 1rem;text-align:center;color:#666;
       transition:.15s;cursor:pointer}
 #drop.hot{border-color:#333;background:#f6f6f6;color:#222}
 .row{margin:1rem 0;display:flex;gap:.6rem;align-items:center;flex-wrap:wrap}
 select{flex:1;min-width:14rem;padding:.35rem}
 .msg{padding:.8rem 1rem;border-radius:8px;margin:.6rem 0;white-space:pre-wrap}
 .ok{background:#e8f5e9}.err{background:#fdecea}.warn{background:#fff8e1}
 code{background:#f0f0f0;padding:.1rem .3rem;border-radius:4px}
</style>
<h1>推书到 reMarkable</h1>
<div class="row">
  <label>目标目录</label>
  <select id="parent"></select>
  <label><input type="checkbox" id="force"> 重名也传</label>
</div>
<div id="drop">把 .epub / .pdf / .rmdoc 拖到这里，或点击选择</div>
<input type="file" id="picker" hidden accept=".epub,.pdf,.rmdoc">
<div id="log"></div>
<script>
const drop = document.getElementById('drop'), picker = document.getElementById('picker'),
      parent = document.getElementById('parent'), force = document.getElementById('force'),
      log = document.getElementById('log');

function say(cls, text) {
  const div = document.createElement('div');
  div.className = 'msg ' + cls; div.textContent = text;
  log.prepend(div);
}

fetch('/api/folders').then(r => r.json()).then(d => {
  for (const f of d.folders) {
    const o = document.createElement('option');
    o.value = f.id; o.textContent = f.path; parent.append(o);
  }
}).catch(() => say('err', '读不到文档树，看下终端里的报错'));

async function upload(file) {
  const body = new FormData();
  body.append('file', file); body.append('parent', parent.value);
  body.append('force', force.checked ? 'true' : 'false');
  say('warn', `上传中：${file.name} → ${parent.options[parent.selectedIndex].text}`);
  const r = await fetch('/api/upload', {method: 'POST', body});
  const d = await r.json().catch(() => ({}));
  if (r.ok) {
    let text = `✓ 已上传「${d.name}」\\nUUID ${d.id}\\n设备端需要同步一次才会出现`;
    if (d.duplicates) text += `\\n⚠ 同名的还有 ${d.duplicates} 份，设备端会看到 ${d.duplicates + 1} 本同名书`;
    say('ok', text);
    return;
  }
  const detail = d.detail || {};
  if (detail.reason === 'duplicate') {
    const names = (detail.existing || []).map(e => `  已有：${e.id}`).join('\\n');
    say('err', `目标目录里已经有同名的书（${(detail.existing || []).length} 份）。\\n` +
               `服务端不覆盖也不去重：再传会多出一份独立副本，设备端两本无法区分。\\n` +
               `确实要传就勾上「重名也传」。\\n${names}`);
  } else {
    say('err', detail.message || `失败：HTTP ${r.status}`);
  }
}

drop.onclick = () => picker.click();
picker.onchange = () => { for (const f of picker.files) upload(f); picker.value = ''; };
drop.ondragover = e => { e.preventDefault(); drop.classList.add('hot'); };
drop.ondragleave = () => drop.classList.remove('hot');
drop.ondrop = e => {
  e.preventDefault(); drop.classList.remove('hot');
  for (const f of e.dataTransfer.files) upload(f);
};
</script>
"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE
