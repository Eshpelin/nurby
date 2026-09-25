"""VLM prompt registry: list versions, promote, roll back (#218).

Promotion and rollback are a change to the ``prompt_versions`` app setting,
never a code edit. Only versions the registry already holds can be made
active, so the setting can never point a VLM call at text that is not
versioned and immutable.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.perception import prompt_registry as reg
from shared.app_settings import set_setting
from shared.auth import get_current_user, require_admin
from shared.models import User

router = APIRouter()


class ActivateRequest(BaseModel):
    version: str


def _describe(key: str, overrides: dict) -> dict:
    active = reg.select(key, overrides)
    return {
        "key": key,
        "default_version": reg.version_for(key),
        "active_version": active.version,
        "versions": [
            {"version": v, "sha": reg.content_hash(reg.text_for(key, v) or "")}
            for v in reg.known_versions(key)
        ],
    }


@router.get("")
async def list_prompts(_current_user: User = Depends(get_current_user)):
    overrides = await reg.active_overrides(fresh=True)
    return [_describe(key, overrides) for key in reg.REGISTRY]


@router.get("/{key}/versions/{version}")
async def get_prompt_version(key: str, version: str, _current_user: User = Depends(get_current_user)):
    text = reg.text_for(key, version)
    if text is None:
        raise HTTPException(status_code=404, detail="Unknown prompt version")
    return {"key": key, "version": version, "sha": reg.content_hash(text), "text": text}


@router.put("/{key}/active")
async def activate_prompt_version(
    key: str, body: ActivateRequest, _current_user: User = Depends(require_admin),
):
    """Promote (or roll back to) ``version`` for ``key``. Selecting the
    shipped default clears the override."""
    if key not in reg.REGISTRY:
        raise HTTPException(status_code=404, detail="Unknown prompt key")
    if reg.text_for(key, body.version) is None:
        raise HTTPException(status_code=400, detail="Unknown version for this prompt")
    overrides = dict(await reg.active_overrides(fresh=True))
    if body.version == reg.version_for(key):
        overrides.pop(key, None)
    else:
        overrides[key] = body.version
    await set_setting(reg.SETTING_KEY, overrides)
    reg.invalidate_cache()
    return _describe(key, overrides)
