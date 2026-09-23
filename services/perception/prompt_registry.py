"""Versioned VLM prompt registry (#218).

Every VLM pass records which prompt produced it (``ObservationVlmPass.
prompt_version``), so a caption or answer is attributable to an exact prompt,
and a golden-set scorecard (#214) can read "prompt v2, model X: 91%". For
that to mean anything, the version must move whenever the prompt text moves.

This registry pins, per lens, the current ``version`` and the ``sha`` of the
prompt text that version corresponds to. A drift test
(``tests/test_prompt_registry.py``) compares each recorded ``sha`` against the
live text in ``vlm_enrichment_worker.LENS_PROMPTS``; editing a prompt without
updating its ``sha`` and bumping its ``version`` fails that test. So a prompt
change can never ship silently unversioned.

The registry deliberately does not import the prompt text (the worker imports
this module, so importing back would be circular); it stores hashes only and
the test bridges the two.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1


@dataclass(frozen=True)
class PromptSpec:
    version: str
    sha: str  # sha1(prompt_text)[:12] of the text this version corresponds to


# lens -> current version + the hash of the text it was cut from.
# Bump `version` AND update `sha` together whenever a prompt's text changes.
REGISTRY: dict[str, PromptSpec] = {
    "attributes": PromptSpec("v1", "504b16acffd2"),
    "anomaly": PromptSpec("v1", "b755c2dc9e3a"),
    "temporal": PromptSpec("v1", "a6b74f34b752"),
    "summary": PromptSpec("v1", "5dfff24ed103"),
    "verify": PromptSpec("v1", "9ba6cced7732"),
    "repair": PromptSpec("v1", "51e07ebdd0d4"),
}

# Default version for any pass whose lens is not in the registry (e.g. the
# live first-pass caption produced outside the enrichment worker). Recording
# "v0-unregistered" is more honest than pretending it is "v1".
UNREGISTERED = "v0-unregistered"


def content_hash(text: str) -> str:
    """The 12-hex sha1 prefix used as a prompt's content fingerprint."""
    return sha1((text or "").encode()).hexdigest()[:12]


def version_for(lens: str) -> str:
    """The current prompt version for ``lens`` (never raises)."""
    spec = REGISTRY.get(lens)
    return spec.version if spec else UNREGISTERED
