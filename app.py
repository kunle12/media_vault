# app.py
import os
import sqlite3
import uuid
from functools import wraps

from authlib.integrations.flask_client import OAuth
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_from_directory,
)
from flask_bcrypt import Bcrypt
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, FileField
from wtforms.validators import DataRequired, Email, Length, EqualTo
from werkzeug.utils import secure_filename

# App configuration
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", os.urandom(32).hex())
app.config["WTF_CSRF_ENABLED"] = True
app.config["WTF_CSRF_TIME_LIMIT"] = None
app.config["UPLOAD_FOLDER"] = os.environ.get("UPLOAD_FOLDER", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB max upload
app.config["ALLOWED_EXTENSIONS"] = {"mp4", "avi", "mov", "mkv", "wmv", "flv", "webm"}
app.config["DATABASE"] = os.environ.get("DATABASE", "videodb.sqlite")

# Google OAuth config
app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID", "")
app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET", "")

bcrypt = Bcrypt(app)
oauth = OAuth(app)

# Initialize Google OAuth
google = oauth.register(
    name="google",
    client_id=app.config["GOOGLE_CLIENT_ID"],
    client_secret=app.config["GOOGLE_CLIENT_SECRET"],
    access_token_url="https://accounts.google.com/o/oauth2/token",
    access_token_params=None,
    authorize_url="https://accounts.google.com/o/oauth2/auth",
    authorize_params=None,
    api_base_url="https://www.googleapis.com/oauth2/v1/",
    userinfo_endpoint="https://openidconnect.googleapis.com/v1/userinfo",
    client_kwargs={"scope": "openid email profile"},
)


# Database setup
def get_db_connection():
    conn = sqlite3.connect(app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with app.app_context():
        conn = get_db_connection()
        cursor = conn.cursor()

        # Create users table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            google_id TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # Create videos table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
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
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_google_id ON users(google_id)"
        )

        conn.commit()
        conn.close()


def ensure_upload_folder():
    upload_folder = app.config["UPLOAD_FOLDER"]
    if not os.path.exists(upload_folder):
        os.makedirs(upload_folder)


# Helper functions
def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


# Routes
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username")
        email = request.form.get("email")
        password = request.form.get("password")

        if not username or not email or not password:
            flash("All fields are required", "error")
            return redirect(url_for("register"))

        if len(username) < 3 or len(username) > 50:
            flash("Username must be between 3 and 50 characters", "error")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Password must be at least 6 characters", "error")
            return redirect(url_for("register"))

        if "@" not in email or "." not in email:
            flash("Please enter a valid email address", "error")
            return redirect(url_for("register"))

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM users WHERE username = ? OR email = ?", (username, email)
        )
        existing_user = cursor.fetchone()

        if existing_user:
            conn.close()
            flash("Username or email already exists", "error")
            return redirect(url_for("register"))

        # Hash the password and store the user
        password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (username, email, password_hash),
        )
        conn.commit()

        # Get the user ID for the session
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()

        session["user_id"] = user["id"]
        session["username"] = username

        flash("Registration successful!", "success")
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()

        if (
            user
            and user["password_hash"]
            and bcrypt.check_password_hash(user["password_hash"], password)
        ):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            flash("Login successful!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password", "error")

    return render_template("login.html")


@app.route("/login/google")
def google_login():
    redirect_uri = url_for("google_auth", _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route("/login/google/callback")
def google_auth():
    token = google.authorize_access_token()
    resp = google.get("userinfo")
    user_info = resp.json()

    # Check if user exists with this Google ID
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE google_id = ?", (user_info["id"],))
    user = cursor.fetchone()

    if not user:
        # Check if email exists but not linked to Google
        cursor.execute("SELECT * FROM users WHERE email = ?", (user_info["email"],))
        user = cursor.fetchone()

        if user:
            # Update the existing account with Google ID
            cursor.execute(
                "UPDATE users SET google_id = ? WHERE id = ?",
                (user_info["id"], user["id"]),
            )
        else:
            # Create a new user
            cursor.execute(
                "INSERT INTO users (username, email, google_id) VALUES (?, ?, ?)",
                (user_info["email"].split("@")[0], user_info["email"], user_info["id"]),
            )
            conn.commit()
            cursor.execute(
                "SELECT * FROM users WHERE google_id = ?", (user_info["id"],)
            )
            user = cursor.fetchone()

    conn.commit()
    conn.close()

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    flash("Login with Google successful!", "success")
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
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
    if request.method == "POST":
        if "video" not in request.files:
            flash("No file part", "error")
            return redirect(request.url)

        file = request.files["video"]

        if file.filename == "":
            flash("No selected file", "error")
            return redirect(request.url)

        if file and allowed_file(file.filename):
            original_filename = secure_filename(file.filename or "")
            if not original_filename:
                flash("Invalid filename", "error")
                return redirect(request.url)
            # Generate a unique filename with UUID to prevent conflicts
            unique_filename = f"{uuid.uuid4()}_{original_filename}"
            file_path = os.path.join(app.config["UPLOAD_FOLDER"], unique_filename)
            file.save(file_path)

            # Save file information to database
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO videos (filename, original_filename, file_path, file_size, user_id) VALUES (?, ?, ?, ?, ?)",
                (
                    unique_filename,
                    original_filename,
                    file_path,
                    os.path.getsize(file_path),
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

    return send_from_directory(
        os.path.dirname(video["file_path"]),
        os.path.basename(video["file_path"]),
        as_attachment=True,
        download_name=video["original_filename"],
    )


@app.route("/video/<int:video_id>/delete", methods=["POST"])
@login_required
def delete_video(video_id):
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

    # Delete the file from storage
    try:
        os.remove(video["file_path"])
    except OSError:
        pass  # File might not exist

    # Delete from database
    cursor.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    conn.commit()
    conn.close()

    flash("Video successfully deleted", "success")
    return redirect(url_for("dashboard"))


if __name__ == "__main__":
    ensure_upload_folder()
    init_db()
    app.run(host="0.0.0.0", port=5050, debug=False)
