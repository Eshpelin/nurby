"""Native FTP storage backend (issue #269).

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


async def ftp_target_for(camera_id) -> tuple[str, str] | None:
    """(profile_id, remote root) for a camera with an enabled FTP profile,
    else None. Cached ~30s like the local resolver."""
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
                .where(StorageProfile.kind == "ftp")
            )
            _ftp_targets = {
                str(cam_id): (str(pid), root) for cam_id, pid, root in rows.all()
            }
    except Exception:
        logger.debug("ftp target load failed", exc_info=True)
    return _ftp_targets.get(key)
