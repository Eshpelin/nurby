"""Magic model setup (#304): installed-first recommendation, proactive
Ollama version compatibility, and byte-honest progress. The recommend /
seed / parse helpers are pure, so the whole contract is testable without
an Ollama server.
"""

import pytest

from services.api.routes import ollama_deploy as od


@pytest.fixture(autouse=True)
def _clean_unsupported_families():
    od._unsupported_families.clear()
    yield
    od._unsupported_families.clear()


# ── version parsing and proactive seeding ──

def test_parse_version():
    assert od._parse_version("0.18.4") == (0, 18, 4)
    assert od._parse_version("v0.5") == (0, 5)
    assert od._parse_version(" 0.18.4-rc1 ") == (0, 18, 4)
    assert od._parse_version(None) is None
    assert od._parse_version("garbage") is None


def test_old_version_seeds_unsupported_families(monkeypatch):
    monkeypatch.setattr(od, "_re", __import__("re"))
    od._seed_unsupported_families_from_version("0.17.9")
    assert "Gemma 4" in od._unsupported_families
    assert "Gemma" not in od._unsupported_families  # gemma3 is old enough


def test_current_version_seeds_nothing(monkeypatch):
    od._seed_unsupported_families_from_version("0.18.0")
    assert od._unsupported_families == set()
    od._seed_unsupported_families_from_version("1.2.3")
    assert od._unsupported_families == set()


def test_unparseable_version_seeds_nothing():
    od._seed_unsupported_families_from_version(None)
    od._seed_unsupported_families_from_version("banana")
    assert od._unsupported_families == set()


def test_recommendation_skips_seeded_family(monkeypatch):
    od._seed_unsupported_families_from_version("0.17.9")
    name, installed = od._recommend_model(48, [])
    assert (name, installed) == ("gemma3:27b", False)  # best Gemma 3, not Gemma 4


# ── installed-first recommendation ──

def test_prefers_capable_installed_model(monkeypatch):
    # 32 GB machine already carrying the 4B model: magic must download
    # nothing instead of pulling the 8.5 GB catalog headliner.
    monkeypatch.setattr(od, "_re", __import__("re"))
    assert od._recommend_model(32, ["gemma3:4b", "moondream"]) == ("gemma3:4b", True)


def test_installed_model_that_fits_ram_wins_over_bigger_download(monkeypatch):
    monkeypatch.setattr(od, "_re", __import__("re"))
    # 16 GB machine: catalog headliner fits, but the installed 12B wins.
    assert od._recommend_model(16, ["gemma3:12b"]) == ("gemma3:12b", True)


def test_downloads_when_nothing_installed(monkeypatch):
    monkeypatch.setattr(od, "_re", __import__("re"))
    assert od._recommend_model(32, []) == ("gemma4:12b", False)
    # 8 GB: the Gemma 4 variants need headroom the machine does not have;
    # the first catalog entry that fits is the 4B Gemma 3.
    assert od._recommend_model(8, []) == ("gemma3:4b", False)


def test_exact_installed_match_not_prefix(monkeypatch):
    monkeypatch.setattr(od, "_re", __import__("re"))
    # Only gemma3:12b is present: the 4B recommendation must NOT claim it
    # is installed (the old prefix match said otherwise).
    assert od._installed_exact("gemma3:4b", ["gemma3:12b"]) is False
    assert od._recommend_model(16, ["gemma3:12b"]) == ("gemma3:12b", True)
    # 8 GB cannot headroom a 12B model even though it is installed: the
    # recommendation falls to a model that fits, marked not-installed.
    assert od._recommend_model(8, ["gemma3:12b"]) == ("gemma3:4b", False)


def test_tiny_ram_falls_back_to_smallest_installed(monkeypatch):
    monkeypatch.setattr(od, "_re", __import__("re"))
    name, installed = od._recommend_model(2, ["moondream", "gemma3:1b"])
    assert installed is True
    assert name in ("gemma3:1b", "moondream")


def test_no_ram_data_still_prefers_installed():
    assert od._recommend_model(None, ["moondream"]) == ("moondream", True)
    assert od._recommend_model(None, []) == ("gemma3:4b", False)


# ── honest progress ──

def test_parse_bytes_progress():
    assert od._parse_bytes_progress("pulling ⣟ 1.2 GB/3.3 GB") == (1_200_000_000, 3_300_000_000)
    assert od._parse_bytes_progress("800 MB/3.3 GB") == (800_000_000, 3_300_000_000)
    assert od._parse_bytes_progress("no numbers here") is None
    assert od._parse_bytes_progress("63%") is None


def test_download_message_with_bytes():
    message = od._download_message("gemma3:4b", 1_200_000_000, 3_300_000_000, 36.4)
    assert message == "Downloading gemma3:4b — 1.2 GB of 3.3 GB (36%)"


def test_download_message_degrades_gracefully():
    assert od._download_message("gemma3:4b", None, None, 12.0) == \
        "Downloading gemma3:4b (12% of about 3.3 GB)"
    assert od._download_message("gemma3:4b", None, None, None) == \
        "Downloading gemma3:4b (about 3.3 GB)"
    assert od._download_message("totally:unknown", None, None, None) == \
        "Downloading totally:unknown"
    small = od._download_message("small:model", 800_000, 1_000_000, None)
    assert small == "Downloading small:model — 0.8 MB of 1 MB (80%)"


def test_status_model_documents_recommended_installed():
    assert od.OllamaStatus.model_fields["recommended_installed"].default is False
    assert od.DeployStatus.model_fields["already_installed"].default is False
