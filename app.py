"""MediaVault - Flask application for managing video and audio files."""

import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from functools import wraps
from typing import Any

from flask import (
    Flask,
    Response,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from loguru import logger

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

application_root = Config.APPLICATION_ROOT()
_static_prefix = (application_root.rstrip("/") or "") + "/static"

app = Flask(__name__, static_url_path=_static_prefix)
app.config["SECRET_KEY"] = Config.SECRET_KEY()
app.config["UPLOAD_FOLDER"] = Config.UPLOAD_FOLDER()
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_LENGTH()
app.config["ALLOWED_EXTENSIONS"] = Config.ALLOWED_EXTENSIONS
app.config["DATABASE"] = Config.DATABASE()
app.config["APPLICATION_ROOT"] = application_root
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
server_name = Config.SERVER_NAME()
if server_name:
    app.config["SERVER_NAME"] = server_name

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


def current_user_id() -> int:
    """Return the guard identity's local user id, or abort."""
    uid = getattr(g, "user_id", None)
    if uid is None:
        raise RuntimeError("identity middleware did not run")
    return int(uid)


@app.before_request
def load_identity() -> Any:
    """Trust the guard's identity header from the local reverse proxy only.

    The app has no login of its own. nginx performs the guard auth_request and
    overwrites ``X-Auth-User``; a request that reaches Flask without it (for
    example a direct loopback call) is refused instead of falling back to a
    local login.
    """
    if request.endpoint in ("static", "healthz"):
        return None
    email = request.headers.get(Config.IDENTITY_HEADER, "").strip().lower()
    if request.remote_addr not in Config.TRUSTED_PROXY_ADDRS:
        return render_template(
            "error.html",
            code=403,
            title="Untrusted origin",
            message="Media Vault only accepts requests through the workspace gate.",
        ), 403
    if (
        not email
        or len(email) > 320
        or email.count("@") != 1
        or any(ch.isspace() for ch in email)
    ):
        return render_template(
            "error.html",
            code=401,
            title="Identity required",
            message="Open Media Vault from the workspace so the guard can identify you.",
        ), 401
    g.user_id = ensure_user_exists(email)
    g.email = email
    g.groups = [
        part.strip()
        for part in request.headers.get(Config.GROUPS_HEADER, "").split(",")
        if part.strip()
    ]
    return None


@app.after_request
def add_security_headers(response: Response) -> Response:
    """Add Content-Security-Policy and other security headers."""
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "media-src 'self'; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
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


def ensure_user_exists(email: str) -> int:
    """Map a verified guard identity to the local users row.

    Existing users keep their id, so media ownership survives the migration
    from the old email-code login. The unique index makes this safe across
    concurrent workers.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        if row:
            return int(row["id"])
        cursor.execute(
            "INSERT INTO users (email, created_at) VALUES (?, ?) "
            "ON CONFLICT(email) DO NOTHING",
            (email, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("could not provision local user")
        return int(row["id"])
    finally:
        conn.close()


# Helper functions
def allowed_file(filename: str) -> bool:
    """Check if filename has an allowed extension."""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


@app.template_filter("filesize")
def human_size(num: int | float | None) -> str:
    """Render a byte count as a compact human value."""
    if not num:
        return "0 B"
    size = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def login_required(f):
    """Decorator documenting that a route needs the guard identity.

    The actual refusal happens in ``load_identity`` before the view runs; this
    keeps the intent visible at each route without duplicating error pages.
    """

    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        current_user_id()
        return f(*args, **kwargs)

    return decorated_function


# Routes
@app.route("/")
def index() -> Any:
    """The vault root always opens the library."""
    return redirect(url_for("dashboard"))


@app.route("/healthz")
def healthz() -> Any:
    """Liveness and storage check for the operator."""
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except sqlite3.Error as exc:
        logger.error(f"healthz database check failed: {exc}")
        return jsonify({"status": "error", "db": "down"}), 503
    upload_folder = app.config["UPLOAD_FOLDER"]
    if not is_s3_enabled() and not os.path.isdir(upload_folder):
        return jsonify({"status": "error", "storage": "missing"}), 503
    return jsonify({"status": "ok", "db": "ok", "storage": "ok"})


@app.route("/dashboard")
@login_required
def dashboard() -> Any:
    """User dashboard showing their uploaded media."""
    sort = request.args.get("sort", "newest")

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

    page = request.args.get("page", 1, type=int)
    per_page = Config.ITEMS_PER_PAGE()
    offset = (page - 1) * per_page
    uid = current_user_id()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) AS count, COALESCE(SUM(file_size), 0) AS total_bytes "
        "FROM media WHERE user_id = ?",
        (uid,),
    )
    totals = cursor.fetchone()
    total_items = int(totals["count"])
    total_bytes = int(totals["total_bytes"])
    total_pages = max(1, (total_items + per_page - 1) // per_page)

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
        offset = (page - 1) * per_page

    cursor.execute(
        "SELECT * FROM media WHERE user_id = ? ORDER BY "
        + order_by
        + " LIMIT ? OFFSET ?",
        (uid, per_page, offset),
    )
    media = cursor.fetchall()
    conn.close()

    disk_used = disk_total = disk_percent = None
    if not is_s3_enabled():
        try:
            usage = shutil.disk_usage(app.config["UPLOAD_FOLDER"])
            disk_used, disk_total = usage.used, usage.total
            disk_percent = round(usage.used / usage.total * 100) if usage.total else 0
        except OSError:
            pass

    return render_template(
        "dashboard.html",
        media=media,
        current_sort=sort,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_items=total_items,
        total_bytes=total_bytes,
        disk_used=disk_used,
        disk_total=disk_total,
        disk_percent=disk_percent,
        storage_path="S3" if is_s3_enabled() else app.config["UPLOAD_FOLDER"],
    )


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
                            current_user_id(),
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
    disk_free = None
    if not is_s3_enabled():
        try:
            disk_free = shutil.disk_usage(app.config["UPLOAD_FOLDER"]).free
        except OSError:
            pass
    return render_template(
        "upload.html",
        max_size_mb=max_size_mb,
        disk_free=disk_free,
        storage_path=app.config["UPLOAD_FOLDER"],
    )


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
        (media_id, current_user_id()),
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
        (media_id, current_user_id()),
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
        (media_id, current_user_id()),
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
        (media_id, current_user_id()),
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


@app.errorhandler(404)
def not_found(_error: Any) -> tuple[str, int]:
    """Render a themed not-found page instead of Flask's default."""
    return render_template(
        "error.html",
        code=404,
        title="Not in the vault",
        message="That file or route does not exist in this deck.",
    ), 404


@app.errorhandler(413)
def too_large(_error: Any) -> tuple[str, int]:
    """Render a themed upload-too-large page."""
    limit = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    return render_template(
        "error.html",
        code=413,
        title="Upload too large",
        message=f"Each upload is limited to {limit} MB.",
    ), 413


@app.errorhandler(500)
def server_error(_error: Any) -> tuple[str, int]:
    """Render a themed server-error page."""
    return render_template(
        "error.html",
        code=500,
        title="Vault offline",
        message="The vault hit an unexpected error. Try again in a moment.",
    ), 500


ensure_upload_folder()
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=False)

# WSGI application for Gunicorn
application = app
