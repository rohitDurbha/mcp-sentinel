"""Static extraction of MCP tools from Go using tree-sitter.

Covers mark3labs/mcp-go (``mcp.NewTool`` with option functions) and the official
go-sdk (``&mcp.Tool{Name: ..., Description: ...}``).
"""

from __future__ import annotations

import re
from functools import cache
from typing import Any

import tree_sitter as ts
import tree_sitter_go as tsgo

from ..models import ParamText
from .common import MAX_DEPTH, Resolved, Scope, concat, decode_escape, text, unresolved, walk
from .found import Found

LANGUAGE = "go"
SUFFIXES = (".go",)
_HELPERS = {"MustTool", "ConvertTool"}
_TRANSLATION_KEY = re.compile(r'"[A-Z][A-Z0-9_]+"')


@cache
def _parser() -> ts.Parser:
    return ts.Parser(ts.Language(tsgo.language()))


def parse(source: bytes) -> Any:
    return _parser().parse(source).root_node


def constants(root: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for decl in root.named_children:
        if decl.type not in ("const_declaration", "var_declaration"):
            continue
        for spec in walk(decl):
            if spec.type not in ("const_spec", "var_spec"):
                continue
            names = [c for c in spec.children_by_field_name("name") if c.type == "identifier"]
            value = spec.child_by_field_name("value")
            if len(names) == 1 and value is not None and len(value.named_children) == 1:
                out[text(names[0])] = value.named_children[0]
    return out


def resolve(node: Any, scope: Scope, depth: int = 0) -> Resolved:
    if depth > MAX_DEPTH:
        return unresolved(text(node))
    kind = node.type
    if kind == "interpreted_string_literal":
        parts = []
        for child in node.named_children:
            if child.type == "escape_sequence":
                parts.append(decode_escape(text(child)))
            else:
                parts.append(text(child))
        return "".join(parts), True
    if kind == "raw_string_literal":
        return text(node)[1:-1].replace("\r", ""), True
    if kind == "parenthesized_expression" and node.named_children:
        return resolve(node.named_children[0], scope, depth + 1)
    if kind == "binary_expression" and text(node.child_by_field_name("operator")) == "+":
        left = resolve(node.child_by_field_name("left"), scope, depth + 1)
        right = resolve(node.child_by_field_name("right"), scope, depth + 1)
        return concat([left, right])
    if kind == "identifier":
        hit = scope.lookup(text(node))
        if hit is None:
            return unresolved(text(node))
        return resolve(hit[0], hit[1], depth + 1)
    if kind == "call_expression":
        args = _args(node)
        # Translation helpers such as t("TOOL_X_DESCRIPTION", "default text") fall back
        # to the default text, which is what users see unless overridden.
        if len(args) == 2 and _TRANSLATION_KEY.fullmatch(text(args[0])):
            return resolve(args[1], scope, depth + 1)
    return unresolved(text(node))


def _call_name(call: Any) -> str | None:
    func = call.child_by_field_name("function")
    if func is None:
        return None
    if func.type == "selector_expression":
        return text(func.child_by_field_name("field"))
    return text(func) if func.type == "identifier" else None


def _args(call: Any) -> list[Any]:
    node = call.child_by_field_name("arguments")
    return [a for a in node.named_children if a.type != "comment"] if node else []


def _from_new_tool(call: Any, scope: Scope) -> Found | None:
    args = _args(call)
    if not args:
        return None
    name, name_ok = resolve(args[0], scope)
    if not name_ok and not (args[0].type == "identifier" and scope.lookup(text(args[0])) is None):
        return None  # first argument is not a tool name, e.g. a project's own NewTool wrapper
    desc: Resolved = ("", True)
    params: list[ParamText] = []
    for opt in args[1:]:
        if opt.type != "call_expression":
            continue
        opt_name, opt_args = _call_name(opt), _args(opt)
        if opt_name == "WithDescription" and opt_args:
            desc = resolve(opt_args[0], scope)
        elif opt_name and opt_name.startswith("With") and opt_args:
            param = resolve(opt_args[0], scope)[0]
            for inner in opt_args[1:]:
                if inner.type == "call_expression" and _call_name(inner) == "Description":
                    inner_args = _args(inner)
                    if inner_args:
                        params.append(ParamText(param, resolve(inner_args[0], scope)[0]))
    return Found(call.start_point[0] + 1, "go.NewTool", name, *desc, params)


def _from_helper(call: Any, scope: Scope) -> Found | None:
    """Helpers shaped like ``MustTool(name, description, handler, opts...)`` (mcp-grafana)."""
    args = _args(call)
    if len(args) < 3:
        return None
    name, name_ok = resolve(args[0], scope)
    if not name_ok:
        return None
    return Found(call.start_point[0] + 1, "go.MustTool", name, *resolve(args[1], scope), [])


def _from_struct(lit: Any, scope: Scope) -> Found | None:
    type_node = lit.child_by_field_name("type")
    if type_node is None:
        return None
    type_name = (
        type_node.child_by_field_name("name") if type_node.type == "qualified_type" else type_node
    )
    if type_name is None or text(type_name) != "Tool":
        return None
    fields: dict[str, Any] = {}
    body = lit.child_by_field_name("body")
    for element in body.named_children if body else []:
        pair = _keyed(element)
        if pair is not None:
            fields[text(pair[0])] = pair[1]
    if "Name" not in fields:
        return None
    desc = resolve(fields["Description"], scope) if "Description" in fields else ("", True)
    name = resolve(fields["Name"], scope)[0]
    params = _schema_params(fields["InputSchema"], scope) if "InputSchema" in fields else []
    return Found(lit.start_point[0] + 1, "go.Tool", name, *desc, params)


def _keyed(node: Any) -> tuple[Any, Any] | None:
    if node.type != "keyed_element" or len(node.named_children) != 2:
        return None
    key, value = (_unwrap_element(c) for c in node.named_children)
    return key, value


def _schema_params(schema: Any, scope: Scope) -> list[ParamText]:
    """Parameter descriptions from a jsonschema.Schema literal: "param": {Description: ...}."""
    out = []
    for node in walk(schema):
        pair = _keyed(node)
        if pair is None or pair[0].type != "interpreted_string_literal":
            continue
        if pair[1].type != "literal_value":
            continue
        for inner in pair[1].named_children:
            field = _keyed(inner)
            if field and field[0].type == "identifier" and text(field[0]) == "Description":
                out.append(ParamText(resolve(pair[0], scope)[0], resolve(field[1], scope)[0]))
    return out


def _unwrap_element(node: Any) -> Any:
    if node.type == "literal_element" and node.named_children:
        return node.named_children[0]
    return node


def extract(root: Any, scope: Scope) -> list[Found]:
    found = []
    for node in walk(root):
        hit = None
        if node.type == "call_expression" and _call_name(node) == "NewTool":
            hit = _from_new_tool(node, scope)
        elif node.type == "call_expression" and _call_name(node) in _HELPERS:
            hit = _from_helper(node, scope)
        elif node.type == "composite_literal":
            hit = _from_struct(node, scope)
        if hit is not None:
            found.append(hit)
    return found
