"""safe_getsize: TOCTOU-free, transient-error-tolerant file size.

Mirrors Frigate PR #23172 (gracefully handle transiently failing stat calls).
"""

import os

from shared.paths import safe_getsize


def test_real_file_returns_size(tmp_path):
    p = tmp_path / "f.bin"
    p.write_bytes(b"x" * 1234)
    assert safe_getsize(str(p)) == 1234
    assert safe_getsize(p) == 1234  # PathLike


def test_missing_file_returns_zero(tmp_path):
    assert safe_getsize(str(tmp_path / "nope.bin")) == 0


def test_none_and_empty_return_zero():
    assert safe_getsize(None) == 0
    assert safe_getsize("") == 0


def test_directory_returns_size_not_crash(tmp_path):
    # getsize on a dir succeeds on POSIX; the point is it must not raise.
    assert isinstance(safe_getsize(str(tmp_path)), int)


def test_zero_byte_file(tmp_path):
    p = tmp_path / "empty.bin"
    p.touch()
    assert safe_getsize(str(p)) == 0
