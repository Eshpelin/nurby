"""The tool registry is split across modules. These tests hold the seams.

``services/agent/tools`` used to be one 3,300-line module. Splitting it
introduced two ways to break things quietly: a tool could stop being
registered, or a tool module could start reading the camera access filter
by name at import time, which would put it outside the reach of the one
place a caller replaces it. Neither failure shows up in a normal run.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import pytest

import services.agent.tools as tools_mod
from services.agent.tools import _common as tools_common


def _tool_modules():
    """Every submodule of the package that defines at least one tool."""
    return [
        importlib.import_module(f"services.agent.tools.{m.name}")
        for m in pkgutil.iter_modules(tools_mod.__path__)
    ]


def test_every_registered_tool_is_importable_from_the_package():
    for entry in tools_mod.TOOL_REGISTRY:
        name = entry["name"]
        assert hasattr(tools_mod, name), f"{name} is registered but not re-exported"
        assert getattr(tools_mod, name) is entry["fn"], (
            f"{name} re-exports a different object than the registry calls"
        )


def test_the_registry_and_its_index_stay_in_step():
    assert len(tools_mod._REGISTRY_BY_NAME) == len(tools_mod.TOOL_REGISTRY)
    for entry in tools_mod.TOOL_REGISTRY:
        assert tools_mod.get_tool(entry["name"]) is entry


def test_every_tool_declares_a_side_effect_and_a_cost():
    for entry in tools_mod.TOOL_REGISTRY:
        assert entry["side_effect"] in {"read", "physical"}, entry["name"]
        assert entry["cost_class"] in {"cheap", "medium", "expensive"}, entry["name"]
        assert entry["input_schema"]["type"] == "object", entry["name"]


def test_no_tool_module_binds_the_access_filter_by_name():
    """The access filter is the privacy boundary. Every tool has to reach it
    through ``_common`` so replacing it in one place covers all of them. A
    module-level ``from ... import accessible_camera_ids`` would bypass that
    and silently keep the old function."""
    offenders = []
    for mod in _tool_modules():
        if mod is tools_common:
            continue
        bound = getattr(mod, "accessible_camera_ids", None)
        if bound is not None:
            offenders.append(mod.__name__)
    assert offenders == [], (
        "these modules bound accessible_camera_ids directly: " + ", ".join(offenders)
    )


@pytest.mark.parametrize(
    "mod", _tool_modules(), ids=lambda m: m.__name__.rsplit(".", 1)[-1]
)
def test_each_tool_module_reaches_the_filter_through_common(mod):
    """Whatever a module calls, it calls ``_common.accessible_camera_ids``."""
    for _, fn in inspect.getmembers(mod, inspect.iscoroutinefunction):
        src = inspect.getsource(fn)
        assert "await accessible_camera_ids(" not in src, (
            f"{mod.__name__}.{fn.__name__} calls the filter by bare name"
        )


def test_every_provider_dialect_covers_the_whole_registry():
    for provider in ("anthropic", "openai", "gemini"):
        served = tools_mod.all_tools_for_provider(provider)
        assert len(served) == len(tools_mod.TOOL_REGISTRY), provider
