"""Storage backend for MediaVault - supports local filesystem and AWS S3."""

import os
from abc import ABC, abstractmethod
from typing import Any, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


class StorageBackend(ABC):
    """Abstract base class for storage backends."""

    @abstractmethod
    def save(self, file_obj: Any, filename: str) -> str:
        """Save file and return the storage key/path."""
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Delete file by key."""
        pass

    @abstractmethod
    def get_file(self, key: str) -> bytes:
        """Get file content as bytes."""
        pass

    @abstractmethod
    def get_url(self, key: str, filename: str, expires_in: int = 3600) -> str:
        """Get presigned URL for downloading."""
        pass

    @abstractmethod
    def is_s3(self) -> bool:
        """Return True if using S3 backend."""
        pass


class LocalStorage(StorageBackend):
    """Local filesystem storage backend."""

    def __init__(self, upload_folder: str):
        self.upload_folder = upload_folder

    def save(self, file_obj: Any, filename: str) -> str:
        """Save file to local disk."""
        file_path = os.path.join(self.upload_folder, filename)
        file_obj.save(file_path)
        return file_path

    def delete(self, key: str) -> bool:
        """Delete file from local disk."""
        try:
            os.remove(key)
            return True
        except OSError:
            return False

    def get_file(self, key: str) -> bytes:
        """Read file from local disk."""
        with open(key, "rb") as f:
            return f.read()

    def get_url(self, key: str, filename: str, expires_in: int = 3600) -> str:
        """Local files don't need presigned URLs."""
        return key

    def is_s3(self) -> bool:
        return False


class S3Storage(StorageBackend):
    """AWS S3 storage backend."""

    def __init__(
        self,
        bucket: str,
        region: Optional[str] = None,
        prefix: str = "",
        endpoint_url: Optional[str] = None,
    ):
        self.bucket = bucket
        self.prefix = prefix.rstrip("/") + "/" if prefix else ""

        config = Config(region_name=region or "us-east-1")
        client_kwargs = {"config": config}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        self.client = boto3.client("s3", **client_kwargs)

    def _get_key(self, filename: str) -> str:
        """Generate S3 key for filename."""
        return f"{self.prefix}{filename}"

    def save(self, file_obj: Any, filename: str) -> str:
        """Upload file to S3 and return the S3 key."""
        key = self._get_key(filename)
        file_obj.seek(0)
        self.client.upload_fileobj(file_obj, self.bucket, key)
        return key

    def delete(self, key: str) -> bool:
        """Delete object from S3."""
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def get_file(self, key: str) -> bytes:
        """Download file content from S3."""
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def get_url(self, key: str, filename: str, expires_in: int = 3600) -> str:
        """Generate presigned URL for S3 object."""
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ResponseContentDisposition": f'attachment; filename="{filename}"',
                },
                ExpiresIn=expires_in,
            )
        except ClientError:
            return ""

    def is_s3(self) -> bool:
        return True


def get_storage_backend() -> StorageBackend:
    """Factory function to get the appropriate storage backend."""
    s3_bucket = os.environ.get("S3_BUCKET")
    if s3_bucket:
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        prefix = os.environ.get("S3_PREFIX", "")
        endpoint_url = os.environ.get("S3_ENDPOINT")
        return S3Storage(s3_bucket, region, prefix, endpoint_url)

    upload_folder = os.environ.get("UPLOAD_FOLDER", "uploads")
    return LocalStorage(upload_folder)


def is_s3_enabled() -> bool:
    """Check if S3 storage is configured."""
    return bool(os.environ.get("S3_BUCKET"))
