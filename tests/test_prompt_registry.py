"""Versioned VLM prompt registry (#218).

Enforces the contract: every registered lens prompt's recorded hash matches
the live text, and every pass-producing lens is registered with a version.
Editing a prompt without bumping its version + hash fails here, so a prompt
change can never ship silently unversioned.
"""

from services.perception import prompt_registry as reg
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
}


def test_every_registry_entry_matches_live_prompt_text():
    for lens, spec in reg.REGISTRY.items():
        assert lens in _LIVE, f"registry has {lens} but no live prompt"
        expected = reg.content_hash(_LIVE[lens])
        assert spec.sha == expected, (
            f"prompt '{lens}' changed (sha {expected}) but registry still pins "
            f"{spec.sha} at {spec.version}. Bump the version and update the sha."
        )


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
