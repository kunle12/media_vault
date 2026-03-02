"""Test fixtures for MediaVault application."""

import os
import sqlite3

import pytest

os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ALLOWED_EMAILS"] = "user@example.com"
os.environ.pop("S3_BUCKET", None)
os.environ.pop("S3_ENDPOINT", None)


@pytest.fixture(scope="function")
def tmp_upload_folder(tmp_path):
    """Create temporary upload folder."""
    folder = tmp_path / "uploads"
    folder.mkdir()
    os.environ["UPLOAD_FOLDER"] = str(folder)
    return folder


@pytest.fixture(scope="function")
def app(tmp_upload_folder, tmp_path):
    """Create test Flask application."""
    from app import app as flask_app

    db_path = str(tmp_path / "test.db")
    test_conn = sqlite3.connect(db_path)
    test_conn.row_factory = sqlite3.Row

    cursor = test_conn.cursor()
    cursor.execute("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE media (
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

    cursor.execute("INSERT INTO users (email) VALUES (?)", ("user@example.com",))
    test_conn.commit()

    flask_app.config["DATABASE"] = db_path
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False

    yield flask_app

    test_conn.close()


@pytest.fixture(scope="function")
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture(scope="function")
def authenticated_client(client):
    """Create authenticated test client."""
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["email"] = "user@example.com"
    return client
