"""Severity taxonomy and incident lifecycle triggers."""

import asyncio

from tests._engine_helpers import FakeRule, install_engine


def _incident_ended(duration=120.0, occurrences=4, kind="person", camera="cam-1"):
    return {
        "event_kind": "incident",
        "incident_event": "ended",
        "incident_id": "i-1",
        "camera_id": camera,
        "camera_name": "Porch",
        "signature_kind": kind,
        "who_or_what": "person:cluster-9",
        "timestamp": "2026-06-11T00:10:00+00:00",
        "started_at": "2026-06-11T00:08:00+00:00",
        "duration_seconds": duration,
        "occurrence_count": occurrences,
        "summary": "Someone lingered by the porch for two minutes.",
    }


def _incident_started(kind="person", camera="cam-1"):
    return {
        "event_kind": "incident",
        "incident_event": "started",
        "incident_id": "i-1",
        "camera_id": camera,
        "camera_name": "Porch",
        "signature_kind": kind,
        "who_or_what": "person:cluster-9",
        "timestamp": "2026-06-11T00:08:00+00:00",
        "occurrence_count": 1,
    }


# ── incident triggers ─────────────────────────────────────────────

def test_incident_started_fires(monkeypatch):
    rule = FakeRule(name="r", trigger_pattern={"type": "incident_started"})
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_incident_started()))
    assert rec.call_count == 1
    asyncio.run(eng.evaluate(_incident_ended()))
    assert rec.call_count == 1  # ended payload does not fire started


def test_incident_ended_thresholds(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={
            "type": "incident_ended",
            "min_duration_seconds": 60,
            "min_occurrences": 3,
        },
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_incident_ended(duration=30)))
    asyncio.run(eng.evaluate(_incident_ended(occurrences=2)))
    assert rec.call_count == 0
    asyncio.run(eng.evaluate(_incident_ended(duration=120, occurrences=4)))
    assert rec.call_count == 1


def test_incident_kind_and_camera_filters(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={
            "type": "incident_started",
            "signature_kind": "vehicle",
            "camera_id": "cam-1",
        },
    )
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_incident_started(kind="person")))
    asyncio.run(eng.evaluate(_incident_started(kind="vehicle", camera="cam-2")))
    assert rec.call_count == 0
    asyncio.run(eng.evaluate(_incident_started(kind="vehicle")))
    assert rec.call_count == 1


def test_incident_payload_does_not_fire_observation_rules(monkeypatch):
    rule = FakeRule(name="r", trigger_pattern={"type": "any"})
    eng, rec = install_engine(monkeypatch, [rule])
    asyncio.run(eng.evaluate(_incident_started()))
    assert rec.call_count == 0


# ── severity stamping ─────────────────────────────────────────────

def test_event_carries_rule_severity(monkeypatch):
    rule = FakeRule(
        name="r",
        trigger_pattern={"type": "any"},
        severity="detection",
    )
    eng, rec = install_engine(monkeypatch, [rule])
    stored = {}

    async def fake_store(rule_id, observation_id, payload, severity="alert"):
        stored["severity"] = severity
        import uuid as _uuid

        return _uuid.uuid4()

    monkeypatch.setattr("services.events.firing.store_event", fake_store)
    asyncio.run(eng.evaluate({"camera_id": "cam"}))
    assert stored["severity"] == "detection"
