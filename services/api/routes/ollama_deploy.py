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
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.auth import require_admin
from shared.database import get_db
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
    # Gemma 3 (Google, all sizes support vision)
    {"name": "gemma3:27b", "label": "Gemma 3 27B", "family": "Gemma", "ram_gb": 20, "quality": "best", "vision": True, "description": "Highest quality vision model from Google"},
    {"name": "gemma3:12b", "label": "Gemma 3 12B", "family": "Gemma", "ram_gb": 10, "quality": "great", "vision": True, "description": "Great balance of quality and speed"},
    {"name": "gemma3:4b", "label": "Gemma 3 4B", "family": "Gemma", "ram_gb": 4, "quality": "good", "vision": True, "description": "Good quality, runs on most machines"},
    {"name": "gemma3:1b", "label": "Gemma 3 1B", "family": "Gemma", "ram_gb": 2, "quality": "fast", "vision": True, "description": "Ultra-light, works on low-end hardware"},
    # LLaVA (vision-language model)
    {"name": "llava:34b", "label": "LLaVA 34B", "family": "LLaVA", "ram_gb": 24, "quality": "best", "vision": True, "description": "Top-tier vision understanding"},
    {"name": "llava:13b", "label": "LLaVA 13B", "family": "LLaVA", "ram_gb": 10, "quality": "great", "vision": True, "description": "Strong vision model, well-tested"},
    {"name": "llava:7b", "label": "LLaVA 7B", "family": "LLaVA", "ram_gb": 5, "quality": "good", "vision": True, "description": "Proven vision model, moderate resources"},
    # LLaVA-Llama3
    {"name": "llava-llama3", "label": "LLaVA-Llama3 8B", "family": "LLaVA", "ram_gb": 6, "quality": "good", "vision": True, "description": "LLaVA fine-tuned on Llama 3"},
    # BakLLaVA
    {"name": "bakllava", "label": "BakLLaVA 7B", "family": "LLaVA", "ram_gb": 5, "quality": "good", "vision": True, "description": "Mistral-based vision model"},
    # Moondream (tiny, edge-optimized)
    {"name": "moondream", "label": "Moondream 1.8B", "family": "Moondream", "ram_gb": 2, "quality": "fast", "vision": True, "description": "Tiny vision model for edge devices"},
    # Llama 3.2 Vision
    {"name": "llama3.2-vision:11b", "label": "Llama 3.2 Vision 11B", "family": "Llama", "ram_gb": 8, "quality": "great", "vision": True, "description": "Meta's multimodal Llama with vision"},
    {"name": "llama3.2-vision:90b", "label": "Llama 3.2 Vision 90B", "family": "Llama", "ram_gb": 55, "quality": "best", "vision": True, "description": "Largest Llama vision model"},
    # MiniCPM-V
    {"name": "minicpm-v", "label": "MiniCPM-V 8B", "family": "MiniCPM", "ram_gb": 6, "quality": "good", "vision": True, "description": "Compact vision model from OpenBMB"},
]


class OllamaStatus(BaseModel):
    installed: bool
    running: bool
    models: list[str]
    recommended_model: str | None
    system_ram_gb: float | None
    available_models: list[dict]
    # URL where a running Ollama was detected (may be the Docker host),
    # or None. Use this as the provider base_url when reusing an existing
    # install rather than the hardcoded localhost.
    reachable_url: str | None = None


class DeployRequest(BaseModel):
    model: str = "gemma3:4b"


class DeployStatus(BaseModel):
    stage: str  # checking, installing, pulling, registering, done, error
    message: str
    progress: float | None = None  # 0-100 for pull progress


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
    """Pick the best model that fits in available RAM."""
    if ram_gb is None:
        return "gemma3:4b"  # safe default
    for model in VISION_MODELS:
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


async def _pull_via_http(base_url: str, model: str) -> tuple[bool, str]:
    """Pull a model on a remote Ollama through its HTTP API.

    Used when Nurby has no local ``ollama`` binary (e.g. running in Docker)
    but can reach an Ollama server, such as the bundled ``ollama`` compose
    service. Returns (ok, message). The pull can take minutes on first run,
    so the timeout is generous. stream is disabled so the call returns once
    the model is fully present.
    """
    try:
        async with httpx.AsyncClient(timeout=900.0) as client:
            resp = await client.post(
                f"{base_url}/api/pull",
                json={"model": model, "stream": False},
            )
            if resp.status_code != 200:
                return False, f"Pull failed at {base_url} (status {resp.status_code})"
            status = (resp.json() or {}).get("status", "")
            # Ollama returns {"status": "success"} on completion.
            if status and status != "success":
                return False, f"Pull did not complete. {status}"
            return True, "ok"
    except httpx.TimeoutException:
        return False, f"Pull timed out. Try a smaller model or run 'ollama pull {model}' manually."
    except (httpx.ConnectError, OSError) as exc:
        return False, f"Could not reach Ollama at {base_url}. {exc}"


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
    ram_gb = _get_system_ram_gb()
    recommended = _recommend_model(ram_gb)

    return OllamaStatus(
        installed=installed,
        running=running,
        models=models,
        recommended_model=recommended,
        system_ram_gb=round(ram_gb, 1) if ram_gb else None,
        available_models=VISION_MODELS,
        reachable_url=reachable_url,
    )


@router.post("/deploy", response_model=DeployStatus)
async def deploy_model(
    body: DeployRequest,
    _current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Deploy a vision model via Ollama and auto-register as provider.

    This endpoint orchestrates the full flow. check Ollama, start it
    if needed, pull the model, and create a Provider record.
    """
    model_name = body.model

    # Validate model name format (allow any model, not just curated list)
    if not model_name or "/" in model_name or ".." in model_name:
        return DeployStatus(stage="error", message="Invalid model name")

    # Decide how to reach Ollama. A local binary lets us serve + pull via
    # the CLI. Otherwise (typical in Docker), look for a reachable Ollama
    # server such as the bundled compose service and pull over HTTP. The
    # provider is registered at whichever URL actually serves the model.
    ollama_path = _find_ollama_binary()
    remote_url, _remote_models = await _detect_running()

    if ollama_path:
        # Local binary path. start the daemon if needed, pull via CLI.
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
                    return DeployStatus(stage="error", message="Ollama started but API not responding after 10 seconds")
            except (OSError, FileNotFoundError) as exc:
                return DeployStatus(stage="error", message=f"Failed to start Ollama. {str(exc)}")

        installed = await _get_installed_models()
        if model_name not in installed and not any(m.startswith(model_name.split(":")[0]) for m in installed if ":" in model_name):
            try:
                proc = await asyncio.create_subprocess_exec(
                    ollama_path, "pull", model_name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=600,  # 10 min timeout for large models
                )
                if proc.returncode != 0:
                    error_msg = stderr.decode().strip() if stderr else "Unknown error"
                    return DeployStatus(stage="error", message=f"Failed to pull {model_name}. {error_msg}")
            except asyncio.TimeoutError:
                return DeployStatus(stage="error", message=f"Model pull timed out after 10 minutes. Try running 'ollama pull {model_name}' manually.")
            except (OSError, FileNotFoundError) as exc:
                return DeployStatus(stage="error", message=f"Pull failed. {str(exc)}")
        provider_url = OLLAMA_URL

    elif remote_url:
        # No local binary, but a reachable Ollama server (bundled service or
        # one on the host/network). Pull over the HTTP API.
        installed = _remote_models
        if model_name not in installed and not any(m.startswith(model_name.split(":")[0]) for m in installed if ":" in model_name):
            ok, msg = await _pull_via_http(remote_url, model_name)
            if not ok:
                return DeployStatus(stage="error", message=msg)
        provider_url = remote_url

    else:
        return DeployStatus(
            stage="error",
            message=(
                "No Ollama found. Install it from https://ollama.com/download on the "
                "machine running Nurby, start the bundled service with "
                "`docker compose --profile local-ai up -d ollama`, or point a cloud "
                "provider in the previous step."
            ),
        )

    # Check if a provider already exists at this URL.
    result = await db.execute(
        select(Provider).where(Provider.kind == "ollama", Provider.base_url == provider_url)
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Update the model if different
        if existing.default_model != model_name:
            existing.default_model = model_name
            existing.active = True
            await db.commit()
        return DeployStatus(
            stage="done",
            message=f"{model_name} is ready. Updated existing Ollama provider.",
        )

    # Create provider record at the URL that serves the model.
    provider = Provider(
        name=f"Ollama ({model_name})",
        kind="ollama",
        base_url=provider_url,
        api_key=None,
        default_model=model_name,
        active=True,
    )
    db.add(provider)
    await db.commit()

    return DeployStatus(
        stage="done",
        message=f"{model_name} is ready. Provider auto-configured.",
    )
