"""WSGI entry point for Gunicorn.

Usage:
    gunicorn -w 1 -b 0.0.0.0:5050 app:application
"""

from app import ensure_upload_folder, init_db

# Initialize database and upload folder on startup
init_db()
ensure_upload_folder()
