"""``shared.models`` is a package now. These tests hold its edges.

Splitting the models across ten modules introduced one quiet failure mode:
a model that stops being imported still compiles, still passes every test
that does not touch it, and then vanishes from ``Base.metadata``. Alembic
autogenerate reads that metadata, so a missing model does not raise. It
writes a migration that drops the table.
"""

from __future__ import annotations

import pkgutil

import pytest

import shared.models as models
from shared.database import Base


def _model_classes():
    return [getattr(models, n) for n in models.__all__ if n != "Base"]


def test_every_model_module_is_imported_by_the_package():
    """A new module under shared/models/ has to be wired into __init__ or
    its tables never reach Base.metadata."""
    submodules = {
        m.name for m in pkgutil.iter_modules(models.__path__)
        if not m.name.startswith("_")
    }
    imported = {
        cls.__module__.rsplit(".", 1)[-1] for cls in _model_classes()
    }
    missing = submodules - imported
    assert missing == set(), (
        "these model modules contribute nothing to shared.models: "
        + ", ".join(sorted(missing))
    )


def test_every_exported_model_registers_a_table():
    for cls in _model_classes():
        assert cls.__tablename__ in Base.metadata.tables, (
            f"{cls.__name__} is exported but its table is not on the metadata"
        )


def test_every_registered_table_has_an_exported_model():
    """The direction Alembic cares about: nothing on the metadata that a
    caller cannot import by name."""
    exported = {cls.__tablename__ for cls in _model_classes()}
    orphans = set(Base.metadata.tables) - exported
    assert orphans == set(), (
        "tables with no importable model: " + ", ".join(sorted(orphans))
    )


def test_no_model_name_is_defined_twice():
    by_table: dict[str, str] = {}
    for cls in _model_classes():
        prior = by_table.get(cls.__tablename__)
        assert prior is None, (
            f"{cls.__tablename__} is claimed by both {prior} and {cls.__name__}"
        )
        by_table[cls.__tablename__] = cls.__name__


@pytest.mark.parametrize("name", sorted(n for n in models.__all__ if n != "Base"))
def test_each_model_is_reachable_from_the_package_root(name):
    """``from shared.models import Camera`` has to keep working; that is the
    import every caller in the repo uses."""
    assert hasattr(models, name)
    assert getattr(models, name).__table__ is not None


def test_every_foreign_key_points_at_a_table_that_exists():
    """Models reference each other by table name, not by Python name, so a
    module that failed to load shows up here as a dangling target."""
    dangling = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            for fk in column.foreign_keys:
                target = fk.target_fullname.split(".")[0]
                if target not in Base.metadata.tables:
                    dangling.append(f"{table.name}.{column.name} -> {fk.target_fullname}")
    assert dangling == [], "dangling foreign keys: " + ", ".join(dangling)
