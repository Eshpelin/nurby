"""Native remote storage backends: FTP (issue #269) and S3 (issue #270).

Buffer-then-upload: segments are always written locally first; recordings
belonging to a camera with an ``kind="ftp"`` storage profile are marked
``pending`` at finalize time and transferred by the ingestion upload
worker (``services/ingestion/remote_upload.py``). The local copy is only
removed after a size-verified upload, and playback falls back to an
on-demand download cache, so an unreachable FTP server degrades to "files
stay local", never to lost footage.

Connection settings live Fernet-sealed on the profile
(``config_enc`` — JSON with the password sealed via the camera-credential
cipher) and are never logged or echoed.
"""

import asyncio
import json
import logging
import os
import posixpath
import time
from dataclasses import dataclass

from shared.camera_secrets import seal, unseal

logger = logging.getLogger(__name__)


@dataclass
class FtpConfig:
    host: str
    port: int = 21
    username: str = ""
    password: str = ""
    passive: bool = True
    tls: bool = False
    delete_after_upload: bool = True

    def public_dict(self) -> dict:
        """Safe-to-echo view (no password) for API responses."""
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "passive": self.passive,
            "tls": self.tls,
            "delete_after_upload": self.delete_after_upload,
        }


def seal_ftp_config(cfg: dict) -> str:
    """Validate + seal an inbound FTP config dict. Raises ValueError on
    missing/invalid fields; the password is never stored in clear."""
    host = str(cfg.get("host") or "").strip()
    if not host:
        raise ValueError("FTP host is required")
    raw_port = cfg.get("port")
    if raw_port in (None, ""):
        raw_port = 21
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        raise ValueError("FTP port must be a number")
    if not (1 <= port <= 65535):
        raise ValueError("FTP port out of range")
    out = {
        "host": host,
        "port": port,
        "username": str(cfg.get("username") or "").strip(),
        "password": str(cfg.get("password") or ""),
        "passive": bool(cfg.get("passive", True)),
        "tls": bool(cfg.get("tls", False)),
        "delete_after_upload": bool(cfg.get("delete_after_upload", True)),
    }
    return seal(json.dumps(out))


def parse_ftp_config(config_enc: str | None) -> FtpConfig | None:
    """Unseal + parse a profile's config. Returns None when absent or
    unreadable (tolerant fallback matches camera credentials)."""
    if not config_enc:
        return None
    try:
        raw = json.loads(unseal(config_enc) or "{}")
        return FtpConfig(
            host=str(raw.get("host") or ""),
            port=int(raw.get("port") or 21),
            username=str(raw.get("username") or ""),
            password=str(raw.get("password") or ""),
            passive=bool(raw.get("passive", True)),
            tls=bool(raw.get("tls", False)),
            delete_after_upload=bool(raw.get("delete_after_upload", True)),
        )
    except Exception:
        logger.debug("ftp config parse failed", exc_info=True)
        return None


def remote_path_for(root: str, rel_file_path: str) -> str:
    """Remote path for a stored recording: <profile root>/<camera>/<date>/<file>.

    ``rel_file_path`` is the DB-stored (possibly root-prefixed) relative
    path; the same prefix stripping every local resolver uses applies."""
    rel = (rel_file_path or "").replace("\\", "/")
    for prefix in ("./recordings/", "recordings/", "./"):
        if rel.startswith(prefix):
            rel = rel[len(prefix):]
            break
    root = "/" + (root or "").strip().strip("/")
    return posixpath.join(root, rel.lstrip("/"))


# ── FTP operations (blocking ftplib, executor-offloaded at call sites) ──


def _connect(cfg: FtpConfig):
    import ftplib

    if cfg.tls:
        ftp = ftplib.FTP_TLS()  # default verified SSL context
    else:
        ftp = ftplib.FTP()
    ftp.connect(cfg.host, cfg.port, timeout=20)
    ftp.login(cfg.username or "anonymous", cfg.password or "nurby@")
    ftp.set_pasv(cfg.passive)
    if cfg.tls:
        ftp.prot_p()  # secure data connection
    return ftp


def _probe_sync(cfg: FtpConfig, root: str) -> tuple[bool, str]:
    """Connect, login, ensure the remote root exists. Returns (ok, detail)."""
    ftp = None
    try:
        ftp = _connect(cfg)
        _ensure_dir(ftp, root)
        return True, f"Connected to {cfg.host}:{cfg.port}"
    except Exception as exc:
        return False, f"FTP connection failed: {exc}"
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:
                try:
                    ftp.close()
                except Exception:
                    pass


def _ensure_dir(ftp, root: str) -> None:
    """Walk the remote root, creating missing levels (MKD may 550 on an
    existing dir — ignore that specific failure per level)."""
    parts = [p for p in (root or "").split("/") if p]
    path = ""
    for part in parts:
        path += "/" + part
        try:
            ftp.mkd(path)
        except Exception:
            pass  # exists (or unwritable — the upload itself will surface it)
    if parts:
        ftp.cwd(path)


def _upload_sync(cfg: FtpConfig, root: str, local_path: str, remote_path: str) -> tuple[bool, str]:
    """Upload one file (STOR) and verify via SIZE. Creates the root tree."""
    ftp = None
    try:
        ftp = _connect(cfg)
        _ensure_dir(ftp, root)
        remote_dir = posixpath.dirname(remote_path)
        _ensure_dir(ftp, remote_dir)
        with open(local_path, "rb") as f:
            ftp.storbinary(f"STOR {posixpath.basename(remote_path)}", f)
        expected = os.path.getsize(local_path)
        try:
            actual = ftp.size(posixpath.basename(remote_path))
        except Exception:
            actual = None  # SIZE unsupported — accept the STOR ack
        if actual is not None and actual != expected:
            return False, f"size mismatch after upload: local {expected} vs remote {actual}"
        return True, "uploaded"
    except Exception as exc:
        return False, str(exc)
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:
                try:
                    ftp.close()
                except Exception:
                    pass


def _delete_sync(cfg: FtpConfig, remote_path: str) -> tuple[bool, str]:
    ftp = None
    try:
        ftp = _connect(cfg)
        ftp.delete(remote_path)
        return True, "deleted"
    except Exception as exc:
        return False, str(exc)
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:
                try:
                    ftp.close()
                except Exception:
                    pass


def _download_sync(cfg: FtpConfig, remote_path: str, local_path: str) -> tuple[bool, str]:
    ftp = None
    tmp = local_path + f".part{os.getpid()}"
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        ftp = _connect(cfg)
        with open(tmp, "wb") as f:
            ftp.retrbinary(f"RETR {remote_path}", f.write)
        os.replace(tmp, local_path)
        return True, "downloaded"
    except Exception as exc:
        try:
            os.remove(tmp)
        except Exception:
            pass
        return False, str(exc)
    finally:
        if ftp is not None:
            try:
                ftp.quit()
            except Exception:
                try:
                    ftp.close()
                except Exception:
                    pass


# Async wrappers (every caller is async; ftplib is blocking).


async def probe_ftp(cfg: FtpConfig, root: str) -> tuple[bool, str]:
    return await asyncio.to_thread(_probe_sync, cfg, root)


async def ftp_upload(cfg: FtpConfig, root: str, local_path: str, remote_path: str) -> tuple[bool, str]:
    return await asyncio.to_thread(_upload_sync, cfg, root, local_path, remote_path)


async def ftp_delete(cfg: FtpConfig, remote_path: str) -> tuple[bool, str]:
    return await asyncio.to_thread(_delete_sync, cfg, remote_path)


async def ftp_download(cfg: FtpConfig, remote_path: str, local_path: str) -> tuple[bool, str]:
    return await asyncio.to_thread(_download_sync, cfg, remote_path, local_path)


# ── FTP-target resolution (which camera uploads where) ────────────────
#
# Mirrors the local profile-root cache in shared/storage_paths: per-process,
# throttled, invalidated by profile/camera changes.

_ftp_targets: dict[str, tuple[str, str]] = {}  # camera_id -> (profile_id, root)
_ftp_targets_at = 0.0


def invalidate_ftp_targets() -> None:
    global _ftp_targets_at
    _ftp_targets.clear()
    _ftp_targets_at = 0.0


async def remote_target_for(camera_id) -> tuple[str, str] | None:
    """(profile_id, remote root) for a camera with an enabled remote (FTP
    or S3) profile, else None. Cached ~30s like the local resolver."""
    global _ftp_targets, _ftp_targets_at
    key = str(camera_id)
    now = time.monotonic()
    if _ftp_targets_at > 0 and now - _ftp_targets_at < 30:
        return _ftp_targets.get(key)
    _ftp_targets_at = now
    try:
        from sqlalchemy import select

        from shared.database import async_session
        from shared.models import Camera, StorageProfile

        async with async_session() as db:
            rows = await db.execute(
                select(Camera.id, StorageProfile.id, StorageProfile.root)
                .join(StorageProfile, Camera.storage_profile_id == StorageProfile.id)
                .where(StorageProfile.enabled.is_(True))
                .where(StorageProfile.kind.in_(REMOTE_KINDS))
            )
            _ftp_targets = {
                str(cam_id): (str(pid), root) for cam_id, pid, root in rows.all()
            }
    except Exception:
        logger.debug("ftp target load failed", exc_info=True)
    return _ftp_targets.get(key)


# Pre-S3 name, kept for existing imports.
ftp_target_for = remote_target_for


# ── S3-compatible backend (issue #270) ────────────────────────────────
#
# One implementation covers AWS S3, Cloudflare R2, Backblaze B2, Wasabi and
# MinIO (endpoint_url selects the non-AWS ones). Same buffer-then-upload
# contract as FTP: the local copy goes only after a verified PUT. The
# profile ``root`` is the key prefix.

S3_STORAGE_CLASSES = (
    "STANDARD",
    "STANDARD_IA",
    "GLACIER_IR",
    "GLACIER",
    "DEEP_ARCHIVE",
)
# Classes whose objects must be restored before they can be read.
S3_RESTORE_CLASSES = ("GLACIER", "DEEP_ARCHIVE")
# How long a restored archive copy stays readable, and the retrieval tier.
S3_RESTORE_DAYS = 7


class RestorePendingError(Exception):
    """The object sits in an archive class and a restore is in progress.
    Playback should say "try again later", not "missing"."""


@dataclass
class S3Config:
    bucket: str
    access_key_id: str = ""
    secret_access_key: str = ""
    region: str = ""
    endpoint_url: str = ""
    storage_class: str = "STANDARD"
    delete_after_upload: bool = True

    def public_dict(self) -> dict:
        """Safe-to-echo view (no secret) for API responses."""
        return {
            "bucket": self.bucket,
            "access_key_id": self.access_key_id,
            "region": self.region,
            "endpoint_url": self.endpoint_url,
            "storage_class": self.storage_class,
            "delete_after_upload": self.delete_after_upload,
        }

    @property
    def needs_restore(self) -> bool:
        return self.storage_class in S3_RESTORE_CLASSES


def seal_s3_config(cfg: dict) -> str:
    """Validate + seal an inbound S3 config dict. Raises ValueError."""
    bucket = str(cfg.get("bucket") or "").strip()
    if not bucket:
        raise ValueError("S3 bucket is required")
    if "/" in bucket or " " in bucket:
        raise ValueError("S3 bucket is a bucket name, not a path (put folders in the prefix)")
    access_key_id = str(cfg.get("access_key_id") or "").strip()
    secret = str(cfg.get("secret_access_key") or "")
    if not access_key_id or not secret:
        raise ValueError("S3 access key ID and secret access key are required")
    endpoint = str(cfg.get("endpoint_url") or "").strip().rstrip("/")
    if endpoint and not endpoint.startswith(("https://", "http://")):
        raise ValueError("S3 endpoint URL must start with https://")
    storage_class = str(cfg.get("storage_class") or "STANDARD").strip().upper()
    if storage_class not in S3_STORAGE_CLASSES:
        raise ValueError(f"Unknown S3 storage class {storage_class!r}")
    out = {
        "bucket": bucket,
        "access_key_id": access_key_id,
        "secret_access_key": secret,
        "region": str(cfg.get("region") or "").strip(),
        "endpoint_url": endpoint,
        "storage_class": storage_class,
        "delete_after_upload": bool(cfg.get("delete_after_upload", True)),
    }
    return seal(json.dumps(out))


def parse_s3_config(config_enc: str | None) -> S3Config | None:
    if not config_enc:
        return None
    try:
        raw = json.loads(unseal(config_enc) or "{}")
        if not raw.get("bucket"):
            return None
        return S3Config(
            bucket=str(raw["bucket"]),
            access_key_id=str(raw.get("access_key_id") or ""),
            secret_access_key=str(raw.get("secret_access_key") or ""),
            region=str(raw.get("region") or ""),
            endpoint_url=str(raw.get("endpoint_url") or ""),
            storage_class=str(raw.get("storage_class") or "STANDARD"),
            delete_after_upload=bool(raw.get("delete_after_upload", True)),
        )
    except Exception:
        logger.debug("s3 config parse failed", exc_info=True)
        return None


def s3_key(remote_path: str) -> str:
    """S3 keys have no leading slash; remote_path_for produces one."""
    return (remote_path or "").lstrip("/")


def _s3_client(cfg: S3Config):
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        aws_access_key_id=cfg.access_key_id,
        aws_secret_access_key=cfg.secret_access_key,
        region_name=cfg.region or None,
        endpoint_url=cfg.endpoint_url or None,
        config=Config(
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=20,
            read_timeout=120,
        ),
    )


def _s3_error_code(exc: Exception) -> str:
    return str(getattr(exc, "response", {}).get("Error", {}).get("Code", "")) or type(exc).__name__


def _s3_probe_sync(cfg: S3Config, root: str) -> tuple[bool, str]:
    """Verify credentials and write access with a tiny marker object.
    The marker is always STANDARD so the probe never incurs archive-class
    minimum storage charges."""
    try:
        client = _s3_client(cfg)
        key = posixpath.join(s3_key(root), ".nurby-write-test")
        client.put_object(Bucket=cfg.bucket, Key=key, Body=b"ok")
        client.delete_object(Bucket=cfg.bucket, Key=key)
        where = cfg.endpoint_url or f"AWS {cfg.region or 'default region'}"
        return True, f"Connected to bucket {cfg.bucket} ({where})"
    except Exception as exc:
        code = _s3_error_code(exc)
        hints = {
            "NoSuchBucket": "the bucket does not exist (check the name and region)",
            "AccessDenied": "the key cannot write to this bucket (it needs s3:PutObject and s3:DeleteObject)",
            "InvalidAccessKeyId": "the access key ID is not recognised",
            "SignatureDoesNotMatch": "the secret access key is wrong",
            "PermanentRedirect": "the bucket is in a different region",
            "AuthorizationHeaderMalformed": "the region does not match the bucket",
        }
        return False, f"S3 connection failed: {hints.get(code, exc)}"


def _s3_upload_sync(cfg: S3Config, local_path: str, remote_path: str) -> tuple[bool, str]:
    """Upload one file (multipart above 8 MB via upload_file) and verify
    the stored size."""
    try:
        client = _s3_client(cfg)
        key = s3_key(remote_path)
        extra = {"ContentType": "video/mp4"}
        if cfg.storage_class and cfg.storage_class != "STANDARD":
            extra["StorageClass"] = cfg.storage_class
        client.upload_file(local_path, cfg.bucket, key, ExtraArgs=extra)
        expected = os.path.getsize(local_path)
        actual = client.head_object(Bucket=cfg.bucket, Key=key).get("ContentLength")
        if actual is not None and int(actual) != expected:
            return False, f"size mismatch after upload: local {expected} vs remote {actual}"
        return True, "uploaded"
    except Exception as exc:
        return False, f"{_s3_error_code(exc)}: {exc}"


def _s3_delete_sync(cfg: S3Config, remote_path: str) -> tuple[bool, str]:
    try:
        _s3_client(cfg).delete_object(Bucket=cfg.bucket, Key=s3_key(remote_path))
        return True, "deleted"
    except Exception as exc:
        return False, f"{_s3_error_code(exc)}: {exc}"


def _s3_download_sync(cfg: S3Config, remote_path: str, local_path: str) -> tuple[bool, str]:
    """Download into ``local_path``. Raises RestorePendingError for an archived
    object, after requesting a restore if none is running yet."""
    client = _s3_client(cfg)
    key = s3_key(remote_path)
    tmp = local_path + f".part{os.getpid()}"
    try:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        client.download_file(cfg.bucket, key, tmp)
        os.replace(tmp, local_path)
        return True, "downloaded"
    except Exception as exc:
        try:
            os.remove(tmp)
        except Exception:
            pass
        code = _s3_error_code(exc)
        if code in ("InvalidObjectState", "403") or cfg.needs_restore:
            restoring = _s3_request_restore(client, cfg.bucket, key)
            if restoring is not None:
                raise RestorePendingError(restoring) from exc
        return False, f"{code}: {exc}"


def _s3_request_restore(client, bucket: str, key: str) -> str | None:
    """Start (or report) a restore for an archived object. Returns a
    user-facing message, or None when the object is not archived."""
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except Exception:
        return None
    klass = head.get("StorageClass") or "STANDARD"
    if klass not in S3_RESTORE_CLASSES:
        return None
    eta = "up to 12 hours" if klass == "DEEP_ARCHIVE" else "3 to 5 hours"
    if 'ongoing-request="true"' in (head.get("Restore") or ""):
        return f"This recording is in {klass} cold storage and is being restored. Try again in {eta}."
    try:
        client.restore_object(
            Bucket=bucket,
            Key=key,
            RestoreRequest={"Days": S3_RESTORE_DAYS, "GlacierJobParameters": {"Tier": "Standard"}},
        )
    except Exception as exc:
        if _s3_error_code(exc) != "RestoreAlreadyInProgress":
            logger.warning("S3 restore request failed for %s: %s", key, exc)
            return None
    return f"This recording is in {klass} cold storage. A restore has been requested. Try again in {eta}."


# ── Kind dispatch: one surface for the upload worker, playback, retention ──

REMOTE_KINDS = ("ftp", "s3")


def parse_remote_config(kind: str, config_enc: str | None):
    if kind == "ftp":
        return parse_ftp_config(config_enc)
    if kind == "s3":
        return parse_s3_config(config_enc)
    return None


def seal_remote_config(kind: str, cfg: dict) -> str:
    if kind == "ftp":
        return seal_ftp_config(cfg)
    if kind == "s3":
        return seal_s3_config(cfg)
    raise ValueError(f"{kind!r} is not a remote storage kind")


async def remote_probe(kind: str, cfg, root: str) -> tuple[bool, str]:
    if kind == "s3":
        return await asyncio.to_thread(_s3_probe_sync, cfg, root)
    return await probe_ftp(cfg, root)


async def remote_upload(kind: str, cfg, root: str, local_path: str, remote_path: str) -> tuple[bool, str]:
    if kind == "s3":
        return await asyncio.to_thread(_s3_upload_sync, cfg, local_path, remote_path)
    return await ftp_upload(cfg, root, local_path, remote_path)


async def remote_download(kind: str, cfg, remote_path: str, local_path: str) -> tuple[bool, str]:
    """Raises RestorePendingError for an S3 archive-class object."""
    if kind == "s3":
        return await asyncio.to_thread(_s3_download_sync, cfg, remote_path, local_path)
    return await ftp_download(cfg, remote_path, local_path)


async def remote_delete(kind: str, cfg, remote_path: str) -> tuple[bool, str]:
    if kind == "s3":
        return await asyncio.to_thread(_s3_delete_sync, cfg, remote_path)
    return await ftp_delete(cfg, remote_path)


def kind_label(kind: str | None) -> str:
    return {"ftp": "FTP", "s3": "S3"}.get(kind or "", kind or "remote")
