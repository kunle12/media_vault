"""Centralized configuration management for MediaVault."""

import os
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env.local")


class Config:
    """Class with cached environment variable access."""

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
        """Get Flask secret key, used only to sign the sort-preference cookie."""
        return Config.get("SECRET_KEY", os.urandom(32).hex())

    @staticmethod
    @lru_cache(maxsize=None)
    def UPLOAD_FOLDER() -> str:
        """Get upload folder path."""
        return Config.get("UPLOAD_FOLDER", "uploads")

    @staticmethod
    @lru_cache(maxsize=None)
    def MAX_CONTENT_LENGTH() -> int:
        """Get max upload size in bytes (set MAX_CONTENT_LENGTH_MB env var)."""
        return Config.get_int("MAX_CONTENT_LENGTH_MB", 500) * 1024 * 1024

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

    #: Header set by the guard through nginx. The app never reads identity
    #: from a cookie; a request without this header is refused at the edge.
    IDENTITY_HEADER = "X-Auth-User"
    GROUPS_HEADER = "X-Auth-Groups"
    #: Only accept the identity header from the local reverse proxy.
    TRUSTED_PROXY_ADDRS = frozenset({"127.0.0.1", "::1"})

    ALLOWED_EXTENSIONS = {
        "mp4",
        "avi",
        "mov",
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
        """Get Azure container name."""
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
    def ITEMS_PER_PAGE() -> int:
        """Get items per page for pagination (default 50)."""
        return Config.get_int("ITEMS_PER_PAGE", 50)


def is_s3_enabled() -> bool:
    """Check if S3 storage is configured."""
    return Config.S3_ENABLED()


def is_azure_enabled() -> bool:
    """Check if Azure storage is configured."""
    return Config.AZURE_ENABLED()


def get_aws_region() -> str:
    """Get AWS region."""
    return Config.AWS_REGION() or Config.AWS_DEFAULT_REGION()


def get_application_root() -> str:
    """Get application root path for subpath hosting."""
    return Config.APPLICATION_ROOT()


def get_server_name() -> str:
    """Get server name for external URL generation."""
    return Config.SERVER_NAME()
