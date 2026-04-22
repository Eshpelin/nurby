"""Unit tests for the rule template engine and safe condition evaluator."""

import pytest

from services.events.templates import (
    ConditionError,
    TemplateError,
    collect_refs,
    render,
    safe_eval_condition,
)


def test_render_dot_path_from_nested_dict():
    ctx = {"vars": {"out": {"level": "high", "reason": "dog in yard"}}}
    assert render("{{vars.out.level}}", ctx) == "high"


def test_render_missing_key_returns_empty_non_strict():
    ctx = {"vars": {}}
    assert render("{{vars.missing}}", ctx) == ""


def test_render_missing_key_strict_raises():
    with pytest.raises(TemplateError):
        render("{{vars.missing}}", {"vars": {}}, strict=True)


def test_render_preserves_types_for_single_token():
    ctx = {"vars": {"out": {"a": 1}}}
    assert render("{{vars.out}}", ctx) == {"a": 1}


def test_render_partial_stringifies():
    ctx = {"camera_name": "Front", "count": 3}
    assert render("Camera {{camera_name}} saw {{count}}", ctx) == "Camera Front saw 3"


def test_render_walks_dicts_and_lists():
    ctx = {"vars": {"out": "ok"}}
    tpl = {"a": [{"b": "{{vars.out}}"}, "plain"]}
    assert render(tpl, ctx) == {"a": [{"b": "ok"}, "plain"]}


def test_render_list_index_in_path():
    ctx = {"items": [{"k": "v"}, {"k": "w"}]}
    assert render("{{items.1.k}}", ctx) == "w"


def test_collect_refs_finds_all_tokens():
    tpl = {"url": "https://x/{{a}}", "body": {"msg": "{{vars.b.c}}"}}
    refs = set(collect_refs(tpl))
    assert refs == {"a", "vars.b.c"}


def test_condition_simple_comparison():
    assert safe_eval_condition("vars.out.level == 'high'", {"vars": {"out": {"level": "high"}}})


def test_condition_and_or_not():
    ctx = {"x": 5, "y": "hi"}
    assert safe_eval_condition("x > 3 and y == 'hi'", ctx)
    assert safe_eval_condition("x < 3 or y == 'hi'", ctx)
    assert safe_eval_condition("not (x < 3)", ctx)


def test_condition_in_operator():
    assert safe_eval_condition("level in ['high', 'medium']", {"level": "high"})


def test_condition_rejects_function_call():
    with pytest.raises(ConditionError):
        safe_eval_condition("len(x) > 0", {"x": "abc"})


def test_condition_rejects_subscript():
    with pytest.raises(ConditionError):
        safe_eval_condition("x[0] == 1", {"x": [1]})


def test_condition_rejects_arithmetic():
    with pytest.raises(ConditionError):
        safe_eval_condition("x + 1 == 2", {"x": 1})


def test_condition_missing_path_falsy():
    assert not safe_eval_condition("vars.nope == 'x'", {"vars": {}})
