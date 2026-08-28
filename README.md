# rmclient

A local web UI and CLI for your own [rmfakecloud](https://github.com/ddvk/rmfakecloud)
server: push books to your reMarkable, organise the document tree, preview
notebooks, download originals, and find duplicates — all from your laptop,
talking to your cloud over its `/ui/api` endpoints.

*[中文版](README.zh-CN.md)*

Nothing runs on the server and nothing is installed on the device: rmclient is
just another API consumer. Everything is a single Python process; the web UI is
plain HTML/CSS/JS with no build chain and no external resources, so it works
offline.

**Status:** works against rmfakecloud **v0.0.31**, which is the only version it
has been tested on. The endpoint contract and its pitfalls are documented in
[`spike/REPORT.md`](spike/REPORT.md).

## What you get

| Page | What it does |
|---|---|
| `/` | Drag epub/pdf/rmdoc in, pick a target folder, upload. Per-file progress and results. |
| `/tree` | The whole document tree: search, sort, create/rename/move/delete (single or multi-select), upload into any folder, download originals, duplicate report. |
| `/preview/<id>` | Render a notebook's pages as SVG, page through them, export the whole notebook as PDF. |

The CLI covers pushing:

```bash
rmclient push book.epub                    # into the root
rmclient push book.epub --to Books/CS      # into a folder, addressed by visible name
rmclient push book.epub --to Books --force # push even though a same-named book exists
rmclient serve --port 8000                 # start the web UI
```

## Quickstart

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
git clone <this repo> && cd rmclient
uv sync

export RMCLIENT_URL=https://cloud.example.com
export RMCLIENT_USER=you@example.com
export RMCLIENT_PASSWORD_FILE=~/.config/rmclient/password   # or RMCLIENT_PASSWORD

uv run rmclient serve            # → http://127.0.0.1:8000
```

Read-only sanity check before anything else:

```bash
uv run python scripts/dump_tree.py    # prints the whole tree, including the trash
```

## Configuration

All configuration is environment variables. There is no config file.

| Variable | Default | Meaning |
|---|---|---|
| `RMCLIENT_URL` | — | Your rmfakecloud base URL, including the scheme. Trailing slash is ignored. |
| `RMCLIENT_USER` | — | Login e-mail. |
| `RMCLIENT_PASSWORD` | — | Password, used literally. |
| `RMCLIENT_PASSWORD_FILE` | — | Path to a file holding the password; its contents are stripped. Use this **or** `RMCLIENT_PASSWORD`, not both. |
| `RMCLIENT_LOCKED_FOLDERS` | `Mailbox` | Comma-separated **root-level** folder names to protect. Set to an empty string to lock nothing. |

If none of these are set, rmclient falls back to the local layout of its
original deployment (documented in `CLAUDE.md`), and only when those files
actually exist. Otherwise it refuses to start and tells you which variables to
set — it will never quietly connect somewhere unexpected.

Credentials are read from the environment or from disk and are never logged,
never printed, and never written to the repository.

## Locked folders

A locked folder is a root-level folder whose entire subtree is read-only:

- it is **shown** in the tree, marked with a lock, and gets no write controls;
- it is excluded from every bulk operation and has no selection checkbox;
- create / rename / move / delete / upload are refused for anything inside it,
  and the check runs **server-side**, not just in the UI;
- read-only access is still allowed: you can preview and download its documents.

Nested folders with the same name are not locked — only the root-level one is.

## Safety notes

These come out of real testing against a live server; the details, with
evidence, are in [`spike/REPORT.md`](spike/REPORT.md).

- **Deletion is permanent and reaches the device.** There is no trash on the
  server side of this operation: a delete removes the document and the device
  drops its copy on the next sync. rmclient always shows the full subtree it is
  about to delete before you confirm, deletes deepest-first (the server does not
  cascade), and only ever deletes UUIDs from an explicit allow-list.
- **Deleted documents can come back.** If the device has local changes for a
  document, its next sync pushes that document back with the same UUID.
  rmclient records every deletion in `var/deleted.json` (never committed) and
  keeps a "check for resurrection" panel on the tree page, because the race
  only becomes visible a sync cycle later.
- **Upload correctness is the client's job.** The server dispatches purely on
  the file extension (`.pdf`, `.epub`, `.rmdoc`), does not look at the content,
  and rejects unknown extensions with an HTTP 500 whose real reason is in the
  body. rmclient validates the extension *and* the content locally (EPUB OCF
  structure, PDF/zip magic) and refuses to send a mismatch.
- **Duplicate uploads are never merged.** Uploading the same file name twice
  produces two independent documents with the same visible name. rmclient warns
  and requires an explicit confirmation instead of silently doubling a book.
- **Renaming is implicit in moving.** The move endpoint overwrites the name
  unconditionally, so rmclient always sends the original name back when you only
  meant to move something.
- **The duplicate report never deletes anything.** It groups documents by
  visible name and shows you where they are; which copy to keep is your call.

## API contract at a glance

What rmclient relies on, and the trap attached to each endpoint. Full evidence
in [`spike/REPORT.md`](spike/REPORT.md).

| Operation | Endpoint | The catch |
|---|---|---|
| Log in | `POST /ui/api/login` | The response body *is* the JWT; send it back as `Authorization: Bearer`, not as a cookie. |
| List tree | `GET /ui/api/documents` | Reads use lower-case keys, writes return upper-case ones. A freshly uploaded document's `type` echoes its name — don't trust it. |
| Upload | `POST /ui/api/documents/upload` | Dispatch is 100% on the file extension (`.pdf`/`.epub`/`.rmdoc`); content is never checked. Unsupported extensions come back as HTTP 500 with the reason in the body. |
| Move / rename | `PUT /ui/api/documents` | `name` is overwritten unconditionally, so a pure move must send the old name back. `parentId: ""` means the root. |
| Delete | `DELETE /ui/api/documents/{id}` | Permanent, no trash, and it propagates to the device. A device with local changes can push the document back under the same UUID. |
| Export | `GET /ui/api/documents/{id}?type=rmdoc` | A zip with the original bytes intact. The `.content` inside is the only reliable `fileType`. |

## Compatibility

- Tested only against **rmfakecloud v0.0.31**. Other versions may differ; the
  observed contract is written down in `spike/REPORT.md`.
- Authentication uses `Authorization: Bearer` rather than cookies.
- If your server sits behind a Cloudflare tunnel, note the 100 MB limit per
  request on the free edge: exporting a large notebook or downloading a large
  book can hit it. Exports are also buffered whole in memory and run under a
  120 s read timeout.
- A document's `size` in the tree is the sum of all its blobs, not the size of
  the original file.

## Development

```bash
uv run pytest        # offline test suite; never touches a real server
```

The tests use `httpx.MockTransport` and FastAPI's `TestClient` throughout,
including synthetic `.rm` scene data for the renderer, so the whole suite runs
without credentials.

```
rmclient/     library + app: config, models, api, validate, push, manage,
              render, journal, cli, web (pages/ holds the HTML and CSS)
scripts/      dump_tree.py — read-only tree dump
spike/        the feasibility work and REPORT.md, the endpoint contract
tests/        offline test suite
```

The scripts under `spike/` do write to a real server. They confine themselves to
a temporary `rmclient-spike-<random>` folder and clean up after themselves.
