"""Centralized configuration management for MediaVault."""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env.local")


class Config:
    """Central configuration class with cached environment variable access."""

    @staticmethod
    @lru_cache(maxsize=None)
    def get(key: str, default: str = "") -> str:
        """Get cached environment variable."""
        return os.environ.get(key, default)

    @staticmethod
    @lru_cache(maxsize=None)
    def get_int(key: str, default: int = 0) -> int:
        """Get cached environment variable as int."""
        return int(os.environ.get(key, str(default)))

    @staticmethod
    @lru_cache(maxsize=None)
    def get_bool(key: str, default: bool = False) -> bool:
        """Get cached environment variable as bool."""
        val = os.environ.get(key, str(default)).lower()
        return val in ("true", "1", "yes")

    @staticmethod
    @lru_cache(maxsize=None)
    def SECRET_KEY() -> str:
        """Get Flask secret key."""
        return Config.get("SECRET_KEY", os.urandom(32).hex())

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None

    @staticmethod
    @lru_cache(maxsize=None)
    def UPLOAD_FOLDER() -> str:
        """Get upload folder path."""
        return Config.get("UPLOAD_FOLDER", "uploads")

    MAX_CONTENT_LENGTH = 500 * 1024 * 1024

    @staticmethod
    @lru_cache(maxsize=None)
    def DATABASE() -> str:
        """Get database path."""
        return Config.get("DATABASE", "videodb.sqlite")

    @staticmethod
    @lru_cache(maxsize=None)
    def APPLICATION_ROOT() -> str:
        """Get application root path for subpath hosting."""
        return Config.get("APPLICATION_ROOT", "/")

    @staticmethod
    @lru_cache(maxsize=None)
    def SERVER_NAME() -> str:
        """Get server name for external URL generation."""
        return Config.get("SERVER_NAME", "")

    @staticmethod
    @lru_cache(maxsize=None)
    def CACHE_TYPE() -> str:
        """Get cache type."""
        return Config.get("CACHE_TYPE", "simple")

    @staticmethod
    @lru_cache(maxsize=None)
    def CACHE_REDIS_URL() -> str:
        """Get Redis cache URL."""
        return Config.get("CACHE_REDIS_URL", "redis://localhost:6379/0")

    CACHE_DEFAULT_TIMEOUT = 300

    ALLOWED_EXTENSIONS = {
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
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "bmp",
        "heic",
    }

    @staticmethod
    @lru_cache(maxsize=None)
    def GOOGLE_CLIENT_ID() -> str:
        """Get Google OAuth client ID."""
        return Config.get("GOOGLE_CLIENT_ID")

    @staticmethod
    @lru_cache(maxsize=None)
    def GOOGLE_CLIENT_SECRET() -> str:
        """Get Google OAuth client secret."""
        return Config.get("GOOGLE_CLIENT_SECRET")

    @staticmethod
    @lru_cache(maxsize=None)
    def GOOGLE_OAUTH_ENABLED() -> bool:
        """Check if Google OAuth is enabled."""
        return bool(Config.GOOGLE_CLIENT_ID() and Config.GOOGLE_CLIENT_SECRET())

    @staticmethod
    @lru_cache(maxsize=None)
    def EMAIL_PROVIDER() -> str:
        """Get email provider."""
        return Config.get("EMAIL_PROVIDER", "generic").lower()

    @staticmethod
    @lru_cache(maxsize=None)
    def SMTP_HOST() -> str:
        """Get SMTP host."""
        return Config.get("SMTP_HOST")

    @staticmethod
    @lru_cache(maxsize=None)
    def SMTP_PORT() -> int:
        """Get SMTP port."""
        return Config.get_int("SMTP_PORT", 587)

    @staticmethod
    @lru_cache(maxsize=None)
    def SMTP_USER() -> str:
        """Get SMTP user."""
        return Config.get("SMTP_USER")

    @staticmethod
    @lru_cache(maxsize=None)
    def SMTP_PASSWORD() -> str:
        """Get SMTP password."""
        return Config.get("SMTP_PASSWORD")

    @staticmethod
    @lru_cache(maxsize=None)
    def FROM_EMAIL() -> str:
        """Get from email."""
        return Config.get("FROM_EMAIL") or Config.get("SMTP_USER")

    @staticmethod
    @lru_cache(maxsize=None)
    def AWS_REGION() -> str:
        """Get AWS region."""
        return Config.get("AWS_REGION", "us-east-1")

    @staticmethod
    @lru_cache(maxsize=None)
    def AWS_DEFAULT_REGION() -> str:
        """Get AWS default region."""
        return Config.get("AWS_DEFAULT_REGION")

    @staticmethod
    @lru_cache(maxsize=None)
    def S3_BUCKET() -> str:
        """Get S3 bucket name."""
        return Config.get("S3_BUCKET")

    @staticmethod
    @lru_cache(maxsize=None)
    def S3_PREFIX() -> str:
        """Get S3 prefix."""
        return Config.get("S3_PREFIX")

    @staticmethod
    @lru_cache(maxsize=None)
    def S3_ENDPOINT() -> str:
        """Get S3 endpoint."""
        return Config.get("S3_ENDPOINT")

    @staticmethod
    @lru_cache(maxsize=None)
    def S3_ENABLED() -> bool:
        """Check if S3 storage is enabled."""
        return bool(Config.S3_BUCKET())

    @staticmethod
    @lru_cache(maxsize=None)
    def AZURE_STORAGE_ACCOUNT() -> str:
        """Get Azure storage account name."""
        return Config.get("AZURE_STORAGE_ACCOUNT")

    @staticmethod
    @lru_cache(maxsize=None)
    def AZURE_STORAGE_KEY() -> str:
        """Get Azure storage account key."""
        return Config.get("AZURE_STORAGE_KEY")

    @staticmethod
    @lru_cache(maxsize=None)
    def AZURE_CONTAINER() -> str:
        """Get Azure blob container name."""
        return Config.get("AZURE_CONTAINER")

    @staticmethod
    @lru_cache(maxsize=None)
    def AZURE_CONNECTION_STRING() -> str:
        """Get Azure connection string."""
        return Config.get("AZURE_CONNECTION_STRING")

    @staticmethod
    @lru_cache(maxsize=None)
    def AZURE_ENABLED() -> bool:
        """Check if Azure storage is enabled."""
        return bool(
            Config.AZURE_STORAGE_ACCOUNT() and Config.AZURE_STORAGE_KEY()
        ) or bool(Config.AZURE_CONNECTION_STRING())

    @staticmethod
    @lru_cache(maxsize=None)
    def ALLOWED_EMAILS() -> str:
        """Get allowed emails."""
        return Config.get("ALLOWED_EMAILS")

    CODE_EXPIRY_SECONDS = 300
    MAX_CODE_ATTEMPTS = 5
    RATE_LIMIT_SECONDS = 60

    @staticmethod
    @lru_cache(maxsize=None)
    def SESSION_TIMEOUT_MINUTES() -> int:
        """Get session timeout in minutes (default 10)."""
        return Config.get_int("SESSION_TIMEOUT_MINUTES", 10)


def is_google_oauth_enabled() -> bool:
    """Check if Google OAuth is configured."""
    return Config.GOOGLE_OAUTH_ENABLED()


def is_s3_enabled() -> bool:
    """Check if S3 storage is configured."""
    return Config.S3_ENABLED()


def is_azure_enabled() -> bool:
    """Check if Azure storage is configured."""
    return Config.AZURE_ENABLED()


def get_google_client_id() -> str:
    """Get Google OAuth client ID."""
    return Config.GOOGLE_CLIENT_ID()


def get_google_client_secret() -> str:
    """Get Google OAuth client secret."""
    return Config.GOOGLE_CLIENT_SECRET()


def get_aws_region() -> str:
    """Get AWS region."""
    return Config.AWS_REGION() or Config.AWS_DEFAULT_REGION()


def get_smtp_config() -> dict:
    """Get SMTP configuration."""
    return {
        "host": Config.SMTP_HOST(),
        "port": Config.SMTP_PORT(),
        "user": Config.SMTP_USER(),
        "password": Config.SMTP_PASSWORD(),
        "from_email": Config.FROM_EMAIL(),
        "provider": Config.EMAIL_PROVIDER(),
    }


def get_allowed_emails() -> set:
    """Get allowed emails as a set."""
    emails = Config.ALLOWED_EMAILS()
    return set(emails.lower().split()) if emails else set()


def get_application_root() -> str:
    """Get application root path for subpath hosting."""
    return Config.APPLICATION_ROOT()


def get_server_name() -> str:
    """Get server name for external URL generation."""
    return Config.SERVER_NAME()
