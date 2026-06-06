"""Unit tests for idle VLM enrichment decision logic.

The DB-touching paths (candidate query, pass storage) are verified live
against postgres. these cover the pure reduce rule that decides whether a
new pass becomes authoritative.
"""

from __future__ import annotations

from services.perception.vlm_enrichment_worker import (
    EnrichmentManager,
    build_attributes,
)


def test_build_attributes_from_detections_and_text():
    text = "A white SUV with plate ABC1234 is parked in the driveway at night."
    dets = [{"label": "car"}, {"label": "person"}, {"label": "person"}]
    a = build_attributes(text, dets)
    assert a["people_count"] == 2
    assert {"label": "car", "count": 1} in a["objects"]
    assert {"label": "person", "count": 2} in a["objects"]
    assert "white" in a["colors"]
    assert "night" in a["time_of_day"]
    assert "ABC1234" in a["text_seen"]


def test_build_attributes_empty_text_is_safe():
    a = build_attributes(None, [])
    assert a["people_count"] == 0
    assert a["objects"] == []
    assert a["colors"] == []


def test_text_seen_requires_a_digit():
    # plain uppercase words should not be mistaken for plates/signage codes
    a = build_attributes("A PERSON WALKS HERE", [])
    assert a["text_seen"] == []


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
