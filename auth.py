import os
import random
import smtplib
import sqlite3
import string
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import (
    Blueprint,
    current_app,
    jsonify,
    request,
    session,
)

auth_bp = Blueprint("auth", __name__)

CODE_EXPIRY_SECONDS = 300  # 5 minutes
MAX_RETRY_ATTEMPTS = 5
CODE_LENGTH = 6
RATE_LIMIT_SECONDS = 60  # Prevent spam


def load_allowed_emails():
    emails_file = os.environ.get("ALLOWED_EMAILS_FILE", "allowed_emails.txt")
    if os.path.exists(emails_file):
        with open(emails_file, "r") as f:
            return {line.strip().lower() for line in f if line.strip()}
    return set()


def generate_code():
    return "".join(
        random.choices(string.ascii_uppercase + string.digits, k=CODE_LENGTH)
    )


def get_cache():
    return current_app.extensions["cache"][
        list(current_app.extensions["cache"].keys())[0]
    ]


def store_code(email, code):
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
    cache = get_cache()
    key = f"auth_code:{email}"
    return cache.get(key)


def delete_code(email):
    cache = get_cache()
    key = f"auth_code:{email}"
    cache.delete(key)


def is_code_expired(code_data):
    if not code_data:
        return True
    elapsed = time.time() - code_data.get("created_at", 0)
    return elapsed > CODE_EXPIRY_SECONDS


def send_email(to_email, code):
    email_provider = os.environ.get("EMAIL_PROVIDER", "generic").lower()

    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    from_email = os.environ.get("FROM_EMAIL", smtp_user)

    if not smtp_user or not smtp_password:
        print(f"[DEBUG] Email would be sent to {to_email} with code: {code}")
        return True

    if email_provider == "aws_ses":
        smtp_host = (
            smtp_host
            or f"email-smtp.{os.environ.get('AWS_REGION', 'us-east-1')}.amazonaws.com"
        )
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Your VideoVault Verification Code"
        msg["From"] = from_email
        msg["To"] = to_email

        html_content = f"""
        <html>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 20px;">
            <div style="max-width: 400px; margin: 0 auto; background: #f8f9fa; border-radius: 12px; padding: 30px;">
                <h2 style="margin: 0 0 20px; color: #333;">Your Verification Code</h2>
                <p style="color: #666; margin-bottom: 20px;">Enter this code to access VideoVault:</p>
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
    conn = sqlite3.connect(current_app.config["DATABASE"])
    conn.row_factory = sqlite3.Row
    return conn


def ensure_user_exists(email):
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
    cache = get_cache()
    key = f"rate_limit:{email}"
    last_request = cache.get(key)
    if last_request and (time.time() - last_request) < RATE_LIMIT_SECONDS:
        return False
    cache.set(key, time.time(), timeout=RATE_LIMIT_SECONDS)
    return True


@auth_bp.route("/auth/request-code", methods=["POST"])
def request_code():
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
    session.clear()
    return jsonify({"success": True})


@auth_bp.route("/auth/status", methods=["GET"])
def status():
    if "user_id" in session:
        return jsonify({"authenticated": True, "email": session.get("email", "")})
    return jsonify({"authenticated": False})
