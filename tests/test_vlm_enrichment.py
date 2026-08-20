"""Unit tests for idle VLM enrichment pure logic.

DB-touching paths (pass storage, summary repoint, candidate query) are
verified live against postgres. these cover the lens sequencing and the
deterministic attribute extraction.
"""

from __future__ import annotations

import numpy as np
import pytest

from services.perception.vlm_enrichment_worker import (
    EnrichmentManager,
    build_attributes,
    next_lens,
    pick_fallback_pass,
)

# ---- lens sequencing ----------------------------------------------------

def test_first_lens_is_attributes():
    assert next_lens(set(), has_recording=False, summary_stale=True) == "attributes"


def test_temporal_runs_only_with_recording():
    have = {"attributes"}
    assert next_lens(have, has_recording=True, summary_stale=True) == "temporal"
    # no recording -> skip temporal, go to anomaly
    assert next_lens(have, has_recording=False, summary_stale=True) == "anomaly"


def test_summary_after_raw_passes_when_stale():
    have = {"attributes", "anomaly"}
    assert next_lens(have, has_recording=False, summary_stale=True) == "summary"


def test_no_summary_when_not_stale():
    have = {"attributes", "anomaly", "summary"}
    assert next_lens(have, has_recording=False, summary_stale=False) is None


def test_resummarize_when_new_raw_pass_lands():
    # a temporal pass arrived after the last summary -> summary is stale again
    have = {"attributes", "anomaly", "summary", "temporal"}
    assert next_lens(have, has_recording=True, summary_stale=True) == "summary"


def test_no_summary_before_any_raw_pass():
    assert next_lens(set(), has_recording=False, summary_stale=True) == "attributes"


# ---- attribute extraction ----------------------------------------------

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
    a = build_attributes("A PERSON WALKS HERE", [])
    assert a["text_seen"] == []


# ---- fallback pass selection -------------------------------------------


def test_fallback_prefers_attributes():
    passes = [
        (1, "attributes", "A red van at the curb."),
        (2, "temporal", "The van pulls away."),
        (3, "anomaly", "Nothing unusual."),
    ]
    assert pick_fallback_pass(passes) == ("attributes", "A red van at the curb.")


def test_fallback_skips_empty_anomaly_and_blank_text():
    passes = [(1, "attributes", "   "), (2, "anomaly", "Nothing unusual")]
    assert pick_fallback_pass(passes) is None
    # A real anomaly finding IS usable.
    passes.append((3, "anomaly", "The side gate is standing open."))
    assert pick_fallback_pass(passes) == ("anomaly", "The side gate is standing open.")


def test_fallback_ignores_summary_passes_and_keeps_newest_per_lens():
    passes = [
        (1, "attributes", "old text"),
        (2, "summary", "a synthesis"),
        (3, "attributes", "new text"),
    ]
    assert pick_fallback_pass(passes) == ("attributes", "new text")


def test_fallback_of_nothing_is_none():
    assert pick_fallback_pass([]) is None


# ---- the verifier is wired to consequences (G1, issue #127) -------------


class _FakeVLM:
    """Returns queued describe() replies in order and records the prompts."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.system_prompts = []

    async def describe(self, frame, detections, provider, system_prompt=None,
                       extra_context=None, max_tokens=None, **kw):
        self.system_prompts.append(system_prompt)
        return self.replies.pop(0) if self.replies else None


def _manager(replies, monkeypatch):
    """An EnrichmentManager with the VLM, frame load and DB writes stubbed."""
    import services.perception.vlm_enrichment_worker as w

    mgr = EnrichmentManager()
    mgr._vlm = _FakeVLM(replies)
    monkeypatch.setattr(w, "_load_frame", lambda thumb: np.zeros((8, 8, 3), dtype=np.uint8))

    writes, appends = [], []

    async def _write_summary(obs_id, summary, attributes, embedding, provider):
        writes.append({"summary": summary, "attributes": attributes, "embedding": embedding})

    async def _append_pass(obs_id, lens, provider, description, attributes):
        appends.append({"lens": lens, "description": description, "attributes": attributes})

    async def _embed(text):
        return [0.0]

    mgr._write_summary = _write_summary
    mgr._append_pass = _append_pass
    mgr._embed = _embed
    return mgr, writes, appends


PASSES = [
    (1, "attributes", "A red van at the curb."),
    (2, "anomaly", "Nothing unusual."),
]


@pytest.mark.asyncio
async def test_supported_summary_is_written_unchanged(monkeypatch):
    # describe -> summary, verify -> OK.
    mgr, writes, appends = _manager(["A red van sits at the curb.", "OK"], monkeypatch)
    assert await mgr._run_summary("obs", "t.jpg", [], PASSES, object()) is True
    assert len(writes) == 1
    assert writes[0]["summary"] == "A red van sits at the curb."
    assert writes[0]["attributes"]["verify"] == {"status": "ok"}
    assert writes[0]["embedding"] is not None
    assert appends == []


@pytest.mark.asyncio
async def test_unsupported_summary_is_repaired_and_the_repair_is_published(monkeypatch):
    mgr, writes, appends = _manager(
        [
            "A red van sits at the curb and the driver waves.",  # summary
            "UNSUPPORTED the driver waving",                     # verify
            "A red van sits at the curb.",                       # repair
            "OK",                                                # re-verify
        ],
        monkeypatch,
    )
    assert await mgr._run_summary("obs", "t.jpg", [], PASSES, object()) is True
    assert len(writes) == 1
    # The rejected text never reaches the caption.
    assert writes[0]["summary"] == "A red van sits at the curb."
    assert writes[0]["attributes"]["verify"] == {"status": "ok", "repair": "ok"}
    # And the repair round was actually a repair prompt, not a re-summary.
    import services.perception.vlm_enrichment_worker as w

    assert mgr._vlm.system_prompts[2] == w.REPAIR_PROMPT


@pytest.mark.asyncio
async def test_unrepairable_summary_falls_back_to_a_raw_pass(monkeypatch):
    mgr, writes, appends = _manager(
        [
            "A red van sits at the curb and the driver waves.",  # summary
            "UNSUPPORTED the driver waving",                     # verify
            "A red van and a waving driver.",                    # repair
            "UNSUPPORTED still the waving",                      # re-verify
        ],
        monkeypatch,
    )
    assert await mgr._run_summary("obs", "t.jpg", [], PASSES, object()) is True
    assert len(writes) == 1
    assert writes[0]["summary"] == "A red van at the curb."
    verify = writes[0]["attributes"]["verify"]
    assert verify["repair"] == "failed"
    assert verify["downgraded_to"] == "attributes"


@pytest.mark.asyncio
async def test_unrepairable_with_no_usable_raw_pass_writes_no_caption(monkeypatch):
    mgr, writes, appends = _manager(
        [
            "A driver waves from a red van.",  # summary
            "UNSUPPORTED all of it",           # verify
            "A driver waves.",                 # repair
            "UNSUPPORTED still",               # re-verify
        ],
        monkeypatch,
    )
    only_empty_anomaly = [(1, "anomaly", "Nothing unusual.")]
    assert await mgr._run_summary("obs", "t.jpg", [], only_empty_anomaly, object()) is True
    # Nothing published: no caption move, no embedding.
    assert writes == []
    # But the attempt is recorded so the observation stops looking stale.
    assert len(appends) == 1
    assert appends[0]["lens"] == "summary"
    assert appends[0]["description"] is None
    assert appends[0]["attributes"]["verify"]["repair"] == "failed"


@pytest.mark.asyncio
async def test_empty_repair_reply_falls_back_without_a_second_verify(monkeypatch):
    mgr, writes, appends = _manager(
        [
            "A red van and a waving driver.",  # summary
            "UNSUPPORTED the waving",          # verify
            "",                                # repair returns nothing
        ],
        monkeypatch,
    )
    assert await mgr._run_summary("obs", "t.jpg", [], PASSES, object()) is True
    assert writes[0]["summary"] == "A red van at the curb."
    assert writes[0]["attributes"]["verify"]["repair"] == "failed"


@pytest.mark.asyncio
async def test_unclear_verdict_is_still_published(monkeypatch):
    # 'unclear' is not a detected hallucination, so behavior is unchanged.
    mgr, writes, appends = _manager(["A red van at the curb.", "hmm maybe"], monkeypatch)
    assert await mgr._run_summary("obs", "t.jpg", [], PASSES, object()) is True
    assert writes[0]["attributes"]["verify"]["status"] == "unclear"
    assert "repair" not in writes[0]["attributes"]["verify"]


# ---- the anomaly lens gets a baseline to compare against (G2, #129) -----


@pytest.mark.asyncio
async def test_anomaly_lens_receives_the_baseline_context(monkeypatch):
    mgr, writes, appends = _manager(["The side gate is standing open."], monkeypatch)
    seen = {}

    async def _ctx(camera_id, ts, objects_blob, persons_blob, obs_id):
        seen["args"] = (camera_id, obs_id)
        return "NORMAL FOR THIS CAMERA at this time of day, from 40 past frames:"

    mgr._anomaly_context = _ctx

    captured = {}
    real_describe = mgr._vlm.describe

    async def _describe(frame, detections, provider, system_prompt=None,
                        extra_context=None, max_tokens=None, **kw):
        captured["extra_context"] = extra_context
        return await real_describe(frame, detections, provider,
                                   system_prompt=system_prompt,
                                   extra_context=extra_context,
                                   max_tokens=max_tokens, **kw)

    mgr._vlm.describe = _describe

    ok = await mgr._run_raw_lens("anomaly", "obs", "cam", "ts", "t.jpg", [],
                                 object(), {"objects": []}, {"faces": []})
    assert ok is True
    assert captured["extra_context"].startswith("NORMAL FOR THIS CAMERA")
    assert seen["args"] == ("cam", "obs")
    assert appends[0]["lens"] == "anomaly"


@pytest.mark.asyncio
async def test_anomaly_lens_runs_unchanged_when_there_is_no_baseline(monkeypatch):
    mgr, writes, appends = _manager(["Nothing unusual."], monkeypatch)

    async def _ctx(*a, **kw):
        return None

    mgr._anomaly_context = _ctx

    captured = {}

    async def _describe(frame, detections, provider, system_prompt=None,
                        extra_context=None, max_tokens=None, **kw):
        captured["extra_context"] = extra_context
        return "Nothing unusual."

    mgr._vlm.describe = _describe

    assert await mgr._run_raw_lens("anomaly", "obs", "cam", "ts", "t.jpg", [],
                                   object(), None, None) is True
    assert captured["extra_context"] is None


@pytest.mark.asyncio
async def test_attributes_lens_gets_no_baseline_context(monkeypatch):
    mgr, writes, appends = _manager(["A red van at the curb."], monkeypatch)

    async def _boom(*a, **kw):
        raise AssertionError("the baseline is for the anomaly lens only")

    mgr._anomaly_context = _boom

    captured = {}

    async def _describe(frame, detections, provider, system_prompt=None,
                        extra_context=None, max_tokens=None, **kw):
        captured["extra_context"] = extra_context
        return "A red van at the curb."

    mgr._vlm.describe = _describe

    assert await mgr._run_raw_lens("attributes", "obs", "cam", "ts", "t.jpg", [],
                                   object(), None, None) is True
    assert captured["extra_context"] is None
    assert appends[0]["attributes"]["source"] == "attributes-pass-v1"


# ---- the temporal lens gets the episode arc (G3, #130) -----------------


@pytest.mark.asyncio
async def test_temporal_lens_receives_the_episode_context(monkeypatch):
    mgr, writes, appends = _manager(["The man carries a box to the door."], monkeypatch)

    async def _montage(camera_id, ts, frame):
        return frame

    async def _episode(obs_id, camera_id, ts):
        return "THIS FRAME CONTINUES AN EPISODE already in progress on this camera."

    mgr._temporal_montage = _montage
    mgr._episode_context = _episode

    captured = {}

    async def _describe(frame, detections, provider, system_prompt=None,
                        extra_context=None, max_tokens=None, **kw):
        captured["extra_context"] = extra_context
        return "The man carries a box to the door."

    mgr._vlm.describe = _describe

    assert await mgr._run_raw_lens("temporal", "obs", "cam", "ts", "t.jpg", [],
                                   object(), None, None) is True
    assert captured["extra_context"].startswith("THIS FRAME CONTINUES AN EPISODE")
    assert appends[0]["lens"] == "temporal"


@pytest.mark.asyncio
async def test_temporal_lens_runs_unchanged_for_a_standalone_frame(monkeypatch):
    mgr, writes, appends = _manager(["A cat crosses the step."], monkeypatch)

    async def _montage(camera_id, ts, frame):
        return frame

    async def _episode(obs_id, camera_id, ts):
        return None

    mgr._temporal_montage = _montage
    mgr._episode_context = _episode

    captured = {}

    async def _describe(frame, detections, provider, system_prompt=None,
                        extra_context=None, max_tokens=None, **kw):
        captured["extra_context"] = extra_context
        return "A cat crosses the step."

    mgr._vlm.describe = _describe

    assert await mgr._run_raw_lens("temporal", "obs", "cam", "ts", "t.jpg", [],
                                   object(), None, None) is True
    assert captured["extra_context"] is None


@pytest.mark.asyncio
async def test_no_montage_means_no_episode_lookup(monkeypatch):
    """A temporal pass with no neighbouring frames is recorded empty, and must
    not pay for an episode query it will never use."""
    mgr, writes, appends = _manager([], monkeypatch)

    async def _montage(camera_id, ts, frame):
        return None

    async def _boom(*a, **kw):
        raise AssertionError("no episode lookup without a montage")

    mgr._temporal_montage = _montage
    mgr._episode_context = _boom

    assert await mgr._run_raw_lens("temporal", "obs", "cam", "ts", "t.jpg", [],
                                   object(), None, None) is True
    assert appends[0] == {"lens": "temporal", "description": None, "attributes": None}
