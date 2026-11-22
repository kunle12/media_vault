# Media Vault — developer notes

Media Vault is a Flask + SQLite media library inside the Kunle Workspace. It
has **no local login**: nginx gates `/mediavault/` through the guard and
forwards `X-Auth-User` / `X-Auth-Groups`.

## Layout

| Path | Purpose |
|---|---|
| `app.py` | Flask app, proxy identity, library/upload/stream/delete routes |
| `config.py` | Environment-backed configuration |
| `storage.py` | Local, S3 and Azure storage backends |
| `templates/layout.html` | Shared media-deck shell, theme toggle, dialogs, logout |
| `templates/dashboard.html` | Library, stats, sorting, filtering, pagination |
| `templates/upload.html` | Dropzone and XHR progress |
| `templates/media_view.html` | Player and file details |
| `templates/error.html` | Themed 401/403/404/413/500 page |
| `static/mediavault.css` | Bridge/dawn theme and responsive layout |
| `test_app.py` | Flask test suite |

## Identity

`load_identity()` in `app.py` runs before every request except `static` and
`healthz`:

1. Reject non-loopback `request.remote_addr`.
2. Read `X-Auth-User`; reject if missing.
3. Find or create the local `users` row by email.
4. Store `g.user_id`, `g.email`, `g.groups`.

Views use `current_user_id()`. The decorator `login_required` documents the
requirement; the real refusal is the middleware and the themed 401 page.

Never add a password/email-code/OAuth login. The guard owns authentication.

## Data

```sql
users(id, email UNIQUE, created_at)
media(id, filename, original_filename, storage_key, file_size,
      uploaded_at, user_id REFERENCES users(id))
```

`storage_key` is an absolute local path or an object key. Local uploads live
in `videos/`, `audios/` and `images/` beneath `UPLOAD_FOLDER`.

Production storage is on `/media/nas`, a systemd automount with a 30-minute
idle timeout. `mediavault.service` requires `media-nas.automount`, and
`require_mount_point()` triggers the mount then refuses to run unless
`REQUIRE_MOUNT_POINT` is a real mount. Never remove that guard: without it a
missing USB disk would create a fresh database on the root filesystem.

## Adding a route

```python
@app.route("/thing")
@login_required
def thing():
    uid = current_user_id()
    ...
```

Keep routes prefix-aware: the app replaces `app.route` with `prefix_route`
and sets `APPLICATION_ROOT=/mediavault` in production.

## UI rules

- Use the tokens in `static/mediavault.css`; do not add a CDN.
- Bridge is the default; dawn is selected through `guard.theme`.
- Every destructive action uses `data-confirm` so the themed dialog handles it.
- Include `/guard-logout.js` on any new full-page shell so cross-tab logout
  redirects the tab.
- Do not restore the old rail: the mockups approved a full-width shell.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

Tests send `X-Auth-User` and set `REMOTE_ADDR=127.0.0.1`.
