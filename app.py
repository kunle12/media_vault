"""MediaVault - Flask application for managing video and audio files."""

import os
import sqlite3
import sys
import uuid
from datetime import timedelta
from functools import wraps
from typing import Any

from flask import (
    Flask,
    Response,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_caching import Cache
from loguru import logger

from auth import auth_bp, is_google_oauth_enabled
from config import Config
from storage import S3UploadError, StorageError, get_storage_backend, is_s3_enabled

logger.remove()

logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)

logger.add(
    "logs/app.log",
    rotation="1 day",
    retention="7 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
)

logger.info("MediaVault application starting")

app = Flask(__name__)
app.config["SECRET_KEY"] = Config.SECRET_KEY()
app.config["WTF_CSRF_ENABLED"] = True
app.config["WTF_CSRF_TIME_LIMIT"] = None
app.config["UPLOAD_FOLDER"] = Config.UPLOAD_FOLDER()
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH()
app.config["ALLOWED_EXTENSIONS"] = Config.ALLOWED_EXTENSIONS
app.config["DATABASE"] = Config.DATABASE()
app.config["APPLICATION_ROOT"] = Config.APPLICATION_ROOT()
server_name = Config.SERVER_NAME()
if server_name:
    app.config["SERVER_NAME"] = server_name

cache_type = Config.CACHE_TYPE()
if cache_type == "redis":
    app.config["CACHE_REDIS_URL"] = Config.CACHE_REDIS_URL()
app.config["CACHE_TYPE"] = cache_type
app.config["CACHE_DEFAULT_TIMEOUT"] = Config.CACHE_DEFAULT_TIMEOUT

cache = Cache(app)

app.config["GOOGLE_OAUTH_ENABLED"] = is_google_oauth_enabled()

session_timeout_minutes = Config.SESSION_TIMEOUT_MINUTES()
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=session_timeout_minutes)
logger.info(f"Session timeout set to {session_timeout_minutes} minutes")

application_root = Config.APPLICATION_ROOT()
app.jinja_env.globals["application_root"] = (
    application_root if application_root != "/" else ""
)

_original_route = app.route
_app_root = application_root


def prefix_route(route, *args, **kwargs):
    """Add application_root prefix to routes."""
    if _app_root != "/" and not route.startswith(_app_root):
        route = _app_root.rstrip("/") + "/" + route.lstrip("/")
    return _original_route(route, *args, **kwargs)


app.route = prefix_route

app.register_blueprint(
    auth_bp, url_prefix=application_root if application_root != "/" else None
)


@app.before_request
def extend_session() -> None:
    """Slide session expiry on each request for authenticated users."""
    if "user_id" in session:
        session.modified = True


@app.after_request
def add_security_headers(response: Response) -> Response:
    """Add Content-Security-Policy and other security headers."""
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


# Initialize storage backend
storage = get_storage_backend()
logger.info(f"Storage backend initialized: {type(storage).__name__}")


# Database setup
def get_db_connection() -> sqlite3.Connection:
    """Get SQLite database connection."""
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize database tables and indexes."""
    with app.app_context():
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            storage_key TEXT NOT NULL,
            file_size INTEGER NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_media_user_id ON media(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")

        conn.commit()
        conn.close()


def ensure_upload_folder() -> None:
    """Create upload folder if it doesn't exist."""
    if not is_s3_enabled():
        upload_folder = app.config["UPLOAD_FOLDER"]
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)


# Helper functions
def allowed_file(filename: str) -> bool:
    """Check if filename has an allowed extension."""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


def login_required(f):
    """Decorator to require authentication for routes."""

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        if "user_id" not in session:
            return render_template("auth_trigger.html")
        return f(*args, **kwargs)

    return decorated_function


# Routes
@app.route("/")
def index() -> Any:
    """Home page - redirect to dashboard if authenticated."""
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/trigger-auth")
def trigger_auth() -> Any:
    """Render the auth trigger page."""
    return render_template("auth_trigger.html")


@app.route("/dashboard")
@login_required
def dashboard() -> Any:
    """User dashboard showing their uploaded media."""
    sort = request.args.get("sort")

    if sort is None:
        sort = session.get("sort_preference", "newest")

    valid_sorts = [
        "newest",
        "oldest",
        "name_asc",
        "name_desc",
        "size_desc",
        "size_asc",
        "type",
    ]
    if sort not in valid_sorts:
        sort = "newest"

    order_by_clauses = {
        "newest": "uploaded_at DESC",
        "oldest": "uploaded_at ASC",
        "name_asc": "original_filename ASC",
        "name_desc": "original_filename DESC",
        "size_desc": "file_size DESC",
        "size_asc": "file_size ASC",
        "type": """CASE
            WHEN filename GLOB '*.mp4' OR filename GLOB '*.avi' OR filename GLOB '*.mov' OR filename GLOB '*.wmv' OR filename GLOB '*.flv' OR filename GLOB '*.webm' THEN 1
            WHEN filename GLOB '*.mp3' OR filename GLOB '*.wav' OR filename GLOB '*.ogg' THEN 2
            ELSE 3 END, uploaded_at DESC""",
    }

    if sort not in valid_sorts:
        sort = "newest"
    order_by = order_by_clauses[sort]

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM media WHERE user_id = ? ORDER BY " + order_by,
        (session["user_id"],),
    )
    media = cursor.fetchall()
    conn.close()
    return render_template("dashboard.html", media=media, current_sort=sort)


@app.route("/dashboard/set_sort", methods=["POST"])
@login_required
def set_sort_preference() -> Any:
    """Save user's sort preference to session."""
    sort = request.form.get("sort", "newest")
    valid_sorts = [
        "newest",
        "oldest",
        "name_asc",
        "name_desc",
        "size_desc",
        "size_asc",
        "type",
    ]
    if sort not in valid_sorts:
        sort = "newest"
    session["sort_preference"] = sort
    return redirect(url_for("dashboard"))


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload() -> Any:
    """Handle file upload - GET shows form, POST processes uploads."""
    if request.method == "POST":
        files = request.files.getlist("files")

        if not files or all(f.filename == "" for f in files):
            flash("No selected file", "error")
            return redirect(request.url)

        uploaded_count = 0
        error_count = 0
        s3_error = None

        for file in files:
            if file.filename == "":
                continue

            if file and allowed_file(file.filename):
                original_filename = os.path.basename(file.filename or "")
                unique_filename = f"{uuid.uuid4()}_{original_filename}"

                try:
                    file_size = 0
                    if is_s3_enabled():
                        file.seek(0, os.SEEK_END)
                        file_size = file.tell()
                        file.seek(0)
                    storage_key = storage.save(file, unique_filename)
                    if not is_s3_enabled():
                        file_size = os.path.getsize(storage_key)

                    conn = get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute(
                        "INSERT INTO media (filename, original_filename, storage_key, file_size, user_id) VALUES (?, ?, ?, ?, ?)",
                        (
                            unique_filename,
                            original_filename,
                            storage_key,
                            file_size,
                            session["user_id"],
                        ),
                    )
                    conn.commit()
                    conn.close()

                    uploaded_count += 1
                    logger.info(
                        f"File uploaded: {original_filename} ({file_size} bytes)"
                    )
                except S3UploadError as e:
                    logger.error(f"S3 upload error: {e}")
                    s3_error = str(e)
                    break
                except StorageError as e:
                    logger.error(f"Storage error during upload: {e}")
                    s3_error = str(e)
                    break
                except OSError as e:
                    logger.error(f"OS error during upload: {e}")
                    s3_error = f"OS error: {str(e)}"
                    break
                except Exception as e:
                    logger.exception(f"Unexpected error during upload: {e}")
                    s3_error = f"Unexpected error: {str(e)}"
                    break
            else:
                error_count += 1

        if s3_error:
            flash(f"Upload failed: {s3_error}", "error")
            if uploaded_count > 0:
                flash(f"{uploaded_count} file(s) uploaded before error", "warning")
        elif uploaded_count > 0:
            if uploaded_count == 1:
                flash("File uploaded successfully!", "success")
            else:
                flash(f"{uploaded_count} files uploaded successfully!", "success")
        if error_count > 0:
            flash(f"{error_count} file(s) skipped - invalid file type", "error")

        return redirect(url_for("dashboard"))

    max_size_mb = Config.MAX_CONTENT_LENGTH() // (1024 * 1024)
    return render_template("upload.html", max_size_mb=max_size_mb)


def validate_media_id(media_id: int) -> bool:
    """Return False if media_id is non-positive (invalid)."""
    return media_id > 0


@app.route("/media/<int:media_id>")
@login_required
def view_media(media_id: int) -> Any:
    """Display a single media file by ID."""
    if not validate_media_id(media_id):
        flash("Invalid media ID", "error")
        return redirect(url_for("dashboard"))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM media WHERE id = ? AND user_id = ?",
        (media_id, session["user_id"]),
    )
    media = cursor.fetchone()
    conn.close()

    if not media:
        flash("Media not found or you do not have permission to view it", "error")
        return redirect(url_for("dashboard"))

    return render_template("media_view.html", media=media)


def encode_filename_for_header(filename: str) -> str:
    """Encode filename for Content-Disposition header per RFC 5987."""
    try:
        filename.encode("ascii")
        return f'filename="{filename}"'
    except UnicodeEncodeError:
        import urllib.parse

        encoded = urllib.parse.quote(filename)
        return f"filename*=UTF-8''{encoded}"


def get_mime_type(filename: str) -> str:
    """Get MIME type based on file extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mime_types = {
        "mp4": "video/mp4",
        "avi": "video/x-msvideo",
        "mov": "video/quicktime",
        "wmv": "video/x-ms-wmv",
        "flv": "video/x-flv",
        "webm": "video/webm",
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "ogg": "audio/ogg",
    }
    return mime_types.get(ext, "application/octet-stream")


def parse_range_header(range_header: str, file_size: int) -> tuple | None:
    """Parse HTTP Range header, returning (start, end) or None if invalid.

    Supports: 'bytes=start-end', 'bytes=start-', 'bytes=-end' (suffix).
    Returns None for malformed requests (caller should return 416).
    """
    if not range_header.startswith("bytes="):
        return None
    range_val = range_header[6:]
    if "," in range_val:
        return None
    range_val = range_val.strip()
    if range_val == "":
        return None

    if range_val.startswith("-"):
        try:
            suffix = int(range_val)
            if suffix <= 0:
                return None
            start = max(0, file_size - suffix)
            end = file_size - 1
            return (start, end)
        except ValueError:
            return None

    parts = range_val.split("-", 1)
    if len(parts) != 2:
        return None

    start_str, end_str = parts
    if start_str == "":
        return None

    try:
        start = int(start_str)
    except ValueError:
        return None

    if start < 0:
        return None

    if end_str == "":
        end = file_size - 1
    else:
        try:
            end = int(end_str)
        except ValueError:
            return None
        if end >= file_size:
            end = file_size - 1

    if start > end:
        return None

    return (start, end)


@app.route("/media/<int:media_id>/play")
@login_required
def play_media(media_id: int) -> Any:
    """Stream a media file by ID for playback with range request support."""
    if not validate_media_id(media_id):
        flash("Invalid media ID", "error")
        return redirect(url_for("dashboard"))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM media WHERE id = ? AND user_id = ?",
        (media_id, session["user_id"]),
    )
    media = cursor.fetchone()
    conn.close()

    if not media:
        flash("Media not found or you do not have permission to view it", "error")
        return redirect(url_for("dashboard"))

    mime_type = get_mime_type(media["original_filename"])

    if is_s3_enabled():
        try:
            presigned_url = storage.get_url(
                media["storage_key"], media["original_filename"], inline=True
            )
            return redirect(presigned_url)
        except StorageError as e:
            flash(f"Failed to generate stream URL: {e}", "error")
            return redirect(url_for("dashboard"))
    else:
        file_path = media["storage_key"]
        file_size = media["file_size"]

        range_header = request.headers.get("Range", "")
        if range_header:
            try:
                byte_range = parse_range_header(range_header, file_size)
                if byte_range is None:
                    return Response(status=416)

                start, end = byte_range
                length = end - start + 1

                try:
                    f = open(file_path, "rb")
                except FileNotFoundError:
                    flash("File not found on disk", "error")
                    return redirect(url_for("dashboard"))
                except OSError as e:
                    flash(f"Failed to read file: {e}", "error")
                    return redirect(url_for("dashboard"))

                f.seek(start)

                def generate():
                    try:
                        remaining = length
                        while remaining > 0:
                            chunk_size = min(8192, remaining)
                            chunk = f.read(chunk_size)
                            if not chunk:
                                break
                            remaining -= len(chunk)
                            yield chunk
                    finally:
                        f.close()

                return Response(
                    generate(),
                    status=206,
                    mimetype=mime_type,
                    headers={
                        "Accept-Ranges": "bytes",
                        "Content-Range": f"bytes {start}-{end}/{file_size}",
                        "Content-Length": length,
                    },
                )
            except (ValueError, OSError):
                return Response(status=416)

        try:
            f = open(file_path, "rb")
        except FileNotFoundError:
            flash("File not found on disk", "error")
            return redirect(url_for("dashboard"))
        except OSError as e:
            flash(f"Failed to read file: {e}", "error")
            return redirect(url_for("dashboard"))

        def generate():
            try:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    yield chunk
            finally:
                f.close()

        return Response(
            generate(),
            mimetype=mime_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": file_size,
            },
        )


@app.route("/media/<int:media_id>/download")
@login_required
def download_media(media_id: int) -> Any:
    """Download a media file by ID."""
    if not validate_media_id(media_id):
        flash("Invalid media ID", "error")
        return redirect(url_for("dashboard"))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM media WHERE id = ? AND user_id = ?",
        (media_id, session["user_id"]),
    )
    media = cursor.fetchone()
    conn.close()

    if not media:
        flash("Media not found or you do not have permission to download it", "error")
        return redirect(url_for("dashboard"))

    filename_header = encode_filename_for_header(media["original_filename"])

    if is_s3_enabled():
        try:
            presigned_url = storage.get_url(
                media["storage_key"], media["original_filename"]
            )
            return redirect(presigned_url)
        except StorageError as e:
            flash(f"Failed to generate download URL: {e}", "error")
            return redirect(url_for("dashboard"))
    else:
        file_path = media["storage_key"]

        try:
            f = open(file_path, "rb")
        except FileNotFoundError:
            flash("File not found on disk", "error")
            return redirect(url_for("dashboard"))
        except OSError as e:
            flash(f"Failed to read file: {e}", "error")
            return redirect(url_for("dashboard"))

        def generate():
            try:
                while True:
                    chunk = f.read(8192)
                    if not chunk:
                        break
                    yield chunk
            finally:
                f.close()

        return Response(
            generate(),
            mimetype="application/octet-stream",
            headers={
                "Content-Disposition": f"attachment; {filename_header}",
                "Content-Length": media["file_size"],
            },
        )


@app.route("/media/<int:media_id>/delete", methods=["POST"])
@login_required
def delete_media(media_id: int) -> Any:
    """Delete a media file by ID."""
    if not validate_media_id(media_id):
        flash("Invalid media ID", "error")
        return redirect(url_for("dashboard"))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM media WHERE id = ? AND user_id = ?",
        (media_id, session["user_id"]),
    )
    media = cursor.fetchone()

    if not media:
        conn.close()
        flash("Media not found or you do not have permission to delete it", "error")
        return redirect(url_for("dashboard"))

    try:
        storage.delete(media["storage_key"])
        logger.info(f"File deleted: {media['original_filename']}")
    except StorageError as e:
        logger.error(f"Storage error during delete: {e}")
        flash(f"Failed to delete file: {e}", "error")
        return redirect(url_for("dashboard"))

    cursor.execute("DELETE FROM media WHERE id = ?", (media_id,))
    conn.commit()
    conn.close()

    flash("Media successfully deleted", "success")
    return redirect(url_for("dashboard"))


ensure_upload_folder()
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)

# WSGI application for Gunicorn
application = app
