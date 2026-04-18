"""
ingestion/file_store.py — object storage abstraction.

Write raw filing content to local disk (dev) or Cloudflare R2 / AWS S3 (prod).
Switch backends by changing STORAGE_BACKEND in .env — no other code changes needed.

Usage:
    store = FileStore()
    key = store.put(cik="0000320193", accession="0001234567-24-001", form_type="10-K", content=html_text)
    raw = store.get(key)
"""

import os
from pathlib import Path

from app.core.config import get_settings

settings = get_settings()


class FileStore:

    def __init__(self):
        self.backend = settings.storage_backend.lower()

        if self.backend == "local":
            self.root = Path(settings.local_storage_root)
            self.root.mkdir(parents=True, exist_ok=True)

        elif self.backend in ("r2", "s3"):
            import boto3
            from botocore.config import Config

            if self.backend == "r2":
                endpoint = f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
                self._client = boto3.client(
                    "s3",
                    endpoint_url=endpoint,
                    aws_access_key_id=settings.r2_access_key_id,
                    aws_secret_access_key=settings.r2_secret_access_key,
                    config=Config(signature_version="s3v4"),
                    region_name="auto",
                )
            else:
                self._client = boto3.client("s3")

            self.bucket = settings.r2_bucket

        else:
            raise ValueError(f"Unknown STORAGE_BACKEND: {self.backend!r}. Use 'local', 'r2', or 's3'.")

    # ── Public API ────────────────────────────────────────────────────────────

    def put(self, cik: str, accession: str, form_type: str, content: str) -> str:
        """
        Save raw filing text. Returns the storage key.
        The key is stored in filings.raw_s3_key in Postgres.

        Key format: {cik}/{form_type}/{accession}.txt
        Example:    0000320193/10-K/0001234567-24-000001.txt
        """
        key = self._make_key(cik, accession, form_type)

        if self.backend == "local":
            path = self.root / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        else:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=content.encode("utf-8"),
                ContentType="text/plain; charset=utf-8",
            )

        return key

    def get(self, key: str) -> str:
        """Retrieve raw filing text by its storage key."""
        if self.backend == "local":
            path = self.root / key
            if not path.exists():
                raise FileNotFoundError(f"Filing not found at local path: {path}")
            return path.read_text(encoding="utf-8")
        else:
            obj = self._client.get_object(Bucket=self.bucket, Key=key)
            return obj["Body"].read().decode("utf-8")

    def exists(self, key: str) -> bool:
        """Return True if an object with this key already exists."""
        if self.backend == "local":
            return (self.root / key).exists()
        else:
            try:
                self._client.head_object(Bucket=self.bucket, Key=key)
                return True
            except self._client.exceptions.ClientError:
                return False

    def size_bytes(self, key: str) -> int:
        """Return the size of a stored object in bytes."""
        if self.backend == "local":
            path = self.root / key
            return path.stat().st_size if path.exists() else 0
        else:
            resp = self._client.head_object(Bucket=self.bucket, Key=key)
            return resp["ContentLength"]

    # ── Private ───────────────────────────────────────────────────────────────

    @staticmethod
    def _make_key(cik: str, accession: str, form_type: str) -> str:
        safe_form = form_type.replace("/", "_").replace(" ", "_")
        return f"{cik}/{safe_form}/{accession}.txt"