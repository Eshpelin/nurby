"""
Template engine and safe condition evaluator for rule actions.

Provides `render(value, ctx, strict=False)` for dot-path variable
substitution inside nested dicts, lists, and strings. Also provides
`safe_eval_condition(expr, ctx)` which evaluates a small whitelisted
AST of boolean and comparison expressions against the same context.

Both helpers are used by rule action executors so action payloads can
reference observation fields, rule metadata, and outputs written by
prior actions (the `vars` dict).
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z_][\w.]*)\s*\}\}")


class TemplateError(Exception):
    """Raised in strict mode when a template variable path is missing."""


class ConditionError(Exception):
    """Raised when a condition expression contains disallowed syntax."""


def _lookup(path: str, ctx: dict) -> Any:
    """Walk a dotted path through nested dicts and lists."""
    parts = path.split(".")
    cur: Any = ctx
    for p in parts:
        if cur is None:
            return None
        if isinstance(cur, dict):
            if p in cur:
                cur = cur[p]
                continue
            return None
        if isinstance(cur, list):
            try:
                cur = cur[int(p)]
                continue
            except (ValueError, IndexError):
                return None
        return getattr(cur, p, None)
    return cur


def _stringify(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, (dict, list)):
        return json.dumps(val, default=str)
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)


def render(value: Any, ctx: dict, strict: bool = False) -> Any:
    """Recursively substitute `{{dotted.path}}` tokens inside value.

    Dicts and lists are walked. Strings composed entirely of a single
    token preserve the raw value type. Strings with multiple tokens or
    surrounding text get each token stringified.
    """
    if isinstance(value, dict):
        return {k: render(v, ctx, strict) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, ctx, strict) for v in value]
    if isinstance(value, str):
        return _render_string(value, ctx, strict)
    return value


def _render_string(s: str, ctx: dict, strict: bool) -> Any:
    stripped = s.strip()
    m = _TOKEN_RE.fullmatch(stripped)
    if m:
        path = m.group(1)
        val = _lookup(path, ctx)
        if val is None:
            if strict and not _path_exists(path, ctx):
                raise TemplateError(f"missing template path '{path}'")
            return ""
        return val

    def repl(match: re.Match) -> str:
        path = match.group(1)
        val = _lookup(path, ctx)
        if val is None:
            if strict and not _path_exists(path, ctx):
                raise TemplateError(f"missing template path '{path}'")
            return ""
        return _stringify(val)

    return _TOKEN_RE.sub(repl, s)


def _path_exists(path: str, ctx: dict) -> bool:
    parts = path.split(".")
    cur: Any = ctx
    for p in parts:
        if isinstance(cur, dict):
            if p not in cur:
                return False
            cur = cur[p]
            continue
        if isinstance(cur, list):
            try:
                cur = cur[int(p)]
                continue
            except (ValueError, IndexError):
                return False
        return False
    return True


def collect_refs(value: Any) -> list[str]:
    """Return every dotted path referenced by `{{...}}` tokens in value."""
    refs: list[str] = []
    if isinstance(value, dict):
        for v in value.values():
            refs.extend(collect_refs(v))
    elif isinstance(value, list):
        for v in value:
            refs.extend(collect_refs(v))
    elif isinstance(value, str):
        for m in _TOKEN_RE.finditer(value):
            refs.append(m.group(1))
    return refs


# ── Safe condition evaluation ──

_ALLOWED_CMP = (
    ast.Eq, ast.NotEq, ast.Gt, ast.Lt, ast.GtE, ast.LtE, ast.In, ast.NotIn,
)
_ALLOWED_BOOL = (ast.And, ast.Or)


def safe_eval_condition(expr: str, ctx: dict) -> bool:
    """Evaluate a boolean expression against ctx using a whitelisted AST.

    Allowed constructs. comparisons (==, !=, <, <=, >, >=, in, not in),
    boolean combinators (and, or, not), string/number/bool/None literals,
    tuples and lists of literals, and bare identifiers that resolve to
    dotted paths in ctx (attribute access used only to form the path).
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise ConditionError(f"invalid syntax. {exc}") from exc

    return bool(_eval_node(tree.body, ctx))


def _path_from_attr(node: ast.AST) -> str | None:
    parts: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return ".".join(reversed(parts))
    return None


def _eval_node(node: ast.AST, ctx: dict) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (str, int, float, bool)) or node.value is None:
            return node.value
        raise ConditionError("disallowed constant")

    if isinstance(node, ast.Name):
        return _lookup(node.id, ctx)

    if isinstance(node, ast.Attribute):
        path = _path_from_attr(node)
        if path is None:
            raise ConditionError("disallowed attribute access")
        return _lookup(path, ctx)

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval_node(node.operand, ctx)

    if isinstance(node, ast.BoolOp) and isinstance(node.op, _ALLOWED_BOOL):
        if isinstance(node.op, ast.And):
            return all(_eval_node(v, ctx) for v in node.values)
        return any(_eval_node(v, ctx) for v in node.values)

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, ctx)
        for op, right_node in zip(node.ops, node.comparators):
            if not isinstance(op, _ALLOWED_CMP):
                raise ConditionError(f"disallowed comparator {type(op).__name__}")
            right = _eval_node(right_node, ctx)
            if not _apply_cmp(op, left, right):
                return False
            left = right
        return True

    if isinstance(node, (ast.Tuple, ast.List)):
        return [_eval_node(el, ctx) for el in node.elts]

    raise ConditionError(f"disallowed node {type(node).__name__}")


def _apply_cmp(op: ast.AST, left: Any, right: Any) -> bool:
    try:
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if isinstance(op, ast.Gt):
            return left > right
        if isinstance(op, ast.Lt):
            return left < right
        if isinstance(op, ast.GtE):
            return left >= right
        if isinstance(op, ast.LtE):
            return left <= right
        if isinstance(op, ast.In):
            return left in (right or [])
        if isinstance(op, ast.NotIn):
            return left not in (right or [])
    except TypeError:
        return False
    return False
