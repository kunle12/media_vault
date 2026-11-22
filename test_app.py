"""Tests for the Media Vault proxy-identity application."""

import io
import sqlite3
import tempfile
from pathlib import Path

from conftest import TEST_EMAIL


def headers(email: str = TEST_EMAIL, groups: str = "users") -> dict:
    return {"X-Auth-User": email, "X-Auth-Groups": groups}


def seed_user(app, email: str) -> int:
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


def seed_media(app, user_id: int, path: Path, name: str = "clip.mp4") -> int:
    path.write_bytes(b"0123456789abcdef")
    conn = sqlite3.connect(app.config["DATABASE"])
    try:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO media (filename, original_filename, storage_key, file_size, user_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (name, name, str(path), path.stat().st_size, user_id),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def test_index_redirects_to_dashboard(client):
    response = client.get("/", headers=headers())
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_missing_identity_is_refused(client):
    response = client.get("/dashboard")
    assert response.status_code == 401
    assert b"Identity required" in response.data


def test_untrusted_remote_is_refused(client):
    response = client.get(
        "/dashboard",
        headers=headers(),
        environ_overrides={"REMOTE_ADDR": "10.0.0.5"},
    )
    assert response.status_code == 403
    assert b"Untrusted origin" in response.data


def test_identity_provisions_local_user(app, client):
    with app.app_context():
        response = client.get("/dashboard", headers=headers("new@example.com"))
        assert response.status_code == 200
        assert b"No media in the vault yet" in response.data

        conn = sqlite3.connect(app.config["DATABASE"])
        try:
            row = conn.execute(
                "SELECT id FROM users WHERE email = ?", ("new@example.com",)
            ).fetchone()
        finally:
            conn.close()
        assert row is not None


def test_existing_user_keeps_their_id(app, client):
    user_id = seed_user(app, TEST_EMAIL)
    response = client.get("/dashboard", headers=headers())
    assert response.status_code == 200

    conn = sqlite3.connect(app.config["DATABASE"])
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == user_id


def test_dashboard_authenticated(app, client, tmp_path):
    user_id = seed_user(app, TEST_EMAIL)
    seed_media(app, user_id, tmp_path / "clip.mp4")
    response = client.get("/dashboard", headers=headers())
    assert response.status_code == 200
    assert b"Your vault" in response.data
    assert b"clip.mp4" in response.data


def test_dashboard_sort_options(client):
    seed_user(client.application, TEST_EMAIL)
    for sort in (
        "newest",
        "oldest",
        "name_asc",
        "name_desc",
        "size_desc",
        "size_asc",
        "type",
    ):
        response = client.get(f"/dashboard?sort={sort}", headers=headers())
        assert response.status_code == 200
    response = client.get("/dashboard?sort=invalid", headers=headers())
    assert response.status_code == 200


def test_upload_requires_identity(client):
    response = client.get("/upload")
    assert response.status_code == 401


def test_upload_get_authenticated(client):
    response = client.get("/upload", headers=headers())
    assert response.status_code == 200
    assert b"Add to the vault" in response.data


def test_upload_file(client):
    response = client.post(
        "/upload",
        headers=headers(),
        data={"files": (io.BytesIO(b"fake audio content"), "sample.wav")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]

    conn = sqlite3.connect(client.application.config["DATABASE"])
    try:
        row = conn.execute("SELECT original_filename, file_size FROM media").fetchone()
    finally:
        conn.close()
    assert row[0] == "sample.wav"
    assert row[1] > 0


def test_upload_rejects_invalid_type(client):
    response = client.post(
        "/upload",
        headers=headers(),
        data={"files": (io.BytesIO(b"nope"), "sample.exe")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    conn = sqlite3.connect(client.application.config["DATABASE"])
    try:
        count = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
    finally:
        conn.close()
    assert count == 0


def test_view_media(app, client, tmp_path):
    user_id = seed_user(app, TEST_EMAIL)
    media_id = seed_media(app, user_id, tmp_path / "clip.mp4")
    response = client.get(f"/media/{media_id}", headers=headers())
    assert response.status_code == 200
    assert b"clip.mp4" in response.data
    assert b"File details" in response.data


def test_media_is_scoped_to_identity(app, client, tmp_path):
    seed_user(app, TEST_EMAIL)
    other_id = seed_user(app, "other@example.com")
    media_id = seed_media(app, other_id, tmp_path / "private.mp4")
    response = client.get(f"/media/{media_id}", headers=headers())
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_stream_supports_range_requests(app, client, tmp_path):
    user_id = seed_user(app, TEST_EMAIL)
    media_id = seed_media(app, user_id, tmp_path / "clip.mp4")
    response = client.get(
        f"/media/{media_id}/play",
        headers={**headers(), "Range": "bytes=0-3"},
    )
    assert response.status_code == 206
    assert response.data == b"0123"
    assert response.headers["Content-Range"] == "bytes 0-3/16"


def test_download_sets_attachment(app, client, tmp_path):
    user_id = seed_user(app, TEST_EMAIL)
    media_id = seed_media(app, user_id, tmp_path / "clip.mp4")
    response = client.get(f"/media/{media_id}/download", headers=headers())
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"]


def test_delete_removes_file_and_row(app, client, tmp_path):
    user_id = seed_user(app, TEST_EMAIL)
    path = tmp_path / "clip.mp4"
    media_id = seed_media(app, user_id, path)
    response = client.post(f"/media/{media_id}/delete", headers=headers())
    assert response.status_code == 302
    assert not path.exists()
    conn = sqlite3.connect(app.config["DATABASE"])
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM media WHERE id = ?", (media_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 0


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "ok"
    assert data["storage"] == "ok"


def test_stylesheet_and_themed_404(client):
    response = client.get("/static/mediavault.css")
    assert response.status_code == 200
    assert b"--peach" in response.data

    response = client.get("/dashboard/does-not-exist", headers=headers())
    assert response.status_code == 404
    assert b"Not in the vault" in response.data


def test_local_storage_save():
    from storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(tmpdir)
        fake = type(
            "F", (), {"save": lambda self, path: Path(path).write_bytes(b"x")}
        )()
        key = storage.save(fake, "test.txt")
        assert key.endswith("test.txt")


def test_local_storage_delete():
    from storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(tmpdir)
        path = Path(tmpdir) / "test.txt"
        path.write_text("test")
        assert storage.delete(str(path)) is True
        assert not path.exists()


def test_local_storage_get_file():
    from storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(tmpdir)
        path = Path(tmpdir) / "test.txt"
        path.write_bytes(b"test content")
        assert storage.get_file(str(path)) == b"test content"


def test_allowed_file_extensions():
    from app import allowed_file

    for name in (
        "video.mp4",
        "video.avi",
        "video.mov",
        "audio.mp3",
        "audio.wav",
        "audio.ogg",
        "image.png",
        "image.jpg",
        "image.jpeg",
        "image.gif",
        "image.webp",
        "image.bmp",
        "image.heic",
    ):
        assert allowed_file(name) is True
    for name in ("file.txt", "file", "file.exe"):
        assert allowed_file(name) is False


def test_human_size_filter():
    from app import human_size

    assert human_size(0) == "0 B"
    assert human_size(1024) == "1.0 KB"
    assert human_size(1024 * 1024 * 3) == "3.0 MB"
