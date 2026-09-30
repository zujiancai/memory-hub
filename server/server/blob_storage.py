"""Blob storage abstraction.

Phase 1 has two implementations:

- ``LocalBlobStore``: on-disk fake used for tests and local dev when
  ``AZURE_STORAGE_CONNECTION_STRING`` is empty. Also supports an in-memory
  variant for pytest.
- ``AzureBlobStore``: Azure Storage backed by ``azure-storage-blob``.
"""
from __future__ import annotations

import os
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote


class BlobStore(ABC):
    @abstractmethod
    def exists(self, blob_name: str) -> bool: ...

    @abstractmethod
    def size_of(self, blob_name: str) -> Optional[int]: ...

    @abstractmethod
    def put(self, blob_name: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...

    @abstractmethod
    def get(self, blob_name: str) -> bytes: ...

    @abstractmethod
    def delete(self, blob_name: str) -> None: ...

    @abstractmethod
    def upload_sas_url(self, blob_name: str, ttl_seconds: int = 900) -> str: ...

    @abstractmethod
    def read_sas_url(self, blob_name: str, ttl_seconds: int = 900) -> str: ...


# ---------------------------------------------------------------------------
# In-memory / local fake used by tests and dev
# ---------------------------------------------------------------------------


class LocalBlobStore(BlobStore):
    """In-memory store, optionally persisted to disk.

    Ships a signed but unfaked URL so tests can round-trip through the
    ``PUT`` verb: the URL is a stable ``memoryhub-local://`` scheme that the
    application layer uploads/downloads through a helper.
    """

    def __init__(self, root_dir: Optional[str] = None, container: str = "memoryhub-media") -> None:
        self._lock = threading.Lock()
        self._data: dict[str, bytes] = {}
        self._content_types: dict[str, str] = {}
        self._root_dir = root_dir
        self._container = container
        if root_dir:
            os.makedirs(root_dir, exist_ok=True)

    # --- primitives ---
    def _disk_path(self, blob_name: str) -> Optional[str]:
        if not self._root_dir:
            return None
        return os.path.join(self._root_dir, blob_name)

    def exists(self, blob_name: str) -> bool:
        with self._lock:
            if blob_name in self._data:
                return True
        path = self._disk_path(blob_name)
        return bool(path and os.path.exists(path))

    def size_of(self, blob_name: str) -> Optional[int]:
        with self._lock:
            if blob_name in self._data:
                return len(self._data[blob_name])
        path = self._disk_path(blob_name)
        if path and os.path.exists(path):
            return os.path.getsize(path)
        return None

    def put(self, blob_name: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        with self._lock:
            self._data[blob_name] = bytes(data)
            self._content_types[blob_name] = content_type
        path = self._disk_path(blob_name)
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)

    def get(self, blob_name: str) -> bytes:
        with self._lock:
            if blob_name in self._data:
                return self._data[blob_name]
        path = self._disk_path(blob_name)
        if path and os.path.exists(path):
            with open(path, "rb") as fh:
                data = fh.read()
            with self._lock:
                self._data[blob_name] = data
            return data
        raise FileNotFoundError(blob_name)

    def delete(self, blob_name: str) -> None:
        with self._lock:
            self._data.pop(blob_name, None)
            self._content_types.pop(blob_name, None)
        path = self._disk_path(blob_name)
        if path and os.path.exists(path):
            os.remove(path)

    # --- signed URLs ---
    def upload_sas_url(self, blob_name: str, ttl_seconds: int = 900) -> str:
        exp = int((datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).timestamp())
        return f"memoryhub-local://upload/{self._container}/{quote(blob_name)}?exp={exp}"

    def read_sas_url(self, blob_name: str, ttl_seconds: int = 900) -> str:
        exp = int((datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).timestamp())
        return f"memoryhub-local://read/{self._container}/{quote(blob_name)}?exp={exp}"


# ---------------------------------------------------------------------------
# Azure implementation
# ---------------------------------------------------------------------------


class AzureBlobStore(BlobStore):  # pragma: no cover - Azure I/O
    def __init__(self, connection_string: str, container: str) -> None:
        from azure.storage.blob import BlobServiceClient  # local import

        self._service = BlobServiceClient.from_connection_string(connection_string)
        self._container = container
        self._connection_string = connection_string
        self._container_client = self._service.get_container_client(container)
        try:
            self._container_client.create_container()
        except Exception:
            pass

    def _client(self, blob_name: str):
        return self._service.get_blob_client(self._container, blob_name)

    def exists(self, blob_name: str) -> bool:
        return self._client(blob_name).exists()

    def size_of(self, blob_name: str) -> Optional[int]:
        try:
            props = self._client(blob_name).get_blob_properties()
        except Exception:
            return None
        return props.size

    def put(self, blob_name: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        from azure.storage.blob import ContentSettings

        self._client(blob_name).upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

    def get(self, blob_name: str) -> bytes:
        return self._client(blob_name).download_blob().readall()

    def delete(self, blob_name: str) -> None:
        try:
            self._client(blob_name).delete_blob()
        except Exception:
            pass

    def _sas(self, blob_name: str, ttl_seconds: int, write: bool) -> str:
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        expiry = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        perms = (
            BlobSasPermissions(write=True, create=True, add=True)
            if write
            else BlobSasPermissions(read=True)
        )
        # Parse the account name / key out of the connection string.
        parts = dict(
            kv.split("=", 1) for kv in self._connection_string.split(";") if "=" in kv
        )
        token = generate_blob_sas(
            account_name=parts.get("AccountName", ""),
            container_name=self._container,
            blob_name=blob_name,
            account_key=parts.get("AccountKey", ""),
            permission=perms,
            expiry=expiry,
        )
        endpoint = parts.get(
            "BlobEndpoint",
            f"https://{parts.get('AccountName')}.blob.core.windows.net",
        ).rstrip("/")
        return f"{endpoint}/{self._container}/{quote(blob_name)}?{token}"

    def upload_sas_url(self, blob_name: str, ttl_seconds: int = 900) -> str:
        return self._sas(blob_name, ttl_seconds, write=True)

    def read_sas_url(self, blob_name: str, ttl_seconds: int = 900) -> str:
        return self._sas(blob_name, ttl_seconds, write=False)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_store_from_config(config) -> BlobStore:
    if config.azure_storage_connection_string:
        return AzureBlobStore(
            config.azure_storage_connection_string, config.azure_storage_container
        )
    return LocalBlobStore(
        root_dir=config.local_blob_dir,
        container=config.azure_storage_container,
    )
