"""Test fixtures for Media Vault."""

import os
import sqlite3
import tempfile

import pytest

# Configuration is cached at import time, so point it at a writable temp root
# before ``app`` is imported. Individual tests get a fresh SQLite database.
_TEST_ROOT = tempfile.mkdtemp(prefix="mediavault-tests-")
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["UPLOAD_FOLDER"] = os.path.join(_TEST_ROOT, "uploads")
os.environ["DATABASE"] = os.path.join(_TEST_ROOT, "global.db")
os.environ.pop("S3_BUCKET", None)
os.environ.pop("S3_ENDPOINT", None)
os.environ.pop("AZURE_STORAGE_ACCOUNT", None)
os.environ.pop("AZURE_CONNECTION_STRING", None)

TEST_EMAIL = "user@example.com"
IDENTITY = {"X-Auth-User": TEST_EMAIL, "X-Auth-Groups": "users"}


@pytest.fixture(scope="function")
def app(tmp_path):
    """Create a test application with a fresh database."""
    from app import app as flask_app
    from app import init_db

    db_path = str(tmp_path / "test.db")
    flask_app.config["DATABASE"] = db_path
    flask_app.config["TESTING"] = True

    with flask_app.app_context():
        init_db()

    yield flask_app


@pytest.fixture(scope="function")
def client(app):
    """Test client that arrives from the trusted loopback proxy."""
    test_client = app.test_client()
    test_client.environ_base["REMOTE_ADDR"] = "127.0.0.1"
    return test_client


@pytest.fixture(scope="function")
def authenticated_client(client):
    """Test client carrying the guard's identity header."""
    return client


def auth_headers(email: str = TEST_EMAIL, groups: str = "users") -> dict:
    """Headers nginx would set after a successful guard auth_request."""
    return {"X-Auth-User": email, "X-Auth-Groups": groups}


def seed_user(app, email: str = TEST_EMAIL) -> int:
    """Insert a local user row and return its id."""
    conn = sqlite3.connect(app.config["DATABASE"])
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (email, created_at) VALUES (?, datetime('now'))",
            (email,),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()
