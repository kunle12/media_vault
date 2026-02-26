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
| `templates/` | Jinja2 HTML templates |
| `allowed_emails.txt` | Whitelist of authorized users |

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

### videos
- `id` INTEGER PRIMARY KEY
- `filename` TEXT (stored filename with UUID prefix)
- `original_filename` TEXT
- `file_path` TEXT
- `file_size` INTEGER
- `uploaded_at` TIMESTAMP
- `user_id` INTEGER (FK to users)

## Authentication Flow

1. User enters email in auth modal
2. System checks if email is in `allowed_emails.txt`
3. 6-character verification code generated (valid 5 minutes, 5 attempts max)
4. Code sent via email (or debug printed to console if no SMTP configured)
5. User enters code to login
6. Session created with user_id

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| SECRET_KEY | auto-generated | Flask secret key |
| UPLOAD_FOLDER | uploads | Media storage directory |
| DATABASE | videodb.sqlite | SQLite database |
| MAX_CONTENT_LENGTH | 524288000 | 500MB max upload |
| CACHE_TYPE | simple | simple or redis |
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
cursor.execute("SELECT * FROM videos WHERE user_id = ?", (session["user_id"],))
videos = cursor.fetchall()
conn.close()
```
