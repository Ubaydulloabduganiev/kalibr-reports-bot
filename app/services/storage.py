from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

import boto3

from app.core.config import settings

LOCAL_ROOT = Path("/tmp/kalibr-reports-storage")


class ObjectStorage:
    def __init__(self) -> None:
        self.enabled = bool(
            settings.s3_endpoint_url and settings.s3_access_key_id and settings.s3_secret_access_key
        )
        self.client = None
        if self.enabled:
            self.client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=settings.s3_secret_access_key,
                region_name=settings.s3_region,
            )

    async def save(self, source: Path, *, prefix: str, filename: str | None = None) -> str:
        safe_name = filename or source.name
        key = f"{prefix.strip('/')}/{uuid.uuid4().hex}-{safe_name}"
        if self.client:
            await asyncio.to_thread(self.client.upload_file, str(source), settings.s3_bucket, key)
            return key

        target = LOCAL_ROOT / key
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copy2, source, target)
        return f"local:{target}"

    async def materialize(self, key: str) -> Path:
        if key.startswith("local:"):
            return Path(key.removeprefix("local:"))
        target = LOCAL_ROOT / "downloads" / key
        target.parent.mkdir(parents=True, exist_ok=True)
        if not self.client:
            raise RuntimeError("S3 storage is not configured")
        await asyncio.to_thread(self.client.download_file, settings.s3_bucket, key, str(target))
        return target


object_storage = ObjectStorage()
