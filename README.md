# Media Vault

A per-user media library for the Kunle Workspace. It stores video, audio and
images on the NAS, streams them with HTTP range requests, and signs users in
through the workspace guard instead of keeping its own email login.

The UI follows the workspace “media deck” language: Saira/IBM Plex Mono,
the bridge (dark) and dawn (light) palettes, and the same `guard.theme`
preference as the console.

## What it does

- Lists the signed-in user's media with sorting, filtering and pagination
- Uploads multiple files with drag-and-drop and live progress
- Streams video/audio with range requests and inline images
- Downloads files with RFC 5987 non-ASCII filenames
- Deletes files through a themed confirmation dialog
- Stores files locally (default) or on S3/Azure Blob
- Exposes `/mediavault/healthz` for the operator

It does **not** have a local password, email-code, or Google login. Identity
comes from the guard through nginx.

## Identity contract

nginx runs the guard's `auth_request` and sets these headers on every request
it proxies to Media Vault:

| Header | Meaning |
|---|---|
| `X-Auth-User` | verified email address |
| `X-Auth-Groups` | comma-separated guard groups |
| `X-Auth-Sid` | session id (not used by the app) |

The app accepts the identity header **only from loopback** (`127.0.0.1` /
`::1`) and refuses a request without it with a themed `401`. Never expose
gunicorn on a public interface.

The app maps the email to its local `users` row, creating one on first sight.
Existing rows are reused by email, so media ownership survives the migration
from the old login.

## Install

### Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env.local      # edit paths if needed
.venv/bin/python app.py         # http://127.0.0.1:5050
```

Flask has no local login, so send the header the guard would send:

```bash
curl -H 'X-Auth-User: you@example.com' http://127.0.0.1:5050/dashboard
```

### Production on `lion`

The app lives at `/srv/media_vault`, runs as `www-data` on
`127.0.0.1:5050`, and reads `/srv/media_vault/.env.local`. The unit declares
`RequiresMountsFor=/media/nas`, so it will not start and create an empty
database on the root disk when the USB disk is missing.

```bash
sudo APP_DIR=/srv/media_vault ./deployment/deploy.sh
```

nginx owns the public route:

- `location = /mediavault` → `308 /mediavault/`
- `location /mediavault/` → `auth_request /_authz`, forward
  `X-Auth-User` / `X-Auth-Groups`, strip `__Host-sso`, proxy to
  `127.0.0.1:5050`
- `client_max_body_size 500M` and a longer read timeout for uploads

The guard app registry must contain `mediavault` with `path_prefix
/mediavault` and the `users` group.

## Configuration

Environment variables are read from `.env.local` (see `.env.example`).

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | random | Flask signing key; only used for the optional sort-preference cookie |
| `APPLICATION_ROOT` | `/` | URL prefix; production uses `/mediavault` |
| `SERVER_NAME` | empty | Optional external host |
| `UPLOAD_FOLDER` | `uploads` | Local storage directory |
| `DATABASE` | `videodb.sqlite` | SQLite database path |
| `MAX_CONTENT_LENGTH_MB` | `500` | Per-request upload limit |
| `ITEMS_PER_PAGE` | `50` | Library page size |
| `S3_BUCKET` | empty | Enables S3 storage |
| `S3_PREFIX` | empty | S3 key prefix |
| `S3_ENDPOINT` | empty | Custom S3 endpoint |
| `AWS_REGION` | `us-east-1` | S3 region |
| `AZURE_STORAGE_ACCOUNT` | empty | Enables Azure Blob storage |
| `AZURE_STORAGE_KEY` | empty | Azure account key |
| `AZURE_CONTAINER` | `media` | Azure container |
| `AZURE_CONNECTION_STRING` | empty | Alternative Azure credential |

## Routes

| Route | Method | Description |
|---|---|---|
| `/` | GET | Redirects to the library |
| `/dashboard` | GET | Library, sorting and pagination |
| `/upload` | GET, POST | Upload form and processing |
| `/media/<id>` | GET | Player and file details |
| `/media/<id>/play` | GET | Stream with range requests |
| `/media/<id>/download` | GET | Download |
| `/media/<id>/delete` | POST | Delete file and row |
| `/healthz` | GET | Database and storage check |

All routes except `/healthz` and `/static/` require a trusted identity header.

## Data model

```text
users(id, email UNIQUE, created_at)
media(id, filename, original_filename, storage_key, file_size,
      uploaded_at, user_id → users.id)
```

`storage_key` is an absolute path for local storage or an object key for
S3/Azure. Local files are grouped into `videos/`, `audios/` and `images/`.

## Supported formats

- Video: mp4, avi, mov, wmv, flv, webm
- Audio: mp3, wav, ogg
- Image: png, jpg, jpeg, gif, webp, bmp, heic

## Theme

The header toggle cycles `bridge` and `dawn` and writes the shared
`guard.theme` key. The app also listens for the guard's cross-tab logout
event through `/guard-logout.js`; signing out of the console redirects open
vault tabs to `/login`.

## Tests

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

The suite covers identity refusal, first-sight provisioning, per-user media
isolation, uploads, range streaming, downloads, deletion, health checks and
the themed error pages.

## Known limitations

- The app trusts `X-Auth-User` from loopback only. Any local process that can
  reach port 5050 can impersonate a user; keep the service on `127.0.0.1`.
- A media stream that is already open can outlive guard logout until the
  request finishes. The guard session still blocks every new request.
- S3 and Azure backends are supported but not exercised by the default
  deployment.
- The NAS is a single USB disk. `mediavault.service` refuses to start without
  it, but backups are still the operator's responsibility.
