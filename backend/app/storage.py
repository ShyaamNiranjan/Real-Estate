"""Object storage. Browsers upload straight to storage through short-lived signed URLs; media
never passes through the API in production (docs/SCOPE.md 4, 9.4).

Keys: `private/ws/<workspace>/...` (drafts, originals) and `public/ws/<workspace>/...` (copied at
Publish, served through the Cloudflare cache). `LocalStorage` mimics R2 for development and
tests until the R2 keys exist.
"""

import base64
import hashlib
import hmac
import json
import shutil
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import get_settings


@dataclass(frozen=True)
class UploadTarget:
    url: str
    method: str
    headers: dict[str, str]
    expires_in: int


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: str


class Storage:
    def upload_target(self, key: str, content_type: str, size: int, ttl: int = 900) -> UploadTarget: ...
    def signed_url(self, key: str, ttl: int = 3600) -> str: ...
    def public_url(self, key: str) -> str: ...
    def head(self, key: str) -> ObjectInfo | None: ...
    def read(self, key: str, max_bytes: int | None = None) -> bytes: ...
    def download(self, key: str, path: Path) -> None: ...
    def upload_file(self, path: Path, key: str, content_type: str) -> None: ...
    def write(self, key: str, data: bytes, content_type: str) -> None: ...
    def copy(self, source: str, destination: str) -> None: ...
    def delete(self, keys: list[str]) -> None: ...
    def delete_prefix(self, prefix: str) -> None: ...
    def list_prefix(self, prefix: str) -> list[str]: ...


def _require_prefix(key: str, prefix: str) -> None:
    if not key.startswith(prefix) or ".." in key.split("/"):
        raise ValueError(f"storage key must start with {prefix}")


def private_to_public(key: str) -> str:
    _require_prefix(key, "private/")
    return "public/" + key[len("private/"):]


# ---------- local (development and tests) ----------


def _sign(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    mac = hmac.new(get_settings().secret_key.encode(), f"storage:{body}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{mac}"


def verify_token(token: str) -> dict | None:
    try:
        body, mac = token.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(get_settings().secret_key.encode(), f"storage:{body}".encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(mac, expected):
        return None
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    return payload if payload.get("exp", 0) >= time.time() else None


class LocalStorage(Storage):
    def __init__(self, root: Path, base_url: str):
        self.root = root.resolve()
        self.api = f"{base_url}/api/v1/media/local"

    def _path(self, key: str) -> Path:
        parts = key.split("/")
        if not key or "\\" in key or ":" in key or any(p in ("", ".", "..") for p in parts):
            raise ValueError("invalid storage key")
        return self.root.joinpath(*parts)

    def _meta(self, key: str) -> Path:
        return self._path(key).with_name(self._path(key).name + ".meta")

    def upload_target(self, key, content_type, size, ttl=900):
        token = _sign({"op": "put", "key": key, "ct": content_type, "size": size, "exp": int(time.time()) + ttl})
        return UploadTarget(f"{self.api}/upload/{token}", "PUT",
                            {"Content-Type": content_type, "Content-Length": str(size)}, ttl)

    def signed_url(self, key, ttl=3600):
        return f"{self.api}/file/{_sign({'op': 'get', 'key': key, 'exp': int(time.time()) + ttl})}"

    def public_url(self, key):
        _require_prefix(key, "public/")
        return f"{self.api}/{key}"

    def head(self, key):
        path = self._path(key)
        if not path.is_file():
            return None
        meta = json.loads(self._meta(key).read_text()) if self._meta(key).exists() else {}
        return ObjectInfo(path.stat().st_size, meta.get("content_type", "application/octet-stream"))

    def read(self, key, max_bytes=None):
        with self._path(key).open("rb") as f:
            return f.read(max_bytes) if max_bytes else f.read()

    def download(self, key, path):
        shutil.copyfile(self._path(key), path)

    def write(self, key, data, content_type):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self._meta(key).write_text(json.dumps({"content_type": content_type}))

    def upload_file(self, path, key, content_type):
        self.write(key, Path(path).read_bytes(), content_type)

    def copy(self, source, destination):
        info = self.head(source)
        self.write(destination, self.read(source), info.content_type if info else "application/octet-stream")

    def delete(self, keys):
        for key in keys:
            for p in (self._path(key), self._meta(key)):
                p.unlink(missing_ok=True)

    def list_prefix(self, prefix):
        base = self._path(prefix.rstrip("/"))
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)).replace("\\", "/")
                      for p in base.rglob("*") if p.is_file() and not p.name.endswith(".meta"))

    def delete_prefix(self, prefix):
        self.delete(self.list_prefix(prefix))


# ---------- Cloudflare R2 ----------


class R2Storage(Storage):
    def __init__(self, account_id: str, access_key: str, secret_key: str, bucket: str, public_base: str):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.public_base = public_base.rstrip("/")
        self.client = boto3.client(
            "s3", endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key, aws_secret_access_key=secret_key, region_name="auto",
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )

    def upload_target(self, key, content_type, size, ttl=900):
        # Content-Type and Content-Length are signed: R2 refuses an upload of any other size or type.
        url = self.client.generate_presigned_url(
            "put_object", ExpiresIn=ttl,
            Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type, "ContentLength": size},
        )
        return UploadTarget(url, "PUT", {"Content-Type": content_type, "Content-Length": str(size)}, ttl)

    def signed_url(self, key, ttl=3600):
        return self.client.generate_presigned_url("get_object", ExpiresIn=ttl,
                                                  Params={"Bucket": self.bucket, "Key": key})

    def public_url(self, key):
        _require_prefix(key, "public/")
        return f"{self.public_base}/{key}"

    def head(self, key):
        from botocore.exceptions import ClientError

        try:
            r = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return None
        return ObjectInfo(r["ContentLength"], r.get("ContentType", ""))

    def read(self, key, max_bytes=None):
        extra = {"Range": f"bytes=0-{max_bytes - 1}"} if max_bytes else {}
        return self.client.get_object(Bucket=self.bucket, Key=key, **extra)["Body"].read()

    def download(self, key, path):
        self.client.download_file(self.bucket, key, str(path))

    def write(self, key, data, content_type):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type,
                               CacheControl="public, max-age=31536000, immutable")

    def upload_file(self, path, key, content_type):
        self.client.upload_file(str(path), self.bucket, key, ExtraArgs={
            "ContentType": content_type, "CacheControl": "public, max-age=31536000, immutable"})

    def copy(self, source, destination):
        self.client.copy_object(Bucket=self.bucket, Key=destination,
                                CopySource={"Bucket": self.bucket, "Key": source})

    def delete(self, keys):
        for i in range(0, len(keys), 1000):
            batch = keys[i:i + 1000]
            if batch:
                self.client.delete_objects(Bucket=self.bucket, Delete={"Objects": [{"Key": k} for k in batch]})

    def list_prefix(self, prefix):
        keys = []
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            keys += [o["Key"] for o in page.get("Contents", [])]
        return keys

    def delete_prefix(self, prefix):
        self.delete(self.list_prefix(prefix))


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.storage_backend == "r2":
        if not all([s.r2_account_id, s.r2_access_key_id, s.r2_secret_access_key, s.r2_bucket, s.media_public_base_url]):
            raise RuntimeError("R2 storage needs R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET "
                               "and MEDIA_PUBLIC_BASE_URL")
        return R2Storage(s.r2_account_id, s.r2_access_key_id, s.r2_secret_access_key, s.r2_bucket,
                         s.media_public_base_url)
    if s.environment == "production":
        raise RuntimeError("Local storage is for development only")
    # Through the app's own origin (the frontend proxies /api), so browser uploads aren't cross-site.
    return LocalStorage(s.local_media_dir, s.app_url)
