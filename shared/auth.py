import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import bcrypt
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import settings
from shared.database import get_db
from shared.models import ApiKey, User, UserCameraAccess

bearer_scheme = HTTPBearer()

ALGORITHM = "HS256"

# Programmatic API keys are issued as ``nrb_<urlsafe-random>``. The
# plaintext is shown once; only its sha256 is stored.
API_KEY_PREFIX = "nrb_"


def generate_api_key() -> tuple[str, str, str]:
    """Mint a new API key. Returns (plaintext, sha256_hex, display_prefix).

    The plaintext is returned to the caller exactly once and never
    persisted. Store the hash; show the prefix in listings.
    """
    plaintext = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return plaintext, hash_api_key(plaintext), plaintext[:12]


def hash_api_key(plaintext: str) -> str:
    """sha256 hex of a plaintext key. The key is high-entropy random, so
    a fast hash is safe here (no brute-force surface like a password)."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def _user_from_api_key(token: str, db: AsyncSession) -> User | None:
    """Resolve a ``nrb_`` token to its owning user, or None when the key
    is unknown, revoked, or expired. Stamps last_used_at best-effort."""
    key_hash = hash_api_key(token)
    row = (
        await db.execute(select(ApiKey).where(ApiKey.key_hash == key_hash))
    ).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    now = datetime.now(timezone.utc)
    if row.expires_at is not None and row.expires_at <= now:
        return None
    user = await db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    # Throttle the write. only stamp when stale by > 60s.
    if row.last_used_at is None or (now - row.last_used_at).total_seconds() > 60:
        try:
            row.last_used_at = now
            await db.commit()
        except Exception:
            await db.rollback()
    return user


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: uuid.UUID) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expiry_hours)
    payload = {
        "sub": str(user_id),
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> uuid.UUID | None:
    """Decode a JWT and return the user UUID, or None if invalid."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if sub is None:
            return None
        return uuid.UUID(sub)
    except (JWTError, ValueError):
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """FastAPI dependency that extracts and validates the current user.

    Accepts either a user JWT or a programmatic API key (``nrb_`` prefix)
    in the Authorization: Bearer header, so scripts and integrations can
    authenticate without a login round-trip.
    """
    token = credentials.credentials

    if token.startswith(API_KEY_PREFIX):
        user = await _user_from_api_key(token, db)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid, revoked, or expired API key",
            )
        return user

    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )
    return user


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """FastAPI dependency that ensures the current user has admin role."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


def require_camera_access(camera_id_param: str = "camera_id"):
    """Factory that returns a FastAPI dependency checking camera access for the current user.

    Admins always have access. Viewers must have an explicit UserCameraAccess row.
    """

    async def _check(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        **kwargs,
    ) -> User:
        # Admins bypass per-camera checks
        if current_user.role == "admin":
            return current_user

        # Extract camera_id from path params via the request
        from fastapi import Request

        request = kwargs.get("request")
        if request is None:
            raise HTTPException(status_code=500, detail="Cannot resolve camera_id")

        camera_id_str = request.path_params.get(camera_id_param)
        if camera_id_str is None:
            raise HTTPException(status_code=400, detail="Missing camera_id")

        try:
            camera_id = uuid.UUID(camera_id_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid camera_id format")

        result = await db.execute(
            select(UserCameraAccess).where(
                UserCameraAccess.user_id == current_user.id,
                UserCameraAccess.camera_id == camera_id,
            )
        )
        if result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No access to this camera",
            )
        return current_user

    return _check
