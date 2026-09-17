"""``shared.schemas`` is a package now. These tests hold its edges.

Splitting the schemas across twelve modules mirrors the ``shared.models``
split. The failure mode is quieter than the models one: a class that
stops being imported still type-checks and its module still passes, but
``from shared.schemas import CameraCreate`` breaks for every route that
uses it. These tests keep the package re-exports honest.
"""

from __future__ import annotations

import pkgutil

import pytest
from pydantic import BaseModel

import shared.schemas as schemas


def _public_names():
    return [n for n in schemas.__all__]


def _model_classes():
    return [getattr(schemas, n) for n in _public_names()]


def test_every_schema_module_is_imported_by_the_package():
    """A new module under shared/schemas/ has to be wired into __init__
    or none of its classes are importable from the package root."""
    submodules = {
        m.name for m in pkgutil.iter_modules(schemas.__path__)
        if not m.name.startswith("_")
    }
    imported = {
        cls.__module__.rsplit(".", 1)[-1] for cls in _model_classes()
    }
    missing = submodules - imported
    assert missing == set(), (
        "these schema modules contribute nothing to shared.schemas: "
        + ", ".join(sorted(missing))
    )


@pytest.mark.parametrize("name", sorted(_public_names()))
def test_each_schema_is_reachable_from_the_package_root(name):
    """``from shared.schemas import X`` has to keep working; that is the
    import every route and test in the repo uses."""
    assert hasattr(schemas, name)


def test_every_export_is_a_model_or_the_url_validator():
    """The package exports Pydantic models and one helper. Anything else
    leaking into __all__ is a wiring mistake."""
    for cls in _model_classes():
        if cls is schemas.validate_stream_url:
            continue
        assert issubclass(cls, BaseModel), (
            f"{cls.__name__} is exported but is not a Pydantic model"
        )


def test_no_schema_name_is_defined_twice():
    """Two modules exporting the same name would mean one import silently
    shadows the other."""
    seen: dict[str, str] = {}
    for cls in _model_classes():
        prior = seen.get(cls.__name__)
        assert prior is None, (
            f"{cls.__name__} is exported by both {prior} and {cls.__module__}"
        )
        seen[cls.__name__] = cls.__module__


def test_every_model_generates_a_json_schema():
    """Validators that fail at class construction usually surface here
    first: model_json_schema() exercises the full schema build."""
    for cls in _model_classes():
        if cls is schemas.validate_stream_url:
            continue
        assert cls.model_json_schema()["title"] == cls.__name__
