"""Camera credential sealing.

Camera passwords and auth tokens are needed in plaintext at connect time
(RTSP URLs, HTTP basic auth, bearer tokens), so they cannot be hashed,
but they should not sit readable in every database backup either. They
are sealed with the same Fernet cipher used for Telegram bot tokens
(shared/crypto, keyed off jwt_secret).

``unseal`` tolerates legacy plaintext rows: anything that does not parse
as a Fernet token is returned as-is, so a deploy upgraded mid-fleet keeps
connecting while the migration converts old rows.
"""

from shared.crypto import InvalidToken, decrypt_secret, encrypt_secret

__all__ = ["seal", "unseal"]

# Every Fernet token is version byte 0x80 b64url-encoded, so this prefix.
_FERNET_PREFIX = "gAAAA"


def seal(value: str | None) -> str | None:
    """Encrypt a credential for storage. None/empty passes through."""
    if not value:
        return value
    return encrypt_secret(value).decode("utf-8")


def unseal(value: str | None) -> str | None:
    """Decrypt a stored credential. Legacy plaintext rows (or rows written
    after a jwt_secret rotation, which makes old tokens undecryptable)
    are returned as stored so the camera connection still gets a value."""
    if not value or not value.startswith(_FERNET_PREFIX):
        return value
    try:
        return decrypt_secret(value.encode("utf-8"))
    except (InvalidToken, ValueError):
        return value
