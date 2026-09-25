"""Versioned VLM prompt registry (#218).

Enforces the contract: every registered lens prompt's recorded hash matches
the live text, and every pass-producing lens is registered with a version.
Editing a prompt without bumping its version + hash fails here, so a prompt
change can never ship silently unversioned.
"""

from services.agent.analyzer import ANALYZER_SYSTEM_PROMPT
from services.perception import prompt_registry as reg
from services.perception.actions import CLASSIFY_SYSTEM_PROMPT
from services.perception.vlm import SYSTEM_PROMPT as LIVE_CAPTION_PROMPT
from services.perception.vlm_enrichment_worker import (
    LENS_PROMPTS,
    REPAIR_PROMPT,
    VERIFY_PROMPT,
)

# Map registry keys to their live prompt text.
_LIVE = {
    **{lens: text for lens, text in LENS_PROMPTS.items()},
    "verify": VERIFY_PROMPT,
    "repair": REPAIR_PROMPT,
    "live_caption": LIVE_CAPTION_PROMPT,
    "action_classify": CLASSIFY_SYSTEM_PROMPT,
    "agent_analyzer": ANALYZER_SYSTEM_PROMPT,
}


def test_every_registry_entry_matches_live_prompt_text():
    for lens, spec in reg.REGISTRY.items():
        assert lens in _LIVE, f"registry has {lens} but no live prompt"
        expected = reg.content_hash(_LIVE[lens])
        assert spec.sha == expected, (
            f"prompt '{lens}' changed (sha {expected}) but registry still pins "
            f"{spec.sha} at {spec.version}. Bump the version and update the sha."
        )


def test_every_live_prompt_is_registered():
    # Every production VLM prompt (enrichment, live caption, action
    # classification, agent analyzer) must carry a version.
    assert set(_LIVE) == set(reg.REGISTRY)
    for key in reg.REGISTRY:
        assert reg.live_text(key) == _LIVE[key]


def test_extra_versions_never_shadow_default():
    for key, versions in reg.EXTRA_VERSIONS.items():
        assert key in reg.REGISTRY
        assert reg.REGISTRY[key].version not in versions


def test_every_lens_prompt_is_registered():
    for lens in LENS_PROMPTS:
        assert lens in reg.REGISTRY, f"lens '{lens}' is not versioned in the registry"


def test_version_for_known_and_unknown():
    assert reg.version_for("attributes") == "v1"
    # An unregistered lens (e.g. the live first-pass caption) is honestly
    # labelled, not silently claimed as v1.
    assert reg.version_for("live") == reg.UNREGISTERED


def test_worker_stamps_registry_version(monkeypatch):
    # The enrichment worker must stamp version_for(lens), not a hardcoded v1.
    import services.perception.vlm_enrichment_worker as worker

    assert worker.version_for is reg.version_for


def test_pass_model_exposes_exact_prompt_provenance():
    from shared.models import ObservationVlmPass

    assert {"prompt_key", "prompt_version", "prompt_text"}.issubset(
        ObservationVlmPass.__table__.columns.keys()
    )


# ── Selection: promotion / rollback is a setting change ──


def test_select_defaults_to_shipped_version():
    ref = reg.select("summary", {})
    assert (ref.key, ref.version, ref.text) == ("summary", "v1", LENS_PROMPTS["summary"])


def test_select_honours_override_to_known_version(monkeypatch):
    monkeypatch.setitem(reg.EXTRA_VERSIONS, "summary", {"v2": "candidate summary text"})
    ref = reg.select("summary", {"summary": "v2"})
    assert (ref.version, ref.text) == ("v2", "candidate summary text")
    # Rolling back is just pointing the setting at the old version again.
    assert reg.select("summary", {"summary": "v1"}).text == LENS_PROMPTS["summary"]
    assert reg.known_versions("summary") == ["v1", "v2"]


def test_select_ignores_unknown_override_version():
    ref = reg.select("summary", {"summary": "v99"})
    assert ref.version == "v1"
    assert ref.text == LENS_PROMPTS["summary"]


def test_text_for_unknown_key_or_version_is_none():
    assert reg.text_for("nope", "v1") is None
    assert reg.text_for("summary", "v99") is None


def test_custom_prompt_is_versioned_by_content():
    a = reg.custom("live_caption", "Only describe the driveway.")
    b = reg.custom("live_caption", "Only describe the driveway.")
    c = reg.custom("live_caption", "Only describe the porch.")
    assert a.key == "live_caption/custom"
    assert a.version == b.version != c.version
    assert len(a.version) <= 24  # fits observations.caption_prompt_version


def test_resolve_reads_setting_and_filters_garbage(monkeypatch):
    import asyncio

    import shared.app_settings as app_settings

    monkeypatch.setitem(reg.EXTRA_VERSIONS, "verify", {"v2": "stricter verify"})

    async def fake_get_setting(key, default=None):
        assert key == reg.SETTING_KEY
        return {"verify": "v2", "not_a_prompt": "v3"}

    monkeypatch.setattr(app_settings, "get_setting", fake_get_setting)
    reg.invalidate_cache()
    try:
        ref = asyncio.run(reg.resolve("verify"))
        assert (ref.version, ref.text) == ("v2", "stricter verify")
        assert asyncio.run(reg.active_overrides(fresh=True)) == {"verify": "v2"}
    finally:
        reg.invalidate_cache()


def test_resolve_falls_back_when_setting_unreadable(monkeypatch):
    import asyncio

    import shared.app_settings as app_settings

    async def broken(key, default=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(app_settings, "get_setting", broken)
    reg.invalidate_cache()
    try:
        assert asyncio.run(reg.resolve("anomaly")).version == "v1"
    finally:
        reg.invalidate_cache()


# ── Stamping at call sites ──


def test_action_classification_is_stamped(monkeypatch):
    import asyncio

    import numpy as np

    from services.perception import actions

    seen = {}

    class FakeVLM:
        async def classify_action(self, crop, provider, prompt=None):
            seen["prompt"] = prompt
            return '{"action": "walking", "posture": "standing", "confidence": 0.9}'

    async def fake_resolve(key):
        return reg.PromptRef(key, "v7", "classify text v7")

    monkeypatch.setattr(reg, "resolve", fake_resolve)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    out = asyncio.run(actions.classify_crop(FakeVLM(), frame, [10, 10, 60, 90], object()))
    assert out["action"] == "walking"
    assert (out["prompt_key"], out["prompt_version"]) == ("action_classify", "v7")
    assert seen["prompt"].text == "classify text v7"


def test_live_caption_prompt_uses_custom_or_registry(monkeypatch):
    import asyncio

    from services.perception.vlm_queue import caption_prompt

    custom = asyncio.run(caption_prompt("Watch the gate."))
    assert custom.key == "live_caption/custom" and custom.text == "Watch the gate."

    async def fake_resolve(key):
        return reg.PromptRef(key, "v2", "promoted caption")

    monkeypatch.setattr(reg, "resolve", fake_resolve)
    ref = asyncio.run(caption_prompt(None))
    assert (ref.key, ref.version, ref.text) == ("live_caption", "v2", "promoted caption")


def test_agent_cache_key_is_scoped_by_prompt_version():
    from services.agent.analyzer import (
        _cached_prompt_matches,
        prompt_scoped_hash,
        question_hash,
    )

    v1 = reg.PromptRef("agent_analyzer", "v1", "x")
    v2 = reg.PromptRef("agent_analyzer", "v2", "y")
    # v1 keeps the legacy hash so existing cache rows stay valid.
    assert prompt_scoped_hash("Is the door open?", v1) == question_hash("Is the door open?")
    assert prompt_scoped_hash("Is the door open?", v2) != question_hash("Is the door open?")
    # An unstamped cached answer was written by v1.
    assert _cached_prompt_matches({"response_json": {}}, v1)
    assert not _cached_prompt_matches({"response_json": {}}, v2)
    assert _cached_prompt_matches({"response_json": {"prompt_version": "v2"}}, v2)


def test_models_carry_caption_and_action_provenance():
    from shared.models import Observation, ObservationAction

    assert {"caption_prompt_key", "caption_prompt_version", "caption_prompt_text"}.issubset(
        Observation.__table__.columns.keys()
    )
    assert {"prompt_key", "prompt_version"}.issubset(ObservationAction.__table__.columns.keys())


def test_provenance_entry_resolves_text_and_labels_legacy():
    from services.api.routes.observations import _prompt_entry

    assert _prompt_entry("summary", "v1", None)["text"] == LENS_PROMPTS["summary"]
    assert _prompt_entry("summary", "v1", "stored")["text"] == "stored"
    legacy = _prompt_entry(None, None, None)
    assert legacy == {"key": "legacy/unknown", "version": "legacy", "text": None}
    assert _prompt_entry("legacy/unknown", "v1", None)["key"] == "legacy/unknown"


def test_promote_and_rollback_route_writes_only_known_versions(monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from services.api.routes import prompts as route

    monkeypatch.setitem(reg.EXTRA_VERSIONS, "anomaly", {"v2": "candidate anomaly"})
    store = {}

    async def fake_set(key, value):
        store[key] = value

    async def fake_overrides(*, fresh=False):
        return dict(store.get(reg.SETTING_KEY, {}))

    monkeypatch.setattr(route, "set_setting", fake_set)
    monkeypatch.setattr(reg, "active_overrides", fake_overrides)

    out = asyncio.run(route.activate_prompt_version("anomaly", route.ActivateRequest(version="v2"), None))
    assert store[reg.SETTING_KEY] == {"anomaly": "v2"}
    assert out["active_version"] == "v2"

    # Rollback to the shipped default clears the override.
    out = asyncio.run(route.activate_prompt_version("anomaly", route.ActivateRequest(version="v1"), None))
    assert store[reg.SETTING_KEY] == {}
    assert out["active_version"] == "v1"

    with pytest.raises(HTTPException) as bad_version:
        asyncio.run(route.activate_prompt_version("anomaly", route.ActivateRequest(version="v9"), None))
    assert bad_version.value.status_code == 400
    with pytest.raises(HTTPException) as bad_key:
        asyncio.run(route.activate_prompt_version("nope", route.ActivateRequest(version="v1"), None))
    assert bad_key.value.status_code == 404
