"""MediaVault - Flask application for managing video and audio files."""

import os
import sqlite3
import uuid
from functools import wraps

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

from auth import auth_bp
from storage import get_storage_backend, is_s3_enabled

# App configuration
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", os.urandom(32).hex())
app.config["WTF_CSRF_ENABLED"] = True
app.config["WTF_CSRF_TIME_LIMIT"] = None
app.config["UPLOAD_FOLDER"] = os.environ.get("UPLOAD_FOLDER", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB max upload
app.config["ALLOWED_EXTENSIONS"] = {
    "mp4",
    "avi",
    "mov",
    "mkv",
    "wmv",
    "flv",
    "webm",
    "mp3",
    "wav",
    "ogg",
}
app.config["DATABASE"] = os.environ.get("DATABASE", "videodb.sqlite")

# Cache configuration
cache_type = os.environ.get("CACHE_TYPE", "simple")
if cache_type == "redis":
    app.config["CACHE_REDIS_URL"] = os.environ.get(
        "CACHE_REDIS_URL", "redis://localhost:6379/0"
    )
app.config["CACHE_TYPE"] = cache_type
app.config["CACHE_DEFAULT_TIMEOUT"] = 300

cache = Cache(app)

app.register_blueprint(auth_bp)

# Initialize storage backend
storage = get_storage_backend()


# Database setup
def get_db_connection():
    """Get SQLite database connection."""
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
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
        CREATE TABLE IF NOT EXISTS videos (
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

        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_user_id ON videos(user_id)"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")

        conn.commit()
        conn.close()


def ensure_upload_folder():
    """Create upload folder if it doesn't exist."""
    if not is_s3_enabled():
        upload_folder = app.config["UPLOAD_FOLDER"]
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)


# Helper functions
def allowed_file(filename):
    """Check if filename has an allowed extension."""
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


def login_required(f):
    """Decorator to require authentication for routes."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            return render_template("auth_trigger.html")
        return f(*args, **kwargs)

    return decorated_function


# Routes
@app.route("/")
def index():
    """Home page - redirect to dashboard if authenticated."""
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/trigger-auth")
def trigger_auth():
    """Render the auth trigger page."""
    return render_template("auth_trigger.html")


@app.route("/dashboard")
@login_required
def dashboard():
    """User dashboard showing their uploaded videos."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM videos WHERE user_id = ? ORDER BY uploaded_at DESC",
        (session["user_id"],),
    )
    videos = cursor.fetchall()
    conn.close()
    return render_template("dashboard.html", videos=videos)


@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    """Handle file upload - GET shows form, POST processes upload."""
    if request.method == "POST":
        if "video" not in request.files:
            flash("No file part", "error")
            return redirect(request.url)

        file = request.files["video"]

        if file.filename == "":
            flash("No selected file", "error")
            return redirect(request.url)

        if file and allowed_file(file.filename):
            original_filename = file.filename
            if not original_filename:
                flash("Invalid filename", "error")
                return redirect(request.url)
            unique_filename = f"{uuid.uuid4()}_{original_filename}"

            file_size = 0
            if is_s3_enabled():
                storage_key = storage.save(file, unique_filename)
                file_obj = storage.get_file(storage_key)
                file_size = len(file_obj)
            else:
                storage_key = storage.save(file, unique_filename)
                file_size = os.path.getsize(storage_key)

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO videos (filename, original_filename, storage_key, file_size, user_id) VALUES (?, ?, ?, ?, ?)",
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

            flash("Video successfully uploaded!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("File type not allowed", "error")
            return redirect(request.url)

    return render_template("upload.html")


@app.route("/video/<int:video_id>")
@login_required
def view_video(video_id):
    """Display a single video by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM videos WHERE id = ? AND user_id = ?",
        (video_id, session["user_id"]),
    )
    video = cursor.fetchone()
    conn.close()

    if not video:
        flash("Video not found or you do not have permission to view it", "error")
        return redirect(url_for("dashboard"))

    return render_template("video.html", video=video)


@app.route("/video/<int:video_id>/download")
@login_required
def download_video(video_id):
    """Download a video file by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM videos WHERE id = ? AND user_id = ?",
        (video_id, session["user_id"]),
    )
    video = cursor.fetchone()
    conn.close()

    if not video:
        flash("Video not found or you do not have permission to download it", "error")
        return redirect(url_for("dashboard"))

    if is_s3_enabled():
        presigned_url = storage.get_url(
            video["storage_key"], video["original_filename"]
        )
        if presigned_url:
            return redirect(presigned_url)
        flash("Failed to generate download URL", "error")
        return redirect(url_for("dashboard"))
    else:
        return Response(
            storage.get_file(video["storage_key"]),
            mimetype="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{video["original_filename"]}"'
            },
        )


@app.route("/video/<int:video_id>/delete", methods=["POST"])
@login_required
def delete_video(video_id):
    """Delete a video by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM videos WHERE id = ? AND user_id = ?",
        (video_id, session["user_id"]),
    )
    video = cursor.fetchone()

    if not video:
        conn.close()
        flash("Video not found or you do not have permission to delete it", "error")
        return redirect(url_for("dashboard"))

    storage.delete(video["storage_key"])

    cursor.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    conn.commit()
    conn.close()

    flash("Video successfully deleted", "success")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    ensure_upload_folder()
    init_db()
    app.run(host="0.0.0.0", port=5050, debug=False)
