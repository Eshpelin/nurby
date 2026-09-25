from pathlib import Path

import pytest

from services.backup import BackupError, _crypt_file


def test_encrypted_backup_round_trip(tmp_path: Path):
    source = tmp_path / "source.tar"
    source.write_bytes((b"nurby backup payload\n" * 10000) + b"end")
    encrypted = tmp_path / "backup.nurby"
    restored = tmp_path / "restored.tar"

    _crypt_file(source, encrypted, "correct horse battery staple")
    _crypt_file(encrypted, restored, "correct horse battery staple", decrypt=True)

    assert restored.read_bytes() == source.read_bytes()


def test_encrypted_backup_rejects_wrong_passphrase(tmp_path: Path):
    source = tmp_path / "source.tar"
    source.write_bytes(b"private Nurby data")
    encrypted = tmp_path / "backup.nurby"
    restored = tmp_path / "restored.tar"
    _crypt_file(source, encrypted, "correct horse battery staple")

    with pytest.raises(BackupError, match="wrong or the archive is corrupted"):
        _crypt_file(encrypted, restored, "wrong passphrase", decrypt=True)
