"""Tests for MediaVault application."""

import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ALLOWED_EMAILS"] = "user@example.com"
os.environ.pop("S3_BUCKET", None)
os.environ.pop("S3_ENDPOINT", None)


def test_index_unauthenticated(client):
    """Test index page shows correctly when not authenticated."""
    response = client.get("/")
    assert response.status_code == 200
    assert b"MediaVault" in response.data


def test_index_authenticated(authenticated_client):
    """Test index page redirects when authenticated."""
    response = authenticated_client.get("/")
    assert response.status_code == 302


def test_request_code_invalid_email(client):
    """Test request code with invalid email."""
    response = client.post(
        "/auth/request-code",
        json={"email": "invalid"},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False


def test_request_code_unauthorized(client):
    """Test request code with unauthorized email."""
    response = client.post(
        "/auth/request-code",
        json={"email": "notallowed@example.com"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is False


def test_request_code_valid(client):
    """Test request code with valid email."""
    with patch("auth.send_email", return_value=True):
        response = client.post(
            "/auth/request-code",
            json={"email": "user@example.com"},
        )
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True


def test_verify_code_no_code(client):
    """Test verify code when no code exists."""
    response = client.post(
        "/auth/verify-code",
        json={"email": "user@example.com", "code": "ABC123"},
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["success"] is False


def test_logout(authenticated_client):
    """Test logout clears session."""
    response = authenticated_client.post("/auth/logout")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True


def test_status_authenticated(authenticated_client):
    """Test auth status when authenticated."""
    response = authenticated_client.get("/auth/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["authenticated"] is True
    assert data["email"] == "user@example.com"


def test_status_unauthenticated(client):
    """Test auth status when not authenticated."""
    response = client.get("/auth/status")
    assert response.status_code == 200
    data = response.get_json()
    assert data["authenticated"] is False


def test_dashboard_requires_auth(client):
    """Test dashboard requires authentication."""
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert b"Sign In" in response.data or b"Login" in response.data


def test_dashboard_authenticated(authenticated_client):
    """Test dashboard shows media for authenticated user."""
    response = authenticated_client.get("/dashboard")
    assert response.status_code == 200
    assert b"Dashboard" in response.data


def test_dashboard_sort_options(authenticated_client):
    """Test dashboard sorting with various sort options."""
    sort_options = [
        "newest",
        "oldest",
        "name_asc",
        "name_desc",
        "size_desc",
        "size_asc",
        "type",
    ]
    for sort in sort_options:
        response = authenticated_client.get(f"/dashboard?sort={sort}")
        assert response.status_code == 200


def test_dashboard_sort_invalid_fallback(authenticated_client):
    """Test dashboard falls back to default for invalid sort."""
    response = authenticated_client.get("/dashboard?sort=invalid")
    assert response.status_code == 200
    assert b"Dashboard" in response.data


def test_upload_requires_auth(client):
    """Test upload requires authentication."""
    response = client.get("/upload")
    assert response.status_code == 200
    assert b"Sign In" in response.data or b"Login" in response.data


def test_upload_get_authenticated(authenticated_client):
    """Test upload page loads for authenticated user."""
    response = authenticated_client.get("/upload")
    assert response.status_code == 200


def test_upload_file(authenticated_client):
    """Test uploading a file."""
    with open("audiosample1.wav", "rb") as f:
        response = authenticated_client.post(
            "/upload",
            data={"video": f},
            content_type="multipart/form-data",
        )

    assert response.status_code == 302
    assert "/dashboard" in response.location


def test_upload_invalid_file(authenticated_client):
    """Test uploading invalid file type."""
    upload_folder = tempfile.mkdtemp()
    os.environ["UPLOAD_FOLDER"] = upload_folder

    try:
        test_file = tempfile.NamedTemporaryFile(suffix=".exe", delete=False)
        test_file.write(b"fake content")
        test_file.close()

        with open(test_file.name, "rb") as f:
            response = authenticated_client.post(
                "/upload",
                data={"video": f},
                content_type="multipart/form-data",
            )

        assert response.status_code == 302
        os.unlink(test_file.name)
    finally:
        shutil.rmtree(upload_folder, ignore_errors=True)


def test_view_media_requires_auth(client):
    """Test view media requires authentication."""
    response = client.get("/media/1")
    assert response.status_code == 200
    assert b"Sign In" in response.data or b"Login" in response.data


def test_download_requires_auth(client):
    """Test download requires authentication."""
    response = client.get("/media/1/download")
    assert response.status_code == 200
    assert b"Sign In" in response.data or b"Login" in response.data


def test_delete_requires_auth(client):
    """Test delete requires authentication."""
    response = client.post("/media/1/delete")
    assert response.status_code == 200
    assert b"Sign In" in response.data or b"Login" in response.data


def test_local_storage_save():
    """Test local storage save."""
    from storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(tmpdir)
        mock_file = MagicMock()
        mock_file.save = MagicMock()

        key = storage.save(mock_file, "test.txt")
        assert key.endswith("test.txt")
        mock_file.save.assert_called_once()


def test_local_storage_delete():
    """Test local storage delete."""
    from storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(tmpdir)
        test_file = os.path.join(tmpdir, "test.txt")
        with open(test_file, "w") as f:
            f.write("test")

        result = storage.delete(test_file)
        assert result is True
        assert not os.path.exists(test_file)


def test_local_storage_get_file():
    """Test local storage get_file."""
    from storage import LocalStorage

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = LocalStorage(tmpdir)
        test_file = os.path.join(tmpdir, "test.txt")
        content = b"test content"
        with open(test_file, "wb") as f:
            f.write(content)

        result = storage.get_file(test_file)
        assert result == content


def test_allowed_file_extensions():
    """Test allowed file extensions."""
    from app import allowed_file

    assert allowed_file("video.mp4") is True
    assert allowed_file("video.avi") is True
    assert allowed_file("video.mov") is True
    assert allowed_file("audio.mp3") is True
    assert allowed_file("audio.wav") is True
    assert allowed_file("audio.ogg") is True
    assert allowed_file("image.png") is True
    assert allowed_file("image.jpg") is True
    assert allowed_file("image.jpeg") is True
    assert allowed_file("image.gif") is True
    assert allowed_file("image.webp") is True
    assert allowed_file("image.bmp") is True
    assert allowed_file("image.heic") is True
    assert allowed_file("file.txt") is False
    assert allowed_file("file") is False
    assert allowed_file("file.exe") is False


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
