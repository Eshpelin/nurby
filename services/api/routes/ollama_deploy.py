"""One-click local AI deployment via Ollama.

Handles checking Ollama status, pulling vision models, and
auto-creating a Provider record so users don't need to configure
anything manually.
"""

import asyncio
import logging
import platform
import shutil

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from shared.auth import require_admin
from shared.models import Provider, User

logger = logging.getLogger("nurby.ollama_deploy")

router = APIRouter()

OLLAMA_URL = "http://localhost:11434"

# Fallback install paths for macOS/Linux when Ollama is installed but not on PATH.
# Common case. user installed Ollama.app on macOS but never launched it to create
# the /usr/local/bin symlink.
_OLLAMA_FALLBACK_PATHS = [
    "/Applications/Ollama.app/Contents/Resources/ollama",
    "/usr/local/bin/ollama",
    "/opt/homebrew/bin/ollama",
    "/usr/bin/ollama",
]


def _find_ollama_binary() -> str | None:
    """Locate the ollama binary. Checks PATH first, then common install paths."""
    on_path = shutil.which("ollama")
    if on_path:
        return on_path
    import os
    for path in _OLLAMA_FALLBACK_PATHS:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None

# Curated list of vision-capable models with RAM requirements.
# Ollama has no public catalog API, so we maintain this list.
# Sorted by quality descending within each family.
VISION_MODELS = [
    # Gemma 4 (Google, 2026). encoder-free multimodal (text + image, and
    # native audio on the e-variants). The recommended local default on
    # capable machines. Listed first so the RAM-aware recommender prefers
    # it, and falls back to lighter models on modest hardware.
    # disk_gb is the approximate download size, used for the preflight
    # free-space check before a pull starts.
    {"name": "gemma4:12b", "label": "Gemma 4 12B", "family": "Gemma 4", "ram_gb": 12, "disk_gb": 8.5,
     "quality": "best", "vision": True, "description": "Newest Google multimodal. agentic, runs on 16GB+ laptops"},
    {"name": "gemma4:e4b", "label": "Gemma 4 E4B", "family": "Gemma 4", "ram_gb": 8, "disk_gb": 5.0,
     "quality": "great", "vision": True,
     "description": "Lighter Gemma 4 with native audio input, for mid-range machines"},
    {"name": "gemma4:e2b", "label": "Gemma 4 E2B", "family": "Gemma 4", "ram_gb": 6, "disk_gb": 3.0,
     "quality": "good", "vision": True, "description": "Smallest Gemma 4, native audio, for modest hardware"},
    # Gemma 3 (Google, all sizes support vision)
    {"name": "gemma3:27b", "label": "Gemma 3 27B", "family": "Gemma", "ram_gb": 20, "disk_gb": 17.0,
     "quality": "best", "vision": True, "description": "Highest quality vision model from Google"},
    {"name": "gemma3:12b", "label": "Gemma 3 12B", "family": "Gemma", "ram_gb": 10, "disk_gb": 8.1,
     "quality": "great", "vision": True, "description": "Great balance of quality and speed"},
    {"name": "gemma3:4b", "label": "Gemma 3 4B", "family": "Gemma", "ram_gb": 4, "disk_gb": 3.3,
     "quality": "good", "vision": True, "description": "Good quality, runs on most machines"},
    {"name": "gemma3:1b", "label": "Gemma 3 1B", "family": "Gemma", "ram_gb": 2, "disk_gb": 0.8,
     "quality": "fast", "vision": True, "description": "Ultra-light, works on low-end hardware"},
    # LLaVA (vision-language model)
    {"name": "llava:34b", "label": "LLaVA 34B", "family": "LLaVA", "ram_gb": 24, "disk_gb": 20.0,
     "quality": "best", "vision": True, "description": "Top-tier vision understanding"},
    {"name": "llava:13b", "label": "LLaVA 13B", "family": "LLaVA", "ram_gb": 10, "disk_gb": 8.0,
     "quality": "great", "vision": True, "description": "Strong vision model, well-tested"},
    {"name": "llava:7b", "label": "LLaVA 7B", "family": "LLaVA", "ram_gb": 5, "disk_gb": 4.7,
     "quality": "good", "vision": True, "description": "Proven vision model, moderate resources"},
    # LLaVA-Llama3
    {"name": "llava-llama3", "label": "LLaVA-Llama3 8B", "family": "LLaVA", "ram_gb": 6, "disk_gb": 5.5,
     "quality": "good", "vision": True, "description": "LLaVA fine-tuned on Llama 3"},
    # BakLLaVA
    {"name": "bakllava", "label": "BakLLaVA 7B", "family": "LLaVA", "ram_gb": 5, "disk_gb": 4.7,
     "quality": "good", "vision": True, "description": "Mistral-based vision model"},
    # Moondream (tiny, edge-optimized)
    {"name": "moondream", "label": "Moondream 1.8B", "family": "Moondream", "ram_gb": 2, "disk_gb": 1.7,
     "quality": "fast", "vision": True, "description": "Tiny vision model for edge devices"},
    # Llama 3.2 Vision
    {"name": "llama3.2-vision:11b", "label": "Llama 3.2 Vision 11B", "family": "Llama", "ram_gb": 8, "disk_gb": 7.9,
     "quality": "great", "vision": True, "description": "Meta's multimodal Llama with vision"},
    {"name": "llama3.2-vision:90b", "label": "Llama 3.2 Vision 90B", "family": "Llama", "ram_gb": 55, "disk_gb": 55.0,
     "quality": "best", "vision": True, "description": "Largest Llama vision model"},
    # MiniCPM-V
    {"name": "minicpm-v", "label": "MiniCPM-V 8B", "family": "MiniCPM", "ram_gb": 6, "disk_gb": 5.5,
     "quality": "good", "vision": True, "description": "Compact vision model from OpenBMB"},
]

MODEL_BY_NAME = {m["name"]: m for m in VISION_MODELS}

# Free space to keep after a pull, on top of the model download itself.
_DISK_MARGIN_GB = 2.0

# Families that a pull already told us this Ollama install can't serve
# (e.g. "requires a newer version of Ollama" for a brand-new model like
# Gemma 4). Ollama has no version-compatibility API to check up front, so
# we learn this the first time a pull fails with that specific message and
# remember it for the rest of the process instead of re-attempting (and
# re-waiting on) the same doomed pull on every setup/retry.
_unsupported_families: set[str] = set()
_OLLAMA_TOO_OLD_MARKER = "requires a newer version of ollama"


class OllamaStatus(BaseModel):
    installed: bool
    running: bool
    models: list[str]
    recommended_model: str | None
    system_ram_gb: float | None
    disk_free_gb: float | None = None
    available_models: list[dict]
    # URL where a running Ollama was detected (may be the Docker host),
    # or None. Use this as the provider base_url when reusing an existing
    # install rather than the hardcoded localhost.
    reachable_url: str | None = None


class DeployRequest(BaseModel):
    model: str = "gemma3:4b"


class DeployStatus(BaseModel):
    stage: str  # idle, checking, pulling, registering, done, error, cancelled
    message: str
    progress: float | None = None  # 0-100 for pull progress
    model: str | None = None
    # Machine-readable failure reason, e.g. insufficient_disk /
    # insufficient_ram / pull_failed / no_ollama.
    code: str | None = None


def _get_disk_free_gb() -> float | None:
    """Free disk space in GB where models land (best-effort)."""
    try:
        import psutil

        return psutil.disk_usage("/").free / (1024 ** 3)
    except Exception:
        return None


def _get_system_ram_gb() -> float | None:
    """Get total system RAM in GB."""
    try:
        import os
        if platform.system() == "Darwin":
            import subprocess
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5,
            )
            return int(result.stdout.strip()) / (1024 ** 3)
        else:
            mem_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            return mem_bytes / (1024 ** 3)
    except Exception:
        return None


def _recommend_model(ram_gb: float | None) -> str:
    """Pick the best model that fits in available RAM.

    Skips families this Ollama install has already told us it can't pull
    (see ``_unsupported_families``), so a known-incompatible install stops
    recommending Gemma 4 and goes straight to Gemma 3 instead of failing
    the same way on every fresh setup attempt.
    """
    candidates = [m for m in VISION_MODELS if m["family"] not in _unsupported_families]
    if ram_gb is None:
        return "gemma3:4b"  # safe default
    for model in candidates:
        if ram_gb >= model["ram_gb"] * 1.5:  # leave headroom
            return model["name"]
    return "gemma3:1b"


import os


def _candidate_urls() -> list[str]:
    """Ollama base URLs to probe, in priority order.

    Covers the local process, an explicit override, and the host as seen
    from inside a Docker container (host.docker.internal on Mac/Windows,
    the default bridge gateway on Linux). De-duplicated, order preserved.
    """
    urls = [
        os.environ.get("OLLAMA_BASE_URL", "").strip(),
        OLLAMA_URL,
        "http://host.docker.internal:11434",
        "http://172.17.0.1:11434",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def _probe(url: str) -> list[str] | None:
    """Return the installed model names at ``url``, or None if it is not
    a reachable Ollama."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{url}/api/tags")
            if resp.status_code == 200:
                return [m["name"] for m in resp.json().get("models", [])]
    except (httpx.ConnectError, httpx.TimeoutException, OSError):
        pass
    return None


async def _detect_running() -> tuple[str | None, list[str]]:
    """Find the first reachable Ollama across the candidate URLs.

    Returns (reachable_url, installed_models). (None, []) when nothing
    answers. Lets onboarding reuse an Ollama the user already runs,
    including one on the Docker host, instead of only checking localhost.
    """
    for url in _candidate_urls():
        models = await _probe(url)
        if models is not None:
            return url, models
    return None, []


async def _is_ollama_running() -> bool:
    """Check if the local Ollama API is responding."""
    return (await _probe(OLLAMA_URL)) is not None


async def _get_installed_models() -> list[str]:
    """Get list of models installed in the local Ollama."""
    return (await _probe(OLLAMA_URL)) or []


class DeployJob:
    """State of the (single) in-flight model deployment.

    One deploy at a time is plenty: the wizard and the settings panel are
    the only callers, and Ollama serializes pulls anyway.
    """

    def __init__(self, model: str):
        self.model = model
        self.stage = "checking"  # checking | pulling | registering | done | error | cancelled
        self.message = "Preparing"
        self.progress: float | None = None
        self.code: str | None = None
        self.task: asyncio.Task | None = None
        self.proc: asyncio.subprocess.Process | None = None

    def snapshot(self) -> "DeployStatus":
        return DeployStatus(
            stage=self.stage,
            message=self.message,
            progress=self.progress,
            model=self.model,
            code=self.code,
        )

    @property
    def active(self) -> bool:
        return self.stage in ("checking", "pulling", "registering")


_current_job: DeployJob | None = None

import re as _re

_PERCENT_RE = _re.compile(r"(\d{1,3})%")


async def _pull_via_http(base_url: str, model: str, job: DeployJob) -> tuple[bool, str]:
    """Pull a model on a remote Ollama through its streaming HTTP API,
    updating ``job.progress`` from the NDJSON status lines.

    Used when Nurby has no local ``ollama`` binary (e.g. running in Docker)
    but can reach an Ollama server, such as the bundled ``ollama`` compose
    service. Returns (ok, message).
    """
    import json

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(900.0, connect=10.0)) as client:
            async with client.stream(
                "POST", f"{base_url}/api/pull", json={"model": model, "stream": True}
            ) as resp:
                if resp.status_code != 200:
                    return False, f"Pull failed at {base_url} (status {resp.status_code})"
                last_status = ""
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except ValueError:
                        continue
                    if chunk.get("error"):
                        return False, str(chunk["error"])
                    last_status = chunk.get("status") or last_status
                    total = chunk.get("total")
                    completed = chunk.get("completed")
                    if total and completed is not None:
                        job.progress = round(min(100.0, completed / total * 100), 1)
                        job.message = f"Downloading {model} ({job.progress:.0f}%)"
                if last_status and last_status != "success":
                    return False, f"Pull did not complete. {last_status}"
                return True, "ok"
    except httpx.TimeoutException:
        return False, f"Pull timed out. Try a smaller model or run 'ollama pull {model}' manually."
    except (httpx.ConnectError, OSError) as exc:
        return False, f"Could not reach Ollama at {base_url}. {exc}"


async def _pull_via_cli(ollama_path: str, model: str, job: DeployJob) -> tuple[bool, str]:
    """Pull via the local ollama binary, parsing percent markers from
    stderr for best-effort progress. The process handle is stored on the
    job so a cancel can terminate it."""
    try:
        proc = await asyncio.create_subprocess_exec(
            ollama_path, "pull", model,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, FileNotFoundError) as exc:
        return False, f"Pull failed. {exc}"
    job.proc = proc
    tail = b""
    try:
        assert proc.stderr is not None
        while True:
            chunk = await proc.stderr.read(1024)
            if not chunk:
                break
            tail = (tail + chunk)[-2048:]
            matches = _PERCENT_RE.findall(chunk.decode(errors="replace"))
            if matches:
                job.progress = float(matches[-1])
                job.message = f"Downloading {model} ({job.progress:.0f}%)"
        await proc.wait()
    finally:
        job.proc = None
    if proc.returncode != 0:
        return False, f"Failed to pull {model}. {_extract_cli_error(tail)}"
    return True, "ok"


_ANSI_RE = _re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[()][A-Za-z0-9]")


def _extract_cli_error(raw: bytes) -> str:
    """Pull the actual error sentence out of `ollama pull`'s stderr.

    stderr is a spinner animation (raw ANSI cursor-control codes) followed
    by the real message, so the *last* printed line is reliably something
    like a bare "https://..." URL rather than the sentence explaining why
    the pull failed. Strip the ANSI noise and progress-spinner lines, then
    return the longest remaining line, prose being the useful part.
    """
    text = _ANSI_RE.sub("", raw.decode(errors="replace"))
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not _PERCENT_RE.search(line) and "pulling manifest" not in line
    ]
    if not lines:
        return "Unknown error"
    return max(lines, key=len)


async def _register_provider(model_name: str, provider_url: str) -> str:
    """Upsert the Ollama Provider row for ``provider_url``. Runs inside the
    background job, so it opens its own session instead of using the
    request-scoped one."""
    from shared.database import async_session

    async with async_session() as db:
        result = await db.execute(
            select(Provider).where(Provider.kind == "ollama", Provider.base_url == provider_url)
        )
        existing = result.scalar_one_or_none()
        if existing:
            if existing.default_model != model_name or not existing.active:
                existing.default_model = model_name
                existing.active = True
                await db.commit()
            return f"{model_name} is ready. Updated existing Ollama provider."
        db.add(
            Provider(
                name=f"Ollama ({model_name})",
                kind="ollama",
                base_url=provider_url,
                api_key=None,
                default_model=model_name,
                active=True,
            )
        )
        await db.commit()
        return f"{model_name} is ready. Provider auto-configured."


def _model_installed(model_name: str, installed: list[str]) -> bool:
    return model_name in installed or any(
        m.startswith(model_name.split(":")[0]) for m in installed if ":" in model_name
    )


async def _run_deploy_job(job: DeployJob, ollama_path: str | None, remote_url: str | None) -> None:
    """The background deploy: pull the model, then register the provider."""
    try:
        job.stage = "pulling"
        job.message = f"Downloading {job.model}"
        if ollama_path:
            ok, msg = await _pull_via_cli(ollama_path, job.model, job)
            provider_url = OLLAMA_URL
        else:
            assert remote_url is not None
            ok, msg = await _pull_via_http(remote_url, job.model, job)
            provider_url = remote_url
        if not ok:
            if _OLLAMA_TOO_OLD_MARKER in msg.lower():
                entry = MODEL_BY_NAME.get(job.model)
                if entry:
                    _unsupported_families.add(entry["family"])
                job.code = "ollama_outdated"
                job.message = (
                    f"This Ollama install can't pull {job.model} yet (needs a newer "
                    "version of Ollama). Update Ollama from https://ollama.com/download, "
                    "or pick a different model."
                )
            else:
                job.code = "pull_failed"
                job.message = msg
            job.stage = "error"
            return
        job.stage = "registering"
        job.message = "Registering the provider"
        job.message = await _register_provider(job.model, provider_url)
        job.stage = "done"
        job.progress = 100.0
    except asyncio.CancelledError:
        if job.proc is not None:
            try:
                job.proc.terminate()
            except ProcessLookupError:
                pass
        job.stage = "cancelled"
        job.message = (
            "Cancelled. Already-downloaded layers are kept, so resuming is fast."
        )
        raise
    except Exception as exc:  # keep the job observable instead of losing the task error
        logger.exception("Deploy job failed")
        job.stage = "error"
        job.code = "pull_failed"
        job.message = str(exc)


@router.get("/status", response_model=OllamaStatus)
async def get_ollama_status(_current_user: User = Depends(require_admin)):
    """Check Ollama installation status and recommend a model."""
    ollama_path = _find_ollama_binary()
    # Detect a running Ollama anywhere we can reach. local process, an
    # override URL, or the Docker host. installed means we can also pull
    # new models locally; reachable means we can at least use it as-is.
    reachable_url, models = await _detect_running()
    running = reachable_url is not None
    installed = ollama_path is not None or running
    # _get_system_ram_gb() shells out to `sysctl` on macOS (up to 5s); keep it
    # off the event loop so a slow probe doesn't stall all other requests.
    ram_gb = await asyncio.to_thread(_get_system_ram_gb)
    disk_free = await asyncio.to_thread(_get_disk_free_gb)
    recommended = _recommend_model(ram_gb)

    return OllamaStatus(
        installed=installed,
        running=running,
        models=models,
        recommended_model=recommended,
        system_ram_gb=round(ram_gb, 1) if ram_gb else None,
        disk_free_gb=round(disk_free, 1) if disk_free else None,
        available_models=VISION_MODELS,
        reachable_url=reachable_url,
    )


def _preflight(model_name: str) -> DeployStatus | None:
    """RAM/disk sanity check before starting a pull. Only meaningful for
    curated models (unknown model names skip the check)."""
    entry = MODEL_BY_NAME.get(model_name)
    if not entry:
        return None
    if entry["family"] in _unsupported_families:
        return DeployStatus(
            stage="error",
            code="ollama_outdated",
            model=model_name,
            message=(
                f"This Ollama install can't pull {entry['family']} models yet "
                "(needs a newer version of Ollama). Update Ollama from "
                "https://ollama.com/download, or pick a different model."
            ),
        )
    ram_gb = _get_system_ram_gb()
    if ram_gb is not None and ram_gb < entry["ram_gb"]:
        return DeployStatus(
            stage="error",
            code="insufficient_ram",
            model=model_name,
            message=(
                f"{entry['label']} needs about {entry['ram_gb']} GB of RAM to run; "
                f"this machine has {ram_gb:.0f} GB. Pick a smaller model."
            ),
        )
    disk_free = _get_disk_free_gb()
    needed = entry["disk_gb"] + _DISK_MARGIN_GB
    if disk_free is not None and disk_free < needed:
        return DeployStatus(
            stage="error",
            code="insufficient_disk",
            model=model_name,
            message=(
                f"Downloading {entry['label']} needs about {needed:.0f} GB free; "
                f"only {disk_free:.1f} GB is available. Free up space or pick a smaller model."
            ),
        )
    return None


@router.post("/deploy", response_model=DeployStatus)
async def deploy_model(
    body: DeployRequest,
    _current_user: User = Depends(require_admin),
):
    """Start a model deployment via Ollama.

    Returns immediately. If the model is already installed the provider is
    registered synchronously and the response is stage="done"; otherwise a
    background pull starts (stage="pulling") and callers poll
    GET /deploy/status. DELETE /deploy cancels an in-flight pull.
    """
    global _current_job
    model_name = body.model

    # Validate model name format (allow any model, not just curated list)
    if not model_name or "/" in model_name or ".." in model_name:
        return DeployStatus(stage="error", code="invalid_model", message="Invalid model name")

    if _current_job is not None and _current_job.active:
        if _current_job.model == model_name:
            return _current_job.snapshot()
        raise HTTPException(
            status_code=409,
            detail=f"A deploy of {_current_job.model} is already running. Cancel it first.",
        )

    # Decide how to reach Ollama. A local binary lets us serve + pull via
    # the CLI. Otherwise (typical in Docker), look for a reachable Ollama
    # server such as the bundled compose service and pull over HTTP. The
    # provider is registered at whichever URL actually serves the model.
    ollama_path = _find_ollama_binary()
    remote_url, remote_models = await _detect_running()

    if ollama_path:
        # Local binary path. start the daemon if needed.
        if not await _is_ollama_running():
            try:
                await asyncio.create_subprocess_exec(
                    ollama_path, "serve",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                for _ in range(10):
                    await asyncio.sleep(1)
                    if await _is_ollama_running():
                        break
                else:
                    return DeployStatus(
                        stage="error", code="no_ollama",
                        message="Ollama started but API not responding after 10 seconds",
                    )
            except (OSError, FileNotFoundError) as exc:
                return DeployStatus(
                    stage="error", code="no_ollama", message=f"Failed to start Ollama. {exc}"
                )
        installed = await _get_installed_models()
        provider_url = OLLAMA_URL
    elif remote_url:
        installed = remote_models
        provider_url = remote_url
    else:
        return DeployStatus(
            stage="error",
            code="no_ollama",
            message=(
                "No Ollama found. Install it from https://ollama.com/download on the "
                "machine running Nurby, start the bundled service with "
                "`docker compose --profile local-ai up -d ollama`, or point a cloud "
                "provider in the previous step."
            ),
        )

    # Cheap path: model already present. Register synchronously so callers
    # that don't poll (old settings panel behavior) still work.
    if _model_installed(model_name, installed):
        message = await _register_provider(model_name, provider_url)
        return DeployStatus(stage="done", message=message, model=model_name, progress=100.0)

    failure = _preflight(model_name)
    if failure is not None:
        return failure

    job = DeployJob(model_name)
    # Stamp the stage before the task runs so the immediate response (and
    # any poll racing the task startup) already reads "pulling".
    job.stage = "pulling"
    job.message = f"Downloading {model_name}"
    job.task = asyncio.create_task(
        _run_deploy_job(job, ollama_path, None if ollama_path else remote_url)
    )
    _current_job = job
    return job.snapshot()


@router.get("/deploy/status", response_model=DeployStatus)
async def get_deploy_status(_current_user: User = Depends(require_admin)):
    """Snapshot of the current (or last finished) deploy job."""
    if _current_job is None:
        return DeployStatus(stage="idle", message="No deploy running")
    return _current_job.snapshot()


@router.delete("/deploy", response_model=DeployStatus)
async def cancel_deploy(_current_user: User = Depends(require_admin)):
    """Cancel the in-flight deploy. Ollama keeps already-downloaded layers,
    so a later retry resumes where it left off."""
    if _current_job is None or not _current_job.active:
        return DeployStatus(stage="idle", message="No deploy running")
    if _current_job.task is not None:
        _current_job.task.cancel()
        try:
            await _current_job.task
        except asyncio.CancelledError:
            pass
    return _current_job.snapshot()
