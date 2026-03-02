"""Storage backend for MediaVault - supports local filesystem, AWS S3, and Azure Blob Storage."""

import os
import urllib.parse
from abc import ABC, abstractmethod
from io import BytesIO
from typing import Any, Optional

import boto3
from azure.core.exceptions import AzureError
from azure.storage.blob import BlobServiceClient, generate_blob_sas
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError, EndpointConnectionError

from config import Config
from config import is_azure_enabled as config_is_azure_enabled
from config import is_s3_enabled as config_is_s3_enabled


class StorageError(Exception):
    """Base exception for storage errors."""

    def __init__(self, message: str, is_retryable: bool = False):
        super().__init__(message)
        self.message = message
        self.is_retryable = is_retryable


class S3ConnectionError(StorageError):
    """Exception raised when S3 connection fails."""

    def __init__(self, message: str = "Failed to connect to S3 storage"):
        super().__init__(message, is_retryable=True)


class S3UploadError(StorageError):
    """Exception raised when S3 upload fails."""

    def __init__(self, message: str = "Failed to upload file to S3"):
        super().__init__(message, is_retryable=True)


class S3DownloadError(StorageError):
    """Exception raised when S3 download fails."""

    def __init__(self, message: str = "Failed to download file from S3"):
        super().__init__(message, is_retryable=False)


class S3DeleteError(StorageError):
    """Exception raised when S3 delete fails."""

    def __init__(self, message: str = "Failed to delete file from S3"):
        super().__init__(message, is_retryable=False)


class AzureConnectionError(StorageError):
    """Exception raised when Azure connection fails."""

    def __init__(self, message: str = "Failed to connect to Azure storage"):
        super().__init__(message, is_retryable=True)


class AzureUploadError(StorageError):
    """Exception raised when Azure upload fails."""

    def __init__(self, message: str = "Failed to upload file to Azure"):
        super().__init__(message, is_retryable=True)


class AzureDownloadError(StorageError):
    """Exception raised when Azure download fails."""

    def __init__(self, message: str = "Failed to download file from Azure"):
        super().__init__(message, is_retryable=False)


class AzureDeleteError(StorageError):
    """Exception raised when Azure delete fails."""

    def __init__(self, message: str = "Failed to delete file from Azure"):
        super().__init__(message, is_retryable=False)


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


VIDEO_EXTENSIONS = {"mp4", "avi", "mov", "mkv", "wmv", "flv", "webm"}
AUDIO_EXTENSIONS = {"mp3", "wav", "ogg"}


def get_media_subdir(filename: str) -> str:
    """Determine subdirectory based on file extension."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in VIDEO_EXTENSIONS:
        return "videos"
    if ext in AUDIO_EXTENSIONS:
        return "audios"
    return "videos"


class LocalStorage(StorageBackend):
    """Local filesystem storage backend."""

    def __init__(self, upload_folder: str):
        self.upload_folder = upload_folder
        self.videos_dir = os.path.join(upload_folder, "videos")
        self.audios_dir = os.path.join(upload_folder, "audios")
        os.makedirs(self.videos_dir, exist_ok=True)
        os.makedirs(self.audios_dir, exist_ok=True)

    def save(self, file_obj: Any, filename: str) -> str:
        """Save file to local disk in appropriate subdirectory."""
        subdir = get_media_subdir(filename)
        if subdir == "videos":
            target_dir = self.videos_dir
        else:
            target_dir = self.audios_dir
        file_path = os.path.join(target_dir, filename)
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
        try:
            with open(key, "rb") as f:
                return f.read()
        except FileNotFoundError as e:
            raise StorageError(f"File not found: {key}", is_retryable=False) from e

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

        config = BotoConfig(region_name=region or "us-east-1")
        client_kwargs = {"config": config}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        self.client = boto3.client("s3", **client_kwargs)

    def _get_key(self, filename: str) -> str:
        """Generate S3 key for filename with subdirectory."""
        subdir = get_media_subdir(filename)
        return f"{self.prefix}{subdir}/{filename}"

    def save(self, file_obj: Any, filename: str) -> str:
        """Upload file to S3 and return the S3 key."""
        key = self._get_key(filename)
        file_obj.seek(0)
        try:
            self.client.upload_fileobj(file_obj, self.bucket, key)
        except (ClientError, BotoCoreError, EndpointConnectionError) as e:
            raise S3UploadError(f"Failed to upload to S3: {str(e)}") from e
        return key

    def delete(self, key: str) -> bool:
        """Delete object from S3."""
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except (ClientError, BotoCoreError, EndpointConnectionError) as e:
            raise S3DeleteError(f"Failed to delete from S3: {str(e)}") from e

    def get_file(self, key: str) -> bytes:
        """Download file content from S3."""
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except (ClientError, BotoCoreError, EndpointConnectionError) as e:
            raise S3DownloadError(f"Failed to download from S3: {str(e)}") from e

    def get_url(
        self, key: str, filename: str, expires_in: int = 3600, inline: bool = False
    ) -> str:
        """Generate presigned URL for S3 object."""
        disposition = "inline" if inline else "attachment"
        try:
            try:
                filename.encode("ascii")
                filename_param = f'filename="{filename}"'
            except UnicodeEncodeError:
                encoded = urllib.parse.quote(filename)
                filename_param = f"filename*=UTF-8''{encoded}"

            return self.client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ResponseContentDisposition": f"{disposition}; {filename_param}",
                },
                ExpiresIn=expires_in,
            )
        except (ClientError, BotoCoreError, EndpointConnectionError) as e:
            raise S3DownloadError(f"Failed to generate download URL: {str(e)}") from e

    def is_s3(self) -> bool:
        return True


class AzureStorage(StorageBackend):
    """Azure Blob Storage backend."""

    def __init__(
        self,
        account_name: str,
        account_key: Optional[str] = None,
        container: str = "media",
        connection_string: Optional[str] = None,
    ):
        self.container = container
        self.account_name = account_name
        self.account_key = account_key

        if connection_string:
            self.client = BlobServiceClient.from_connection_string(connection_string)
        else:
            account_key = account_key or ""
            connection_str = (
                f"DefaultEndpointsProtocol=https;"
                f"AccountName={account_name};"
                f"AccountKey={account_key}"
            )
            self.client = BlobServiceClient.from_connection_string(connection_str)

        self._base_url = None

    def _get_blob_name(self, filename: str) -> str:
        """Generate blob name for filename with subdirectory."""
        subdir = get_media_subdir(filename)
        return f"{subdir}/{filename}"

    def save(self, file_obj: Any, filename: str) -> str:
        """Upload file to Azure and return the blob name."""
        blob_name = self._get_blob_name(filename)
        file_obj.seek(0)
        file_content = file_obj.read()

        try:
            blob = self.client.get_blob_client(container=self.container, blob=blob_name)

            blob.upload_blob(BytesIO(file_content), overwrite=True)
        except AzureError as e:
            raise AzureUploadError(f"Failed to upload to Azure: {str(e)}") from e
        return blob_name

    def delete(self, key: str) -> bool:
        """Delete blob from Azure."""
        try:
            blob = self.client.get_blob_client(container=self.container, blob=key)
            blob.delete_blob()
            return True
        except AzureError as e:
            raise AzureDeleteError(f"Failed to delete from Azure: {str(e)}") from e

    def get_file(self, key: str) -> bytes:
        """Download file content from Azure."""
        try:
            blob = self.client.get_blob_client(container=self.container, blob=key)
            return blob.download_blob().readall()
        except AzureError as e:
            raise AzureDownloadError(f"Failed to download from Azure: {str(e)}") from e

    def get_url(
        self, key: str, filename: str, expires_in: int = 3600, inline: bool = False
    ) -> str:
        """Generate SAS URL for Azure blob."""
        try:
            account_key = getattr(
                getattr(self.client, "credential", None), "account_key", None
            )
            if account_key:
                sas_token = generate_blob_sas(
                    account_name=self.client.account_name,
                    container_name=self.container,
                    blob_name=key,
                    account_key=account_key,
                    expiry=__import__("datetime").datetime.utcnow()
                    + __import__("datetime").timedelta(seconds=expires_in),
                )
                base_url = self.client.get_blob_client(
                    container=self.container, blob=key
                ).url
                url = f"{base_url}?{sas_token}"
                return url
            blob_client = self.client.get_blob_client(
                container=self.container, blob=key
            )
            base_url = blob_client.url
        except AzureError as e:
            raise AzureDownloadError(
                f"Failed to generate download URL: {str(e)}"
            ) from e

        disposition = "inline" if inline else "attachment"
        try:
            try:
                filename.encode("ascii")
                filename_param = f'filename="{filename}"'
            except UnicodeEncodeError:
                encoded = urllib.parse.quote(filename)
                filename_param = f"filename*=UTF-8''{encoded}"
            return f"{base_url}?{disposition}; {filename_param}"
        except Exception as e:
            raise AzureDownloadError(
                f"Failed to generate download URL: {str(e)}"
            ) from e

    def is_s3(self) -> bool:
        return False


def get_storage_backend() -> StorageBackend:
    """Factory function to get the appropriate storage backend."""
    s3_bucket = Config.S3_BUCKET()
    if s3_bucket:
        region = Config.AWS_REGION() or Config.AWS_DEFAULT_REGION()
        prefix = Config.S3_PREFIX() or ""
        endpoint_url = Config.S3_ENDPOINT()
        return S3Storage(s3_bucket, region, prefix, endpoint_url)

    if is_azure_enabled():
        azure_account = Config.AZURE_STORAGE_ACCOUNT()
        account_key = Config.AZURE_STORAGE_KEY()
        container = Config.AZURE_CONTAINER() or "media"
        connection_string = Config.AZURE_CONNECTION_STRING()
        return AzureStorage(azure_account, account_key, container, connection_string)

    upload_folder = Config.UPLOAD_FOLDER()
    return LocalStorage(upload_folder)


def is_s3_enabled() -> bool:
    """Check if S3 storage is configured."""
    return config_is_s3_enabled()


def is_azure_enabled() -> bool:
    """Check if Azure storage is configured."""
    return config_is_azure_enabled()
