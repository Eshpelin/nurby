"""Camera credential sealing coverage."""

from shared.camera_secrets import seal, unseal


def test_roundtrip():
    sealed = seal("rtsp-password-123")
    assert sealed != "rtsp-password-123"
    assert sealed.startswith("gAAAA")
    assert unseal(sealed) == "rtsp-password-123"


def test_none_and_empty_pass_through():
    assert seal(None) is None
    assert seal("") == ""
    assert unseal(None) is None
    assert unseal("") == ""


def test_legacy_plaintext_passes_through():
    # Rows written before the migration are returned as stored, so the
    # camera connection still gets a usable value mid-upgrade.
    assert unseal("plain-old-password") == "plain-old-password"


def test_double_seal_detectable():
    # Migration guards on the gAAAA prefix; confirm the prefix survives.
    sealed = seal("x")
    assert sealed.startswith("gAAAA")
    assert not "x".startswith("gAAAA")


def test_long_credential_fits_column():
    # auth tokens can be 512 chars; sealed form must fit String(2048).
    sealed = seal("t" * 512)
    assert len(sealed) <= 2048
    assert unseal(sealed) == "t" * 512
