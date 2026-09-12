"""Subject matching against per-subject and legacy joined keys (#151)."""
import pytest
from sqlalchemy import Column, MetaData, String, Table, select
from sqlalchemy.dialects import postgresql

from shared.subject_keys import key_elements, key_names, subject_key_has

_t = Table("t", MetaData(), Column("signature_key", String))


def test_key_elements_splits_legacy_joined_keys():
    assert key_elements("Ahmed,Sara") == ["Ahmed", "Sara"]
    assert key_elements("Ahmed") == ["Ahmed"]
    assert key_elements("Ahmed, Sara ") == ["Ahmed", "Sara"]
    assert key_elements("") == []
    assert key_elements(None) == []


@pytest.mark.parametrize(
    "key,name,expected",
    [
        ("Sam", "Sam", True),
        ("Samantha", "Sam", False),  # the bug this replaces
        ("Ahmed,Sara", "Sara", True),
        ("Ahmed,Sara", "Sar", False),
        ("Ahmed,Sara", "ahmed", False),  # exact, not case-folded
        ("", "Sam", False),
    ],
)
def test_key_names_is_exact_per_element(key, name, expected):
    assert key_names(key, name) is expected


def test_sql_predicate_is_exact_per_element_not_substring():
    sql = str(
        select(_t.c.signature_key)
        .where(subject_key_has(_t.c.signature_key, "Sam"))
        .compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert "string_to_array" in sql
    assert "ANY" in sql
    assert "ILIKE" not in sql.upper() or "string_to_array" in sql
    assert "%" not in sql  # no LIKE wildcard anywhere
