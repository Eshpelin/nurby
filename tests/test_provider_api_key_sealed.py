"""Provider.api_key is Fernet-sealed at rest (#330).

Constructing or assigning a plaintext key stores a gAAAA token in
api_key_enc; reading .api_key unseals transparently (the ~30 reader
call sites are unchanged); None round-trips; legacy plaintext column
values still read back as stored, so a mid-fleet upgrade keeps working
(same contract as camera credentials).
"""

from __future__ import annotations

from shared.models import Provider


def _provider(**kw) -> Provider:
    base = {"name": "p", "kind": "openai", "base_url": "https://api.example.com"}
    base.update(kw)
    return Provider(**base)


def test_plaintext_assignment_seals_at_rest():
    p = _provider(api_key="sk-test-123")
    assert p.api_key_enc is not None
    assert p.api_key_enc.startswith("gAAAA"), "stored value must be a Fernet token"
    assert p.api_key_enc != "sk-test-123", "plaintext must not sit in the column"
    assert p.api_key == "sk-test-123", "reading unseals transparently"


def test_none_round_trips():
    p = _provider(api_key=None)
    assert p.api_key is None
    p.api_key = "sk-x"
    assert p.api_key == "sk-x"
    p.api_key = None
    assert p.api_key is None and p.api_key_enc is None


def test_legacy_plaintext_column_value_still_reads():
    # A row written before sealing (or after a jwt_secret rotation, which
    # makes old tokens undecryptable) reads back as stored — unseal passes
    # unknown formats through rather than raising.
    p = _provider()
    p.api_key_enc = "legacy-plaintext-key"
    assert p.api_key == "legacy-plaintext-key"
