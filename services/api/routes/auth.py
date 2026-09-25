import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from shared.activation import (
    DELIVERY_ACTIONS,
    ActivationList,
    ActivationView,
    ConfigureRequest,
    ConfirmRequest,
    DraftRuleRequest,
    RetestRequest,
    clear_activation_test,
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
from shared.camera_secrets import seal, unseal
from shared.database import get_db
from shared.models import ActivationMilestone, Event, InviteKey, Recording, Rule, User, UserCameraAccess
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
    SetupCodeAdoption,
)

router = APIRouter()
logger = logging.getLogger("nurby.api.auth")


def _hash_setup_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_setup_code() -> str:
    # Eight uppercase hex characters are easy to read aloud and paste, while
    # still providing 32 bits of one-time entropy alongside the cookie bind.
    return secrets.token_hex(4).upper()


def _set_install_cookie(response: Response, install_secret: str) -> None:
    response.set_cookie(
        "nurby_install_secret", install_secret,
        httponly=True, secure=False, samesite="strict", max_age=60 * 60 * 24 * 30,
    )


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
async def bootstrap(
    request: Request = None,
    response: Response = None,
    db: AsyncSession = Depends(get_db),
):
    """Drop a brand-new install straight in.

    On first run (no users) this auto-creates a provisional owner account
    and returns a login token, so a first-time user never hits a signup
    wall. The account is flagged ``is_provisional`` until the user claims
    it (sets a real email + password) via ``/auth/claim``.

    Re-adoption while unclaimed is limited to the installing browser by an
    HttpOnly cookie. Once the account is claimed (real credentials), this
    returns 409 and the caller falls back to the login screen.
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
        # Only an unclaimed provisional owner exists. Re-adoption is bound to
        # the browser that created the install. OPEN_ADMIN is an explicit,
        # documented escape hatch for headless/kiosk deployments.
        owner = min(users, key=lambda u: u.created_at)
        install_secret = request.cookies.get("nurby_install_secret") if request is not None else None
        expected = getattr(owner, "bootstrap_secret_hash", None)
        valid_cookie = bool(
            install_secret and expected
            and secrets.compare_digest(hashlib.sha256(install_secret.encode()).hexdigest(), expected)
        )
        if not valid_cookie and not settings.allow_open_admin:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This Nurby is being set up on another device. Use the installing browser or claim the account.",
            )
        setup_code = None
        # Older provisional rows may predate the setup-code migration. Issue
        # the code lazily when that owner returns through the bound browser.
        if valid_cookie and not getattr(owner, "setup_code_hash", None):
            setup_code = _new_setup_code()
            owner.setup_code_hash = _hash_setup_value(setup_code)
            owner.setup_code_ciphertext = seal(setup_code)
            await db.commit()
        token = create_access_token(owner.id)
        return TokenResponse(
            access_token=token, user=UserResponse.model_validate(owner), setup_code=setup_code
        )

    # Random, unusable-by-design credentials. The user never sees these.
    # they exist only so the row is valid until the account is claimed.
    placeholder_email = f"owner+{secrets.token_hex(6)}@nurby.local"
    install_secret = secrets.token_urlsafe(32)
    setup_code = _new_setup_code()
    user = User(
        email=placeholder_email,
        display_name="Owner",
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role="admin",
        camera_access_mode="all",
        is_active=True,
        is_provisional=True,
        bootstrap_secret_hash=hashlib.sha256(install_secret.encode()).hexdigest(),
        setup_code_hash=_hash_setup_value(setup_code),
        setup_code_ciphertext=seal(setup_code),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id)
    logger.warning("Nurby provisional setup code: %s", setup_code)
    if response is not None:
        _set_install_cookie(response, install_secret)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user), setup_code=setup_code)


@router.post("/bootstrap/adopt", response_model=TokenResponse)
async def adopt_provisional_owner(
    body: SetupCodeAdoption,
    request: Request = None,
    response: Response = None,
    db: AsyncSession = Depends(get_db),
):
    """Use the one-time setup code to move an unclaimed install to a new browser."""
    await db.execute(text("SELECT pg_advisory_xact_lock(481566)"))
    users = (await db.execute(select(User))).scalars().all()
    owners = [u for u in users if u.is_provisional]
    if not owners or any(not u.is_provisional for u in users):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Setup is already claimed")
    owner = min(owners, key=lambda u: u.created_at)
    expected = getattr(owner, "setup_code_hash", None)
    if not expected or not secrets.compare_digest(_hash_setup_value(body.code.strip().upper()), expected):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invalid or already-used setup code")

    # Consume the code and bind the newly adopted browser to a fresh secret.
    install_secret = secrets.token_urlsafe(32)
    owner.setup_code_hash = None
    owner.setup_code_ciphertext = None
    owner.bootstrap_secret_hash = _hash_setup_value(install_secret)
    await db.commit()
    token = create_access_token(owner.id)
    if response is not None:
        _set_install_cookie(response, install_secret)
    return TokenResponse(access_token=token, user=UserResponse.model_validate(owner))


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
    current_user.setup_code_hash = None
    current_user.setup_code_ciphertext = None
    current_user.bootstrap_secret_hash = None
    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)


@router.get("/setup-code")
async def get_setup_code(current_user: User = Depends(get_current_user)):
    """Return the setup code only to the authenticated, unclaimed owner."""
    if not current_user.is_provisional:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No setup code available")
    value = unseal(getattr(current_user, "setup_code_ciphertext", None))
    if not value:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No setup code available")
    return {"setup_code": value, "single_use": True}


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
        event_id=str(m.event_id) if getattr(m, "event_id", None) else None,
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
        ).with_for_update()
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
    milestone = await _get_milestone(db, current_user, body.goal)
    # The wizard is resumable and users can arrive here from both the goal
    # flow and the rule templates. Reuse the milestone's draft first, then
    # an equivalent starter rule, so retries never create duplicates.
    rule = None
    if milestone and milestone.draft_rule_id:
        rule = await db.get(Rule, milestone.draft_rule_id)
    if rule is None:
        rule = (await db.execute(
            select(Rule).where(
                Rule.name == payload["name"],
                Rule.trigger_pattern == payload["trigger_pattern"],
            ).order_by(Rule.created_at.asc()).limit(1)
        )).scalar_one_or_none()
    if rule is None:
        rule = Rule(**payload)
        db.add(rule)
        await db.commit()
        await db.refresh(rule)
    now = datetime.now(timezone.utc)
    if milestone is None:
        milestone = ActivationMilestone(user_id=current_user.id, goal=body.goal, install_ready_at=now)
        db.add(milestone)
    milestone.draft_rule_id = rule.id
    clear_activation_test(milestone)
    milestone.configured_at = None
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
    if milestone.rule_id != rule.id or milestone.camera_id != uuid_or_none(camera_id):
        clear_activation_test(milestone)
        milestone.configured_at = None
    milestone.rule_id = rule.id
    milestone.camera_id = uuid_or_none(camera_id)
    if milestone.configured_at is None:
        milestone.configured_at = now
    if milestone.install_ready_at is None:
        milestone.install_ready_at = now
    await db.commit()
    await db.refresh(milestone)
    return _milestone_view(milestone)


async def _activation_evidence(db: AsyncSession, milestone: ActivationMilestone):
    """Resolve only the recorded event and its own recording, never a generic feed."""
    if (milestone.configured_at is None or milestone.tested_at is None
            or milestone.delivery_ok is not True or not milestone.event_id):
        raise HTTPException(status_code=409, detail="No delivered test event yet. Trigger the camera and wait for the alert")
    event = await db.get(Event, milestone.event_id)
    if event is None or event.rule_id != milestone.rule_id or event.camera_id != milestone.camera_id:
        raise HTTPException(status_code=409, detail="Test evidence no longer matches this setup. Start a new test")
    recording = await db.get(Recording, event.recording_id) if event.recording_id else None
    if recording is None or recording.camera_id != milestone.camera_id:
        raise HTTPException(status_code=409, detail="No recording is available for this test. Check recording and start a new test")
    from services.api.routes.recordings import _get_disk_path_or_404
    _get_disk_path_or_404(recording)
    return event, recording


@router.get("/me/activation/evidence")
async def get_activation_evidence(
    goal: str,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    milestone = await _get_milestone(db, current_user, goal)
    if milestone is None:
        raise HTTPException(status_code=404, detail="Nothing to review for this goal yet")
    event, recording = await _activation_evidence(db, milestone)
    offset = max(0.0, (event.fired_at - recording.started_at).total_seconds())
    # Processing can finish after the recording ends; don't seek beyond it.
    if recording.duration_seconds and offset >= recording.duration_seconds:
        offset = 0.0
    return {"event_id": str(event.id), "recording_id": str(recording.id), "seek_seconds": offset}


@router.post("/me/activation/retest", response_model=ActivationView)
async def restart_activation_test(
    body: RetestRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    milestone = await _get_milestone(db, current_user, body.goal)
    if milestone is None:
        raise HTTPException(status_code=404, detail="No configured goal to test")
    clear_activation_test(milestone)
    await db.commit()
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
    if body.event_id != milestone.event_id:
        raise HTTPException(status_code=409, detail="The test event changed. Review its evidence again")
    await _activation_evidence(db, milestone)
    if milestone.confirmed_useful_at is None:
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


class FunnelEventRequest(BaseModel):
    event: str


@router.post("/onboarding/funnel")
async def record_funnel_event(
    body: FunnelEventRequest,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Count one first-run wizard funnel event (#293).

    Fire-and-forget from the client: failures are ignored there, and the
    aggregate is only ever read by the admin metrics card. Counters live
    in the onboarding_funnel app setting — no migration, no PII.
    """
    from shared.app_settings import get_setting, set_setting
    from shared.onboarding_metrics import bump_funnel, normalize_funnel_event

    event = normalize_funnel_event(body.event)
    if event is None:
        raise HTTPException(status_code=422, detail="Unknown funnel event")
    counts = await get_setting("onboarding_funnel", {})
    if not isinstance(counts, dict):
        counts = {}
    await set_setting("onboarding_funnel", bump_funnel(counts, event))
    return {"ok": True}


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

    from shared.app_settings import get_setting
    from shared.onboarding_metrics import FUNNEL_EVENTS

    funnel_raw = await get_setting("onboarding_funnel", {})
    funnel = {
        event: int((funnel_raw or {}).get(event, 0))
        for event in FUNNEL_EVENTS
        if isinstance(funnel_raw, dict)
    }

    return compute_metrics(preferences, milestones, now=datetime.now(timezone.utc), funnel=funnel)


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
