import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.activation import (
    DELIVERY_ACTIONS,
    ActivationList,
    ActivationView,
    ConfigureRequest,
    ConfirmRequest,
    DraftRuleRequest,
    compute_activation,
    starter_key_for_goal,
)
from shared.daily_workflow import Capabilities, DailyWorkflow, daily_workflow
from shared.onboarding_metrics import (
    MilestoneRow,
    OnboardingMetrics,
    PreferenceRow,
    compute_metrics,
)
from shared.auth import (
    MOBILE_PAIR_TTL_SECONDS,
    create_access_token,
    create_mobile_pair_code,
    decode_mobile_pair_code,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)
from shared.config import settings
from shared.database import get_db
from shared.models import ActivationMilestone, Camera, InviteKey, Rule, User, UserCameraAccess
from shared.onboarding import ExperiencePreferences, ExperienceResponse, experience_response
from shared.rule_starters import starter_rule
from shared.schemas import (
    AccountClaim,
    AdminSetup,
    PairClaim,
    PairStartResponse,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)

router = APIRouter()


@router.get("/needs-setup")
async def needs_setup(db: AsyncSession = Depends(get_db)):
    """Public. Returns whether the instance has zero users yet.

    A brand-new install has no admin account, so the frontend should
    route a tokenless visitor to /setup instead of /login. Without this
    the user lands on a sign-in form for an account that does not exist
    and has to notice the small "First time?" link.
    """
    users = (await db.execute(select(User))).scalars().all()
    # provisional_open. the only account(s) are unclaimed provisional
    # owners, so a tokenless visitor can re-adopt the session via
    # /auth/bootstrap rather than being stranded at /login (cleared
    # cookies, new browser). False once any account is claimed.
    provisional_open = len(users) > 0 and all(u.is_provisional for u in users)
    return {"needs_setup": len(users) == 0, "provisional_open": provisional_open}


@router.post("/setup", response_model=TokenResponse, status_code=201)
async def initial_admin_setup(body: AdminSetup, db: AsyncSession = Depends(get_db)):
    """Create the first admin account. Only works when no users exist in the system."""
    count_result = await db.execute(select(func.count()).select_from(User))
    user_count = count_result.scalar()
    if user_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Setup already completed. An admin account exists.",
        )

    user = User(
        email=body.email,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        role="admin",
        camera_access_mode="all",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/bootstrap", response_model=TokenResponse, status_code=201)
async def bootstrap(db: AsyncSession = Depends(get_db)):
    """Drop a brand-new install straight in.

    On first run (no users) this auto-creates a provisional owner account
    and returns a login token, so a first-time user never hits a signup
    wall. The account is flagged ``is_provisional`` until the user claims
    it (sets a real email + password) via ``/auth/claim``.

    Re-adoptable while unclaimed. if the only account is an unclaimed
    provisional owner, a fresh visitor (no token. cleared cookies, new
    browser) gets a session for that same owner instead of being locked
    out. Once the account is claimed (real credentials), this returns 409
    and the caller falls back to the login screen.
    """
    # Serialize concurrent first-run requests. Without this, two tabs or a
    # double-fired client effect could both pass the count check and create
    # two owners. The lock is transaction-scoped and released on commit.
    await db.execute(text("SELECT pg_advisory_xact_lock(481566)"))

    users = (await db.execute(select(User))).scalars().all()
    if users:
        # Any claimed (real) account means setup is done. require login.
        if any(not u.is_provisional for u in users):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Setup already completed. An account exists.",
            )
        # Only an unclaimed provisional owner exists. re-adopt it so a
        # visitor who lost their token can still get into their own
        # not-yet-secured install rather than being stranded at /login.
        owner = min(users, key=lambda u: u.created_at)
        token = create_access_token(owner.id)
        return TokenResponse(
            access_token=token, user=UserResponse.model_validate(owner)
        )

    # Random, unusable-by-design credentials. The user never sees these.
    # they exist only so the row is valid until the account is claimed.
    placeholder_email = f"owner+{secrets.token_hex(6)}@nurby.local"
    user = User(
        email=placeholder_email,
        display_name="Owner",
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role="admin",
        camera_access_mode="all",
        is_active=True,
        is_provisional=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/claim", response_model=UserResponse)
async def claim_account(
    body: AccountClaim,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Secure a provisional owner account.

    Sets the real email + password and clears the provisional flag. Also
    works for an already-real account as a credential update. Rejects an
    email already taken by a different user.
    """
    existing = await db.execute(
        select(User).where(User.email == body.email, User.id != current_user.id)
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    current_user.email = body.email
    if body.display_name:
        current_user.display_name = body.display_name
    current_user.password_hash = hash_password(body.password)
    current_user.is_provisional = False
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user with an invite key."""
    # Validate invite key
    result = await db.execute(select(InviteKey).where(InviteKey.key == body.invite_key))
    invite = result.scalar_one_or_none()
    if invite is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid invite key",
        )

    # Check expiry
    if invite.expires_at is not None:
        now = datetime.now(timezone.utc)
        if invite.expires_at < now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invite key has expired",
            )

    # Check usage limit
    if invite.use_count >= invite.max_uses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invite key has reached its usage limit",
        )

    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    # Create user with the role specified in the invite
    user = User(
        email=body.email,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        role=invite.role,
        camera_access_mode="selected" if invite.camera_ids else "none",
        is_active=True,
        invite_key_id=invite.id,
    )
    db.add(user)

    # Increment invite usage
    invite.use_count += 1

    await db.flush()

    # Auto-grant camera access from invite
    if invite.camera_ids:
        for cam_id_str in invite.camera_ids:
            access = UserCameraAccess(
                user_id=user.id,
                camera_id=cam_id_str if not isinstance(cam_id_str, str) else cam_id_str,
                granted_by_id=invite.created_by_id,
            )
            db.add(access)

    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(body: UserLogin, db: AsyncSession = Depends(get_db)):
    """Authenticate with email and password, returns a JWT."""
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    # Update last login timestamp
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user's profile."""
    return current_user


@router.get("/me/experience", response_model=ExperienceResponse)
async def get_experience(current_user: User = Depends(get_current_user)):
    """Personal defaults, independent of installation-wide wizard dismissal."""
    return experience_response(current_user)


@router.put("/me/experience", response_model=ExperienceResponse)
async def save_experience(
    body: ExperiencePreferences,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # There is deliberately no target user ID and no role/grant field.
    if current_user.role != "admin" and (
        body.place is not None or body.focus != "daily" or body.goal not in {"review", "explore"}
    ):
        raise HTTPException(status_code=403, detail="Your account can personalize its review experience only")
    current_user.onboarding_preferences = body.model_dump()
    await db.commit()
    return experience_response(current_user)


# ── Verified first useful result (#193 / #204 phase 2) ───────────────
#
# Activation is installation work, so these endpoints are admin-only.
# Saving a preference or scaffolding a draft never claims activation:
# only a real, delivered event the person confirmed marks it verified.


def _milestone_view(m: ActivationMilestone) -> ActivationView:
    return compute_activation(
        goal=m.goal,
        rule_id=str(m.rule_id) if m.rule_id else None,
        camera_id=str(m.camera_id) if m.camera_id else None,
        draft_rule_id=str(m.draft_rule_id) if m.draft_rule_id else None,
        configured_at=m.configured_at,
        tested_at=m.tested_at,
        confirmed_useful_at=m.confirmed_useful_at,
        test_kind=m.test_kind,
        delivery_ok=m.delivery_ok,
        install_ready_at=m.install_ready_at,
    )


async def _get_milestone(db: AsyncSession, user: User, goal: str) -> ActivationMilestone | None:
    result = await db.execute(
        select(ActivationMilestone).where(
            ActivationMilestone.user_id == user.id, ActivationMilestone.goal == goal
        )
    )
    return result.scalar_one_or_none()


@router.get("/me/activation", response_model=ActivationList)
async def list_activation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every activation milestone this user is pursuing, resumable across
    sessions and devices."""
    result = await db.execute(
        select(ActivationMilestone).where(ActivationMilestone.user_id == current_user.id)
    )
    return ActivationList(milestones=[_milestone_view(m) for m in result.scalars().all()])


@router.post("/me/activation/draft-rule", response_model=ActivationView)
async def scaffold_draft_rule(
    body: DraftRuleRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Scaffold a DISABLED draft rule for a goal. The user reviews and
    enables it; it never fires until they do."""
    key = starter_key_for_goal(body.goal)
    if key is None:
        raise HTTPException(status_code=400, detail=f"Goal {body.goal!r} has no rule to scaffold")
    payload = starter_rule(key, body.camera_id)
    if payload is None:  # pragma: no cover - map and starters kept in sync
        raise HTTPException(status_code=404, detail=f"Unknown starter for goal {body.goal!r}")
    # The whole point: created off, so a saved preference never arms a rule.
    payload["enabled"] = False
    rule = Rule(**payload)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)

    milestone = await _get_milestone(db, current_user, body.goal)
    now = datetime.now(timezone.utc)
    if milestone is None:
        milestone = ActivationMilestone(user_id=current_user.id, goal=body.goal, install_ready_at=now)
        db.add(milestone)
    milestone.draft_rule_id = rule.id
    milestone.rule_id = rule.id
    milestone.camera_id = uuid_or_none(body.camera_id)
    if milestone.install_ready_at is None:
        milestone.install_ready_at = now
    await db.commit()
    await db.refresh(milestone)
    return _milestone_view(milestone)


@router.post("/me/activation/configure", response_model=ActivationView)
async def mark_configured(
    body: ConfigureRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Record that a real rule is configured: enabled, on a camera, with a
    delivery action. This alone is never verified activation."""
    if starter_key_for_goal(body.goal) is None:
        raise HTTPException(status_code=400, detail=f"Goal {body.goal!r} has no activation to configure")
    rule = await db.get(Rule, uuid_or_none(body.rule_id))
    if rule is None:
        raise HTTPException(status_code=404, detail="Rule not found")
    if not rule.enabled:
        raise HTTPException(status_code=409, detail="Enable the rule before it can be configured")
    trigger = rule.trigger_pattern or {}
    camera_id = trigger.get("camera_id")
    if not camera_id:
        raise HTTPException(status_code=409, detail="Point the rule at a camera before configuring")
    actions = rule.actions or []
    if not any(isinstance(a, dict) and a.get("type") in DELIVERY_ACTIONS for a in actions):
        raise HTTPException(status_code=409, detail="Add a delivery action so the alert can reach you")

    milestone = await _get_milestone(db, current_user, body.goal)
    now = datetime.now(timezone.utc)
    if milestone is None:
        milestone = ActivationMilestone(user_id=current_user.id, goal=body.goal, install_ready_at=now)
        db.add(milestone)
    milestone.rule_id = rule.id
    milestone.camera_id = uuid_or_none(camera_id)
    if milestone.configured_at is None:
        milestone.configured_at = now
    if milestone.install_ready_at is None:
        milestone.install_ready_at = now
    await db.commit()
    await db.refresh(milestone)
    return _milestone_view(milestone)


@router.post("/me/activation/confirm", response_model=ActivationView)
async def confirm_useful(
    body: ConfirmRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """The person confirms they opened the exact clip and it was useful.

    Requires a delivered test event first: confirmation without a real
    delivery cannot stand in for verified activation.
    """
    milestone = await _get_milestone(db, current_user, body.goal)
    if milestone is None:
        raise HTTPException(status_code=404, detail="Nothing to confirm for this goal yet")
    if milestone.tested_at is None or milestone.delivery_ok is not True:
        raise HTTPException(status_code=409, detail="No delivered test event yet. Trigger the camera and wait for the alert")
    milestone.confirmed_useful_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(milestone)
    return _milestone_view(milestone)


def uuid_or_none(value):
    import uuid as _uuid

    if value is None or isinstance(value, _uuid.UUID):
        return value
    try:
        return _uuid.UUID(str(value))
    except (ValueError, AttributeError):
        return None


# ── Daily workflow priorities (#204 phase 3) ─────────────────────────


async def _account_capabilities(db: AsyncSession, user: User) -> Capabilities:
    """What the account can actually do today. Read-only; drives which
    daily priorities are recommended vs shown as blocked."""
    from services.api.routes.cameras import resolve_demo_video_url
    from shared.email import resolve_smtp
    from shared.models import (
        ActivationMilestone as _AM,
        Camera as _Camera,
        Provider,
        PushDevice,
        Rule as _Rule,
        TelegramChannel,
        WebhookSubscription,
    )

    cameras = (await db.execute(select(_Camera.stream_type, _Camera.stream_url))).all()
    demo_url = resolve_demo_video_url()
    has_real_camera = any(not (c.stream_type == "file" and c.stream_url == demo_url) for c in cameras)

    has_provider = bool(await db.scalar(
        select(func.count()).select_from(Provider).where(Provider.active.is_(True))
    ))
    has_enabled_rule = bool(await db.scalar(
        select(func.count()).select_from(_Rule).where(_Rule.enabled.is_(True))
    ))

    telegram = await db.scalar(select(func.count()).select_from(TelegramChannel).where(TelegramChannel.enabled.is_(True)))
    webhook = await db.scalar(select(func.count()).select_from(WebhookSubscription))
    push = await db.scalar(select(func.count()).select_from(PushDevice))
    smtp_cfg = await resolve_smtp()
    has_channel = bool(telegram or webhook or push or (smtp_cfg.get("host") and smtp_cfg.get("from_addr")))

    verified = bool(await db.scalar(
        select(func.count()).select_from(_AM).where(
            _AM.user_id == user.id,
            _AM.test_kind == "real",
            _AM.delivery_ok.is_(True),
            _AM.confirmed_useful_at.isnot(None),
        )
    ))
    return Capabilities(
        has_real_camera=has_real_camera,
        has_provider=has_provider,
        has_channel=has_channel,
        has_enabled_rule=has_enabled_rule,
        verified=verified,
    )


@router.get("/me/daily", response_model=DailyWorkflow)
async def get_daily_workflow(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """The person's ordered daily priorities for their audience and goal,
    capability-aware. Read-only: never creates or rewrites a rule."""
    resp = experience_response(current_user)
    prefs = resp.preferences
    caps = await _account_capabilities(db, current_user)
    return daily_workflow(
        audience=resp.audience,
        goal=prefs.goal if prefs else None,
        focus=prefs.focus if prefs else "daily",
        paused=bool(prefs.paused) if prefs else False,
        place_label=prefs.place_label if prefs else None,
        caps=caps,
    )


# ── Onboarding validation metrics (#204 phase 4) ─────────────────────


@router.get("/onboarding/metrics", response_model=OnboardingMetrics)
async def onboarding_metrics(
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Install-wide, aggregate onboarding outcomes. Admin-only, no PII: only
    counts, a verified-activation rate and the median time to first useful
    result."""
    pref_rows = (
        await db.execute(select(User.onboarding_preferences).where(User.onboarding_preferences.isnot(None)))
    ).scalars().all()
    preferences = [
        PreferenceRow(
            goal=(p or {}).get("goal"),
            place=(p or {}).get("place"),
            focus=(p or {}).get("focus", "daily"),
            paused=bool((p or {}).get("paused", False)),
        )
        for p in pref_rows
        if isinstance(p, dict)
    ]

    ms = (await db.execute(select(ActivationMilestone))).scalars().all()
    milestones = [
        MilestoneRow(
            goal=m.goal,
            configured_at=m.configured_at,
            confirmed_useful_at=m.confirmed_useful_at,
            install_ready_at=m.install_ready_at,
            test_kind=m.test_kind,
            delivery_ok=m.delivery_ok,
        )
        for m in ms
    ]

    return compute_metrics(preferences, milestones, now=datetime.now(timezone.utc))


# ── Mobile QR pairing ────────────────────────────────────────────────
#
# The web app (already logged in) requests a short-lived pairing code and
# renders it as a QR code together with the server URL. The mobile app
# scans it and exchanges the code for a normal access token: no server
# address typing, no password entry on the phone.
#
# Single-use enforcement is an in-process jti set. Codes expire after
# MOBILE_PAIR_TTL_SECONDS anyway, so worst case for a multi-worker
# deployment is a replay window of two minutes on a code that was only
# ever shown on the owner's own screen.

_used_pair_jtis: dict[str, datetime] = {}


def _prune_used_jtis(now: datetime) -> None:
    expired = [j for j, exp in _used_pair_jtis.items() if exp <= now]
    for j in expired:
        del _used_pair_jtis[j]


@router.post("/pair/start", response_model=PairStartResponse)
async def pair_start(current_user: User = Depends(get_current_user)):
    """Mint a single-use QR pairing code for the current user."""
    return PairStartResponse(
        code=create_mobile_pair_code(current_user.id),
        expires_in=MOBILE_PAIR_TTL_SECONDS,
        server_url=settings.public_base_url,
    )


@router.post("/pair/claim", response_model=TokenResponse)
async def pair_claim(body: PairClaim, db: AsyncSession = Depends(get_db)):
    """Exchange a scanned pairing code for an access token. Public, but the
    code itself is the credential: signed, short-lived, and single-use."""
    decoded = decode_mobile_pair_code(body.code)
    if decoded is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired pairing code",
        )
    user_id, jti = decoded

    now = datetime.now(timezone.utc)
    _prune_used_jtis(now)
    if jti in _used_pair_jtis:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Pairing code already used",
        )
    _used_pair_jtis[jti] = now + timedelta(seconds=MOBILE_PAIR_TTL_SECONDS)

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or deactivated",
        )

    user.last_login_at = now
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))
