import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.perception.vlm import get_active_provider as get_active_vlm_provider
from services.search.backfill import backfill_embeddings
from services.search.digest import generate_digest
from services.search.embeddings import get_embedding_provider
from services.search.query import (
    answer_question,
    search_conversations,
    search_observations,
    search_summaries,
    search_transcripts,
)
from shared.auth import get_current_user, require_admin
from shared.database import get_db
from shared.models import Camera, DigestEntry, Observation, Provider, User
from shared.schemas import DigestEntryResponse

router = APIRouter()


class SearchResponse(BaseModel):
    results: list[dict]
    total: int


class QuestionRequest(BaseModel):
    question: str


class QuestionResponse(BaseModel):
    answer: str | None
    sources: list[dict]
    note: str | None = None


class BackfillResponse(BaseModel):
    updated: int
    message: str


@router.get("", response_model=SearchResponse)
async def search(
    q: str | None = Query(default=None, description="Text query"),
    camera_id: uuid.UUID | None = Query(default=None),
    person: str | None = Query(default=None, description="Person name filter"),
    object: str | None = Query(default=None, description="Object label filter"),
    time_from: datetime | None = Query(default=None),
    time_to: datetime | None = Query(default=None),
    limit: int = Query(default=30, le=100),
    offset: int = Query(default=0, ge=0),
    _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Search observations with structured filters and text matching."""
    results = await search_observations(
        db,
        query=q,
        camera_id=camera_id,
        person_name=person,
        object_label=object,
        time_from=time_from,
        time_to=time_to,
        limit=limit,
        offset=offset,
    )
    return SearchResponse(results=results, total=len(results))


@router.get("/union", response_model=SearchResponse)
async def search_union(
    q: str | None = Query(default=None),
    camera_id: uuid.UUID | None = Query(default=None),
    time_from: datetime | None = Query(default=None),
    time_to: datetime | None = Query(default=None),
    limit_per_kind: int = Query(default=10, ge=1, le=50),
    kinds: str = Query(
        default="observations,transcripts,conversations,summaries",
        description="Comma-separated. observations,transcripts,conversations,summaries",
    ),
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Union search across observations, transcripts, conversations, and
    summaries. Each kind contributes up to ``limit_per_kind`` rows. The
    UI is responsible for ranking / interleaving by recency or distance.
    """
    selected = {k.strip() for k in kinds.split(",") if k.strip()}
    results: list[dict] = []
    if "observations" in selected:
        results.extend(
            await search_observations(
                db, query=q, camera_id=camera_id,
                time_from=time_from, time_to=time_to, limit=limit_per_kind,
            )
        )
    if "transcripts" in selected:
        results.extend(
            await search_transcripts(
                db, query=q, camera_id=camera_id,
                time_from=time_from, time_to=time_to, limit=limit_per_kind,
            )
        )
    if "conversations" in selected:
        results.extend(
            await search_conversations(
                db, query=q, camera_id=camera_id,
                time_from=time_from, time_to=time_to, limit=limit_per_kind,
            )
        )
    if "summaries" in selected:
        results.extend(
            await search_summaries(
                db, query=q, camera_id=camera_id,
                time_from=time_from, time_to=time_to, limit=limit_per_kind,
            )
        )
    # Sort. distance asc when present, else started_at desc.
    def _sort_key(r: dict):
        d = r.get("distance")
        return (0 if d is not None else 1, d if d is not None else 0,
                -datetime.fromisoformat(r["started_at"]).timestamp())
    results.sort(key=_sort_key)
    return SearchResponse(results=results, total=len(results))


@router.post("/ask", response_model=QuestionResponse)
async def ask_question(
    body: QuestionRequest,
    _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Answer a natural language question grounded in observation history."""
    result = await answer_question(db, body.question)
    return QuestionResponse(**result)


@router.get("/digest")
async def get_digest(
    period: str = Query(default="daily", pattern="^(hourly|daily|1h|6h|12h|24h|48h|7d)$"),
    camera_id: uuid.UUID | None = Query(default=None),
    _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Generate an activity digest for the given period (on demand)."""
    custom_prompt = None
    provider = None

    # Use per-camera digest config if camera specified
    if camera_id:
        cam = await db.get(Camera, camera_id)
        if cam:
            custom_prompt = cam.digest_prompt
            if cam.digest_provider_id:
                provider = await db.get(Provider, cam.digest_provider_id)

    if not provider:
        # Prefer the active VLM/text provider. get_embedding_provider
        # returns the embedding model, which is not a text LLM and
        # silently produces no narrative, forcing the stats fallback.
        provider = await get_active_vlm_provider()
        if not provider:
            provider = await get_embedding_provider()

    return await generate_digest(
        db, period=period, camera_id=camera_id,
        provider=provider, custom_prompt=custom_prompt,
    )


@router.get("/digests", response_model=list[DigestEntryResponse])
async def list_digests(
    camera_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=20, le=100),
    offset: int = Query(default=0, ge=0),
    _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """List stored digests with optional camera_id filter, newest first."""
    stmt = select(DigestEntry).order_by(DigestEntry.generated_at.desc())

    if camera_id is not None:
        stmt = stmt.where(DigestEntry.camera_id == camera_id)

    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/digests/latest", response_model=DigestEntryResponse | None)
async def get_latest_digest(
    camera_id: uuid.UUID | None = Query(default=None),
    _current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Get the most recent stored digest, optionally filtered by camera."""
    stmt = select(DigestEntry).order_by(DigestEntry.generated_at.desc()).limit(1)

    if camera_id is not None:
        stmt = stmt.where(DigestEntry.camera_id == camera_id)

    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    return entry


@router.post("/backfill", response_model=BackfillResponse)
async def run_backfill(
    batch_size: int = Query(default=50, ge=1, le=500),
    _current_user: User = Depends(require_admin),
):
    """Backfill description embeddings for observations that have VLM descriptions
    but no embedding yet. Intended for admin use."""
    updated = await backfill_embeddings(batch_size=batch_size)
    return BackfillResponse(
        updated=updated,
        message=f"Backfill complete. {updated} observations updated with embeddings.",
    )


# ── FindAnything deep scan (visual grounding) ──────────────────────────
#
# Direct, user-initiated visual search: the "Scan the raw footage" button /
# "Deep visual scan" toggle land here (design §3.2/§3.6). It pre-filters
# candidate frames from the index then runs grounding only on those, streaming
# boxes back via the poll endpoint. Person/identity queries are routed to
# face-rec instead of grounding (§3.4).


class ScanRequest(BaseModel):
    query: str
    camera_id: uuid.UUID | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None
    max_frames: int | None = None


class ScanRoutedModel(BaseModel):
    kind: str
    name: str
    message: str


class ScanFrameModel(BaseModel):
    observation_id: str
    camera_id: str
    camera_name: str
    started_at: str
    thumbnail_path: str | None
    boxes: list[dict]


class ScanStatusModel(BaseModel):
    scan_id: str
    status: str
    scanned: int
    total: int
    found: int
    summary: str
    results: list[ScanFrameModel]
    routed: ScanRoutedModel | None = None
    error: str | None = None
    leaves_privacy_boundary: bool = False


def _job_to_status(job) -> ScanStatusModel:
    return ScanStatusModel(
        scan_id=job.id,
        status=job.status,
        scanned=job.scanned,
        total=job.total,
        found=job.found,
        summary=job.summary(),
        results=[
            ScanFrameModel(
                observation_id=r.observation_id,
                camera_id=r.camera_id,
                camera_name=r.camera_name,
                started_at=r.started_at,
                thumbnail_path=r.thumbnail_path,
                boxes=r.boxes,
            )
            for r in job.results
        ],
        routed=(
            ScanRoutedModel(kind=job.routed.kind, name=job.routed.name, message=job.routed.message)
            if job.routed
            else None
        ),
        error=job.error,
        leaves_privacy_boundary=job.leaves_privacy_boundary,
    )


@router.post("/scan", response_model=ScanStatusModel)
async def start_scan(
    body: ScanRequest,
    current_user: User = Depends(get_current_user),
):
    """Kick off a deep visual scan and return the initial job state. Poll
    ``GET /search/scan/{scan_id}`` for streamed results."""
    from services.grounding.config import is_enabled
    from services.search.scan import get_registry, run_scan

    query = (body.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    if not await is_enabled():
        raise HTTPException(
            status_code=409,
            detail="FindAnything is not enabled. Turn on visual grounding in Settings.",
        )

    registry = get_registry()
    # One active scan per user keeps a single user from wedging the GPU (§5).
    existing = registry.active_for_user(str(current_user.id))
    if existing is not None:
        return _job_to_status(existing)

    job = registry.create(str(current_user.id), query)
    asyncio.create_task(
        run_scan(
            job,
            camera_id=body.camera_id,
            time_from=body.time_from,
            time_to=body.time_to,
            max_frames=body.max_frames or 0,
        )
    )
    return _job_to_status(job)


@router.get("/scan/{scan_id}", response_model=ScanStatusModel)
async def get_scan(
    scan_id: str,
    current_user: User = Depends(get_current_user),
):
    """Poll a deep-scan job. Results accumulate as frames are grounded."""
    from services.search.scan import get_registry

    job = get_registry().get(scan_id)
    # 404 (not 403) on a foreign job so we never confirm another user's id.
    if job is None or job.user_id != str(current_user.id):
        raise HTTPException(status_code=404, detail="scan not found")
    return _job_to_status(job)


class LocateNowRequest(BaseModel):
    camera_id: uuid.UUID
    prompt: str


class LocateNowResponse(BaseModel):
    found: bool
    boxes: list[dict]
    observation_id: str | None = None
    camera_name: str = ""
    thumbnail_path: str | None = None
    started_at: str | None = None
    summary: str


@router.post("/locate-now", response_model=LocateNowResponse)
async def locate_now(
    body: LocateNowRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ground a prompt against a camera's most-recent frame, synchronously —
    the "find X in this camera now" affordance. One frame, one inference (vs the
    deep scan over recordings). Uses the interactive grounding lane since the
    user is waiting, and benefits from the same result cache."""
    from services.grounding.client import get_client
    from services.grounding.config import is_enabled
    from services.search.scan import _default_frame_loader

    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    if not await is_enabled():
        raise HTTPException(
            status_code=409,
            detail="FindAnything is not enabled. Turn on visual grounding in Settings.",
        )

    obs = (await db.execute(
        select(Observation)
        .where(Observation.camera_id == body.camera_id, Observation.thumbnail_path.is_not(None))
        .order_by(Observation.started_at.desc())
        .limit(1)
    )).scalars().first()
    cam = await db.get(Camera, body.camera_id)
    cam_name = (cam.name if cam else "") or ""

    if obs is None:
        return LocateNowResponse(found=False, boxes=[], camera_name=cam_name,
                                 summary="No recent frame for this camera yet.")

    frame = await asyncio.to_thread(_default_frame_loader, obs.thumbnail_path)
    if frame is None:
        return LocateNowResponse(found=False, boxes=[], observation_id=str(obs.id),
                                 camera_name=cam_name, thumbnail_path=obs.thumbnail_path,
                                 started_at=obs.started_at.isoformat(),
                                 summary="Could not load the latest frame.")

    result = await get_client().ground(frame, prompt, interactive=True)
    if result.error:
        raise HTTPException(status_code=503, detail=f"grounding unavailable: {result.error}")

    boxes = [
        {"bbox_norm": list(b.bbox_norm), "is_point": b.is_point, "label": b.label}
        for b in result.boxes
    ]
    return LocateNowResponse(
        found=bool(boxes), boxes=boxes, observation_id=str(obs.id), camera_name=cam_name,
        thumbnail_path=obs.thumbnail_path, started_at=obs.started_at.isoformat(),
        summary=f"{len(boxes)} match(es) for '{prompt}'." if boxes else f"No '{prompt}' in the latest frame.",
    )


@router.get("/grounding/health")
async def grounding_health(_current_user: User = Depends(get_current_user)):
    """Health of the grounding backend for the navbar surface."""
    from services.grounding.client import get_client

    return await get_client().health()
