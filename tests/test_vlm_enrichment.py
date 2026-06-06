"""Unit tests for idle VLM enrichment decision logic.

The DB-touching paths (candidate query, pass storage) are verified live
against postgres. these cover the pure reduce rule that decides whether a
new pass becomes authoritative.
"""

from __future__ import annotations

from services.perception.vlm_enrichment_worker import EnrichmentManager


def test_promote_when_caption_missing():
    assert EnrichmentManager.should_promote(None, 40) is True
    assert EnrichmentManager.should_promote("", 40) is True
    assert EnrichmentManager.should_promote("   ", 40) is True


def test_promote_when_caption_thin():
    assert EnrichmentManager.should_promote("a person", 40) is True


def test_append_when_caption_rich():
    rich = "A man in a green jacket walks toward the front door carrying a parcel."
    assert len(rich) >= 40
    assert EnrichmentManager.should_promote(rich, 40) is False


def test_threshold_is_inclusive_boundary():
    exactly_40 = "x" * 40
    # length == min_len is not below the threshold, so it is not thin
    assert EnrichmentManager.should_promote(exactly_40, 40) is False
    assert EnrichmentManager.should_promote("x" * 39, 40) is True
