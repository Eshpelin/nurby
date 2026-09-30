import pytest
from datetime import datetime, timezone

from services import recap


@pytest.mark.asyncio
async def test_person_recap_records_unscoped_usage(monkeypatch):
    provider = type("Provider", (), {"default_model": "vision-model"})()
    person = type("Person", (), {"id": "person-1", "display_name": "Sam", "relationship": None, "recap_prompt": None, "recap_model": None, "recap_provider": None})()
    usage = []

    async def pick_provider(_person):
        return "openai", provider

    async def call_vlm(*_args):
        return "Sam was seen near the front door."

    async def record(provider_arg, **kwargs):
        usage.append((provider_arg, kwargs))

    monkeypatch.setattr(recap, "_pick_provider", pick_provider)
    monkeypatch.setattr(recap, "_call_vlm", call_vlm)
    monkeypatch.setattr(recap, "record_vlm_usage", record)

    result = await recap._run_vlm_status(
        person,
        [{"camera": "Front door", "at": datetime.now(timezone.utc), "description": ""}],
    )

    assert result == "Sam was seen near the front door."
    assert len(usage) == 1
    assert usage[0][1]["workload"] == "person_recap"
    assert usage[0][1]["camera_id"] is None
    assert usage[0][1]["output_text"] == result


@pytest.mark.asyncio
async def test_person_recap_records_failed_attempt(monkeypatch):
    provider = type("Provider", (), {"default_model": "vision-model"})()
    person = type("Person", (), {"id": "person-1", "display_name": "Sam", "relationship": None, "recap_prompt": None, "recap_model": None, "recap_provider": None})()
    usage = []

    async def pick_provider(_person):
        return "openai", provider

    async def call_vlm(*_args):
        raise RuntimeError("provider unavailable")

    async def record(provider_arg, **kwargs):
        usage.append((provider_arg, kwargs))

    monkeypatch.setattr(recap, "_pick_provider", pick_provider)
    monkeypatch.setattr(recap, "_call_vlm", call_vlm)
    monkeypatch.setattr(recap, "record_vlm_usage", record)

    result = await recap._run_vlm_status(
        person,
        [{"camera": "Front door", "at": datetime.now(timezone.utc), "description": ""}],
    )

    assert result.startswith("Sam last seen")
    assert usage[0][1]["workload"] == "person_recap"
    assert usage[0][1]["succeeded"] is False
