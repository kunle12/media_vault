"""Authentication blueprint for email-based passwordless login."""

import random
import smtplib
import sqlite3
import string
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    request,
    session,
    url_for,
)

try:
    from authlib.integrations.flask_client import OAuth
except ImportError:
    OAuth = None

from config import Config
from config import is_google_oauth_enabled as check_google_oauth

auth_bp = Blueprint("auth", __name__)


def is_google_oauth_enabled():
    """Check if Google OAuth is configured."""
    return check_google_oauth()


def get_google_user_info(access_token):
    """Fetch user info from Google OAuth2."""
    try:
        resp = requests.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
    except requests.RequestException:
        pass
    return None


def is_oauth_state_valid():
    """Check if OAuth state exists and hasn't expired."""
    oauth_state = session.get("oauth_state")
    if not oauth_state:
        return False
    state_data = oauth_state.get("state")
    timestamp = oauth_state.get("timestamp", 0)
    if not state_data or not timestamp:
        return False
    if time.time() - timestamp > OAUTH_STATE_EXPIRY:
        session.pop("oauth_state", None)
        return False
    return True


CODE_EXPIRY_SECONDS = 300  # 5 minutes
MAX_RETRY_ATTEMPTS = 5
CODE_LENGTH = 6
RATE_LIMIT_SECONDS = 60  # Prevent spam
OAUTH_STATE_EXPIRY = 600  # 10 minutes


def load_allowed_emails():
    """Load allowed emails from ALLOWED_EMAILS environment variable."""
    emails_env = Config.ALLOWED_EMAILS()
    if emails_env:
        return {email.strip().lower() for email in emails_env.split() if email.strip()}
    return set()


def generate_code():
    """Generate a random verification code."""
    return "".join(
        random.choices(string.ascii_uppercase + string.digits, k=CODE_LENGTH)
    )


def get_cache():
    """Get the Flask cache instance."""
    cache_ext = current_app.extensions.get("cache")
    if cache_ext is None:
        raise RuntimeError("Cache not initialized")
    if isinstance(cache_ext, dict):
        if not cache_ext:
            raise RuntimeError("Cache not initialized")
        return cache_ext.get(list(cache_ext.keys())[0])
    return cache_ext


def store_code(email, code):
    """Store authentication code in cache with expiry."""
    cache = get_cache()
    key = f"auth_code:{email}"
    cache.set(
        key,
        {
            "code": code,
            "attempts": 0,
            "created_at": time.time(),
            "email": email,
        },
        timeout=CODE_EXPIRY_SECONDS,
    )


def get_code_data(email):
    """Retrieve stored code data from cache."""
    cache = get_cache()
    key = f"auth_code:{email}"
    return cache.get(key)


def delete_code(email):
    """Remove code from cache."""
    cache = get_cache()
    key = f"auth_code:{email}"
    cache.delete(key)


def is_code_expired(code_data):
    """Check if the code has expired."""
    if not code_data:
        return True
    elapsed = time.time() - code_data.get("created_at", 0)
    return elapsed > CODE_EXPIRY_SECONDS


def send_email(to_email, code):
    """Send verification email with the code."""
    email_provider = Config.EMAIL_PROVIDER()

    smtp_host = Config.SMTP_HOST()
    smtp_port = Config.SMTP_PORT()
    smtp_user = Config.SMTP_USER()
    smtp_password = Config.SMTP_PASSWORD()
    from_email = Config.FROM_EMAIL()

    if not smtp_user or not smtp_password:
        print(f"[DEBUG] Email would be sent to {to_email} with code: {code}")
        return True

    if email_provider == "aws_ses":
        aws_region = Config.AWS_REGION()
        smtp_host = smtp_host or f"email-smtp.{aws_region}.amazonaws.com"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Your MediaVault Verification Code"
        msg["From"] = from_email
        msg["To"] = to_email

        html_content = f"""
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 20px;">
            <div style="max-width: 400px; margin: 0 auto; background: #f8f9fa; border-radius: 12px; padding: 30px;">
                <h2 style="margin: 0 0 20px; color: #333;">Your Verification Code</h2>
                <p style="color: #666; margin-bottom: 20px;">Enter this code to access MediaVault:</p>
                <div style="font-size: 32px; letter-spacing: 8px; font-weight: bold; color: #2563eb; text-align: center; padding: 15px; background: white; border-radius: 8px;">
                    {code}
                </div>
                <p style="color: #999; font-size: 12px; margin-top: 20px;">This code expires in {CODE_EXPIRY_SECONDS // 60} minutes.</p>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            if smtp_port == 587:
                server.starttls()
                server.ehlo()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False


def get_db_connection():
    """Get SQLite database connection."""
    conn = sqlite3.connect(current_app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    return conn


def ensure_user_exists(email):
    """Create user if not exists, return user ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
    user = cursor.fetchone()

    if not user:
        cursor.execute(
            "INSERT INTO users (email, created_at) VALUES (?, ?)",
            (email, datetime.now().isoformat()),
        )
        conn.commit()
        cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()

    conn.close()
    return user["id"] if user else None


def check_rate_limit(email):
    """Check if email has exceeded rate limit for code requests."""
    cache = get_cache()
    key = f"rate_limit:{email}"
    last_request = cache.get(key)
    if last_request and (time.time() - last_request) < RATE_LIMIT_SECONDS:
        return False
    cache.set(key, time.time(), timeout=RATE_LIMIT_SECONDS)
    return True


@auth_bp.route("/auth/request-code", methods=["POST"])
def request_code():
    """Request a verification code to be sent to the user's email."""
    data = request.get_json()
    email = data.get("email", "").strip().lower()

    if not email or "@" not in email or "." not in email:
        return jsonify(
            {"success": False, "error": "Please enter a valid email address"}
        ), 400

    allowed_emails = load_allowed_emails()

    if email not in allowed_emails:
        return jsonify(
            {
                "success": False,
                "error": "If this email is authorized, you will receive a verification code. Please check your inbox.",
            }
        ), 200

    if not check_rate_limit(email):
        return jsonify(
            {"success": False, "error": "Please wait before requesting another code."}
        ), 429

    code = generate_code()
    store_code(email, code)

    if send_email(email, code):
        return jsonify({"success": True, "message": "Code sent"})
    else:
        return jsonify(
            {"success": False, "error": "Failed to send code. Please try again."}
        ), 500


@auth_bp.route("/auth/verify-code", methods=["POST"])
def verify_code():
    """Verify the code and create a session if valid."""
    data = request.get_json()
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip().upper()

    if not email or not code:
        return jsonify({"success": False, "error": "Email and code are required"}), 400

    code_data = get_code_data(email)

    if not code_data or is_code_expired(code_data):
        delete_code(email)
        return jsonify(
            {
                "success": False,
                "error": "Code expired or not found. Please request a new code.",
                "expired": True,
            }
        ), 400

    code_data["attempts"] += 1

    if code_data["attempts"] >= MAX_RETRY_ATTEMPTS:
        delete_code(email)
        return jsonify(
            {
                "success": False,
                "error": "Too many failed attempts. Please request a new code.",
                "locked": True,
            }
        ), 400

    if code != code_data["code"]:
        get_cache().set(
            f"auth_code:{email}",
            code_data,
            timeout=CODE_EXPIRY_SECONDS,
        )
        remaining = MAX_RETRY_ATTEMPTS - code_data["attempts"]
        return jsonify(
            {
                "success": False,
                "error": f"Incorrect code. {remaining} attempts remaining.",
            }
        ), 400

    delete_code(email)

    user_id = ensure_user_exists(email)
    session["user_id"] = user_id
    session["email"] = email
    session.permanent = True

    return jsonify({"success": True, "message": "Login successful"})


@auth_bp.route("/auth/logout", methods=["POST"])
def logout():
    """Clear the user session."""
    session.clear()
    return jsonify({"success": True})


@auth_bp.route("/auth/status", methods=["GET"])
def status():
    """Check if user is authenticated."""
    return jsonify(
        {
            "authenticated": "user_id" in session,
            "email": session.get("email", ""),
            "google_oauth_enabled": is_google_oauth_enabled(),
        }
    )


@auth_bp.route("/auth/google/login", methods=["GET"])
def google_login():
    """Initiate Google OAuth flow."""
    if not is_google_oauth_enabled():
        return redirect(url_for("trigger_auth"))

    from authlib.integrations.requests_client import OAuth2Session

    client_id = Config.GOOGLE_CLIENT_ID()
    redirect_uri = url_for("auth.google_callback", _external=True)

    client = OAuth2Session(client_id, scope="openid email profile")
    authorization_url, state = client.create_authorization_url(
        "https://accounts.google.com/o/oauth2/v2/auth",
        redirect_uri=redirect_uri,
    )
    session["oauth_state"] = {"state": state, "timestamp": time.time()}
    return redirect(authorization_url)


@auth_bp.route("/auth/google/callback", methods=["GET"])
def google_callback():
    """Handle Google OAuth callback."""
    if not is_google_oauth_enabled():
        return redirect(url_for("trigger_auth"))

    error = request.args.get("error")
    if error:
        session.pop("oauth_state", None)
        return redirect(url_for("trigger_auth"))

    code = request.args.get("code")
    state = request.args.get("state")

    if not code or not state:
        session.pop("oauth_state", None)
        return redirect(url_for("trigger_auth"))

    if not is_oauth_state_valid():
        session.pop("oauth_state", None)
        return redirect(url_for("trigger_auth"))

    if state != session.get("oauth_state", {}).get("state"):
        session.pop("oauth_state", None)
        return redirect(url_for("trigger_auth"))

    from authlib.integrations.requests_client import OAuth2Session

    client_id = Config.GOOGLE_CLIENT_ID()
    client_secret = Config.GOOGLE_CLIENT_SECRET()
    redirect_uri = url_for("auth.google_callback", _external=True)

    client = OAuth2Session(client_id, state=state)
    token = client.fetch_token(
        "https://oauth2.googleapis.com/token",
        code=code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )

    access_token = token.get("access_token")
    if not access_token:
        session.pop("oauth_state", None)
        return redirect(url_for("trigger_auth"))

    user_info = get_google_user_info(access_token)
    if not user_info:
        session.pop("oauth_state", None)
        return redirect(url_for("trigger_auth"))

    if not user_info.get("verified_email", False):
        session.pop("oauth_state", None)
        return redirect(url_for("trigger_auth"))

    email = user_info.get("email", "").lower()
    if not email:
        session.pop("oauth_state", None)
        return redirect(url_for("trigger_auth"))

    allowed_emails = load_allowed_emails()
    if allowed_emails and email not in allowed_emails:
        session.pop("oauth_state", None)
        return redirect(url_for("trigger_auth"))

    user_id = ensure_user_exists(email)
    session["user_id"] = user_id
    session["email"] = email
    session.permanent = True
    session.pop("oauth_state", None)

    return redirect(url_for("dashboard"))
