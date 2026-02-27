# MediaVault - Claude Code Instructions

## Project Overview

MediaVault is a Flask-based personal multimedia management application with passwordless email authentication. Users can upload, view, and manage their video and audio collection.

## Tech Stack

- **Backend**: Flask 3.1.0 with Flask-WTF
- **Database**: SQLite (videodb.sqlite)
- **Caching**: Flask-Caching (simple or redis)
- **Frontend**: HTML/Jinja2 templates with minimal JavaScript
- **Linting**: ruff 0.15.2

## Key Files

| File | Purpose |
|------|---------|
| `app.py` | Main Flask application - routes, database, upload handling |
| `auth.py` | Authentication blueprint - email verification codes |
| `config.py` | Centralized configuration management with cached env vars |
| `storage.py` | Storage backend - local filesystem and AWS S3 support |
| `templates/` | Jinja2 HTML templates |

## Configuration

All environment variables are accessed through the `Config` class in `config.py`. Use `Config.METHOD()` to get cached values:

```python
from config import Config

# Get cached config values
secret_key = Config.SECRET_KEY()
upload_folder = Config.UPLOAD_FOLDER()
s3_enabled = Config.S3_ENABLED()
google_oauth_enabled = Config.GOOGLE_OAUTH_ENABLED()

# Helper functions
from config import is_s3_enabled, is_google_oauth_enabled, get_smtp_config, get_allowed_emails
```

## Running the App

```bash
python app.py
```

The app runs on `http://localhost:5050`

## Database Schema

### users
- `id` INTEGER PRIMARY KEY
- `email` TEXT UNIQUE
- `created_at` TIMESTAMP

### media
- `id` INTEGER PRIMARY KEY
- `filename` TEXT (stored filename with UUID prefix)
- `original_filename` TEXT
- `storage_key` TEXT (local path or S3 key)
- `file_size` INTEGER
- `uploaded_at` TIMESTAMP
- `user_id` INTEGER (FK to users)

## Authentication Flow

1. User enters email in auth modal
2. System checks if email is in `ALLOWED_EMAILS` env var
3. 6-character verification code generated (valid 5 minutes, 5 attempts max)
4. Code sent via email (or debug printed to console if no SMTP configured)
5. User enters code to login
6. Session created with user_id

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| SECRET_KEY | auto-generated | Flask secret key |
| ALLOWED_EMAILS | - | Whitespace-separated allowed email addresses |
| UPLOAD_FOLDER | uploads | Media storage directory (local only) |
| DATABASE | videodb.sqlite | SQLite database |
| MAX_CONTENT_LENGTH | 524288000 | 500MB max upload |
| CACHE_TYPE | simple | simple or redis |
| S3_BUCKET | - | S3 bucket name (enables S3 storage) |
| S3_PREFIX | - | S3 key prefix |
| AWS_REGION | - | AWS region for S3 |
| AWS_DEFAULT_REGION | - | AWS default region |
| EMAIL_PROVIDER | generic | generic or aws_ses |
| SMTP_HOST | - | SMTP server |
| SMTP_PORT | 587 | SMTP port |
| SMTP_USER | - | SMTP username |
| SMTP_PASSWORD | - | SMTP password |
| FROM_EMAIL | - | Sender email |

## Allowed File Extensions

**Video**: mp4, avi, mov, mkv, wmv, flv, webm
**Audio**: mp3, wav, ogg

## Important Implementation Details

1. **Rate limiting**: 60 seconds between code requests per email
2. **Code expiry**: 5 minutes (300 seconds)
3. **Max retry attempts**: 5 per code
4. **Session**: Permanent session with user_id stored in session
5. **Upload**: Files saved with UUID prefix to avoid name collisions

## Media Routes

| Route | Purpose |
|-------|---------|
| `/media/<id>` | View media player page |
| `/media/<id>/play` | Stream media for inline playback |
| `/media/<id>/download` | Download media file (properly encodes non-ASCII filenames) |

**Filename encoding**: Non-ASCII filenames in Content-Disposition headers are encoded using RFC 5987 (`filename*=UTF-8''...`) to ensure browser compatibility.

## Linting

```bash
ruff check .
```

## Adding a New Route

1. Add route to `app.py` (main routes) or `auth.py` (auth routes)
2. Use `@login_required` decorator for protected routes
3. Use `session["user_id"]` to get current user
4. Return `render_template()` or `jsonify()`

## Database Access

```python
from app import get_db_connection

conn = get_db_connection()
cursor = conn.cursor()
cursor.execute("SELECT * FROM media WHERE user_id = ?", (session["user_id"],))
media = cursor.fetchall()
conn.close()
```
