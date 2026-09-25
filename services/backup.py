"""Encrypted, self-contained Nurby backup archives.

The archive deliberately keeps the database as a PostgreSQL dump: that is the
only reliable way to preserve every relationship, vector, extension and
future table without maintaining a second serialization format. The outer
archive is encrypted with a passphrase chosen by the operator.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from shared.config import settings

MAGIC = b"NURBYBK1"
FORMAT_VERSION = 1
SALT_BYTES = 16
NONCE_BYTES = 16
KEY_BYTES = 64
CHUNK_SIZE = 1024 * 1024


class BackupError(RuntimeError):
    """An operator-actionable backup or restore failure."""


def _derive_keys(passphrase: str, salt: bytes) -> tuple[bytes, bytes]:
    if len(passphrase) < 8:
        raise BackupError("Backup passphrase must be at least 8 characters")
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=KEY_BYTES, salt=salt, iterations=600_000).derive(
        passphrase.encode("utf-8")
    )
    return key[:32], key[32:]


def _crypt_file(source: Path, destination: Path, passphrase: str, decrypt: bool = False) -> None:
    if decrypt:
        with source.open("rb") as src:
            header = src.read(len(MAGIC) + SALT_BYTES + NONCE_BYTES)
            if len(header) != len(MAGIC) + SALT_BYTES + NONCE_BYTES or not header.startswith(MAGIC):
                raise BackupError("Not a Nurby backup archive or unsupported archive version")
            salt = header[len(MAGIC):len(MAGIC) + SALT_BYTES]
            nonce = header[-NONCE_BYTES:]
            enc_key, mac_key = _derive_keys(passphrase, salt)
            decryptor = Cipher(algorithms.AES(enc_key), modes.CTR(nonce)).decryptor()
            mac = hmac.new(mac_key, header, hashlib.sha256)
            remaining = source.stat().st_size - len(header) - 32
            if remaining < 0:
                raise BackupError("Backup archive is truncated")
            with destination.open("wb") as dst:
                while remaining:
                    chunk = src.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise BackupError("Backup archive is truncated")
                    remaining -= len(chunk)
                    mac.update(chunk)
                    dst.write(decryptor.update(chunk))
                tag = src.read(32)
                dst.write(decryptor.finalize())
            if not hmac.compare_digest(mac.digest(), tag):
                destination.unlink(missing_ok=True)
                raise BackupError("Backup passphrase is wrong or the archive is corrupted")
        return

    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    enc_key, mac_key = _derive_keys(passphrase, salt)
    header = MAGIC + salt + nonce
    encryptor = Cipher(algorithms.AES(enc_key), modes.CTR(nonce)).encryptor()
    mac = hmac.new(mac_key, header, hashlib.sha256)
    with source.open("rb") as src, destination.open("wb") as dst:
        dst.write(header)
        while chunk := src.read(CHUNK_SIZE):
            encrypted = encryptor.update(chunk)
            mac.update(encrypted)
            dst.write(encrypted)
        dst.write(encryptor.finalize())
        dst.write(mac.digest())


def _pg_env() -> tuple[str, dict[str, str]]:
    parsed = urlsplit(settings.database_url.replace("+asyncpg", ""))
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise BackupError("Backups currently require a PostgreSQL database")
    db_url = f"postgresql://{parsed.hostname or ''}"
    if parsed.port:
        db_url += f":{parsed.port}"
    db_url += parsed.path or "/nurby"
    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    if parsed.username:
        db_url = db_url.replace("postgresql://", f"postgresql://{unquote(parsed.username)}@", 1)
    return db_url, env


def _run_pg(command: list[str], env: dict[str, str]) -> None:
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=600)
    except FileNotFoundError as exc:
        raise BackupError("pg_dump/pg_restore is not installed; install the PostgreSQL client tools") from exc
    except subprocess.TimeoutExpired as exc:
        raise BackupError("PostgreSQL backup operation timed out") from exc
    if result.returncode:
        raise BackupError((result.stderr or result.stdout or "PostgreSQL backup operation failed").strip()[-1000:])


def create_backup(
    passphrase: str,
    output_path: str | Path | None = None,
    include_recordings: bool = False,
) -> Path:
    """Create an encrypted backup and return its path."""
    out_dir = Path(settings.backup_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    output = Path(output_path) if output_path else out_dir / f"nurby-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.nurby"
    output.parent.mkdir(parents=True, exist_ok=True)
    db_url, env = _pg_env()

    with tempfile.TemporaryDirectory(prefix="nurby-backup-") as tmp:
        root = Path(tmp) / "archive"
        root.mkdir()
        dump = root / "database.dump"
        _run_pg(["pg_dump", "--format=custom", "--no-owner", "--file", str(dump), db_url], env)
        metadata = {
            "format_version": FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "include_recordings": include_recordings,
            # Stored only inside the passphrase-encrypted archive. Keeping the
            # JWT secret is necessary for sealed camera/channel credentials to
            # remain decryptable after restore on a new host.
            "jwt_secret": settings.jwt_secret,
        }
        (root / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        if Path(settings.thumbnails_path).is_dir():
            shutil.copytree(settings.thumbnails_path, root / "thumbnails")
        if include_recordings and Path(settings.recordings_path).is_dir():
            shutil.copytree(settings.recordings_path, root / "recordings")
        plain = Path(tmp) / "archive.tar"
        with tarfile.open(plain, "w") as tar:
            tar.add(root, arcname="nurby")
        _crypt_file(plain, output, passphrase)

    marker = output.parent / ".nurby-backup-status.json"
    marker.write_text(
        json.dumps({"last_success_at": datetime.now(timezone.utc).isoformat(), "archive": output.name}),
        encoding="utf-8",
    )
    return output


def backup_status() -> dict[str, str | None]:
    marker = Path(settings.backup_path) / ".nurby-backup-status.json"
    if not marker.exists():
        return {"last_success_at": None, "archive": None}
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        return {"last_success_at": data.get("last_success_at"), "archive": data.get("archive")}
    except (OSError, ValueError):
        return {"last_success_at": None, "archive": None}


def restore_backup(archive_path: str | Path, passphrase: str, env_file: str | Path | None = None) -> dict[str, str]:
    """Restore a backup into the configured database and media roots."""
    archive = Path(archive_path)
    if not archive.is_file():
        raise BackupError(f"Backup archive not found: {archive}")
    db_url, env = _pg_env()
    with tempfile.TemporaryDirectory(prefix="nurby-restore-") as tmp:
        plain = Path(tmp) / "archive.tar"
        _crypt_file(archive, plain, passphrase, decrypt=True)
        extract = Path(tmp) / "extract"
        with tarfile.open(plain, "r") as tar:
            for member in tar.getmembers():
                target = (extract / member.name).resolve()
                if not str(target).startswith(str(extract.resolve()) + os.sep):
                    raise BackupError("Backup contains an unsafe path")
            tar.extractall(extract)
        root = extract / "nurby"
        metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
        if metadata.get("format_version") != FORMAT_VERSION:
            raise BackupError("Unsupported Nurby backup format")
        _run_pg(
            ["pg_restore", "--clean", "--if-exists", "--no-owner", "--dbname", db_url, str(root / "database.dump")],
            env,
        )
        for name, target in (("thumbnails", settings.thumbnails_path), ("recordings", settings.recordings_path)):
            source = root / name
            if source.is_dir():
                Path(target).mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, target, dirs_exist_ok=True)
        if env_file:
            path = Path(env_file)
            lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
            lines = [line for line in lines if not line.startswith("JWT_SECRET=")]
            lines.append(f"JWT_SECRET={metadata['jwt_secret']}")
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"created_at": str(metadata["created_at"]), "jwt_secret_restored": "true"}
