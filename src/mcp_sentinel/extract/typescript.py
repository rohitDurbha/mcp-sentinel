"""Static extraction of MCP tools from TypeScript and JavaScript using tree-sitter."""

from __future__ import annotations

from functools import cache
from typing import Any

import tree_sitter as ts
import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts

from ..models import ParamText
from .common import (
    MAX_DEPTH,
    Resolved,
    Scope,
    concat,
    decode_escape,
    dedent,
    text,
    unresolved,
    walk,
)
from .found import Found

LANGUAGE = "typescript"
SUFFIXES = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")

_FUNCTIONS = {"arrow_function", "function_expression", "function"}
_WRAPPERS = {
    "as_expression",
    "satisfies_expression",
    "non_null_expression",
    "parenthesized_expression",
}
_SCHEMA_KEYS = ("inputSchema", "input_schema", "parameters", "paramsSchema")
_CLASS_NAME_KEYS = ("name", "toolName")


@cache
def _parser(suffix: str) -> ts.Parser:
    if suffix == ".tsx":
        lang = tsts.language_tsx()
    elif suffix in (".ts", ".mts", ".cts"):
        lang = tsts.language_typescript()
    else:
        lang = tsjs.language()
    return ts.Parser(ts.Language(lang))


def parse(source: bytes, suffix: str) -> Any:
    return _parser(suffix).parse(source).root_node


def _unwrap(node: Any) -> Any:
    while node is not None and node.type in _WRAPPERS and node.named_children:
        node = node.named_children[0]
    return node


def constants(root: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for stmt in root.named_children:
        if stmt.type == "export_statement":
            stmt = stmt.child_by_field_name("declaration")
        if stmt is None or stmt.type not in ("lexical_declaration", "variable_declaration"):
            continue
        for decl in stmt.named_children:
            name, value = decl.child_by_field_name("name"), decl.child_by_field_name("value")
            if decl.type != "variable_declarator" or value is None:
                continue
            if name is not None and name.type == "identifier":
                out[text(name)] = value
    return out


def resolve(node: Any, scope: Scope, depth: int = 0) -> Resolved:
    node = _unwrap(node)
    if depth > MAX_DEPTH:
        return unresolved(text(node))
    kind = node.type
    if kind in ("string", "template_string"):
        parts: list[Resolved] = []
        for child in node.named_children:
            if child.type == "string_fragment":
                parts.append((text(child), True))
            elif child.type == "escape_sequence":
                parts.append((decode_escape(text(child)), True))
            elif child.type == "template_substitution":
                inner = child.named_children[0] if child.named_children else child
                value, ok = resolve(inner, scope, depth + 1)
                parts.append((value, True) if ok else unresolved(text(inner)))
        return concat(parts)
    if kind == "binary_expression" and text(node.child_by_field_name("operator")) == "+":
        left = resolve(node.child_by_field_name("left"), scope, depth + 1)
        right = resolve(node.child_by_field_name("right"), scope, depth + 1)
        return concat([left, right])
    if kind == "identifier":
        hit = scope.lookup(text(node))
        if hit is None:
            return unresolved(text(node))
        return resolve(hit[0], hit[1], depth + 1)
    if kind == "member_expression":
        obj, prop = _lookup_object(node.child_by_field_name("object"), scope, depth)
        key = text(node.child_by_field_name("property"))
        value = _pair(obj, key) if obj is not None else None
        if value is not None:
            return resolve(value, prop, depth + 1)
    if kind == "call_expression":
        return _resolve_call(node, scope, depth)
    return unresolved(text(node))


def _lookup_object(node: Any, scope: Scope, depth: int) -> tuple[Any, Scope]:
    node = _unwrap(node)
    if node is not None and node.type == "identifier":
        hit = scope.lookup(text(node))
        if hit is not None:
            target = _unwrap(hit[0])
            if target.type == "object":
                return target, hit[1]
    return None, scope


def _resolve_call(node: Any, scope: Scope, depth: int) -> Resolved:
    func = node.child_by_field_name("function")
    args = node.child_by_field_name("arguments")
    arg_list = [a for a in args.named_children if a.type != "comment"] if args else []
    if func.type == "member_expression":
        method = text(func.child_by_field_name("property"))
        target = _unwrap(func.child_by_field_name("object"))
        if method == "join" and target.type == "array" and len(arg_list) <= 1:
            sep = resolve(arg_list[0], scope, depth + 1) if arg_list else (",", True)
            items = [resolve(e, scope, depth + 1) for e in target.named_children]
            return sep[0].join(t for t, _ in items), sep[1] and all(ok for _, ok in items)
        if method in ("trim", "trimStart", "trimEnd") and not arg_list:
            value, ok = resolve(target, scope, depth + 1)
            return value.strip(), ok
    if func.type == "identifier" and text(func) in ("dedent", "outdent"):
        source = args if args is not None and args.type == "template_string" else None
        source = source or (arg_list[0] if arg_list else None)
        if source is not None:
            value, ok = resolve(source, scope, depth + 1)
            return dedent(value), ok
    return unresolved(text(node))


def _key(pair: Any, scope: Scope) -> str | None:
    key = pair.child_by_field_name("key")
    if key is None:
        return None
    if key.type in ("property_identifier", "identifier"):
        return text(key)
    if key.type == "string":
        return resolve(key, scope)[0]
    return None


def _pair(obj: Any, name: str, scope: Scope | None = None) -> Any:
    for child in obj.named_children:
        if child.type == "pair" and _key(child, scope or Scope({})) == name:
            return child.child_by_field_name("value")
    return None


def _describe_calls(node: Any, scope: Scope) -> list[str]:
    out = []
    for sub in walk(node):
        if sub.type != "call_expression":
            continue
        func = sub.child_by_field_name("function")
        if (
            func.type == "member_expression"
            and text(func.child_by_field_name("property")) == "describe"
        ):
            args = sub.child_by_field_name("arguments")
            if args is not None and args.named_children:
                out.append(resolve(args.named_children[0], scope)[0])
    out.reverse()  # outer .describe() wraps inner ones, so report innermost first
    return out


def _params(node: Any, scope: Scope, parent: str | None = None) -> list[ParamText]:
    node = _unwrap(node)
    if node is None:
        return []
    if node.type == "identifier":
        hit = scope.lookup(text(node))
        return _params(hit[0], hit[1], parent) if hit else []
    if node.type == "call_expression":
        shape = _zod_object_shape(node)
        if shape is not None:
            return _params(shape, scope, parent)
    if node.type != "object":
        return [ParamText(parent, t) for t in _describe_calls(node, scope)]
    out: list[ParamText] = []
    for pair in node.named_children:
        if pair.type != "pair":
            continue
        key = _key(pair, scope)
        value = _unwrap(pair.child_by_field_name("value"))
        if key == "description" and parent != "properties":
            out.append(ParamText(parent, resolve(value, scope)[0]))
        elif value.type == "object":
            out.extend(_params(value, scope, key))
        else:
            out.extend(ParamText(key, t) for t in _describe_calls(value, scope))
    return out


def _zod_object_shape(node: Any) -> Any:
    """Return the shape object inside ``z.object({...})``, even when chained."""
    for sub in walk(node):
        if sub.type != "call_expression":
            continue
        func = sub.child_by_field_name("function")
        prop = func.child_by_field_name("property") if func.type == "member_expression" else None
        args = sub.child_by_field_name("arguments")
        if prop is not None and text(prop) == "object" and args is not None and args.named_children:
            first = _unwrap(args.named_children[0])
            if first.type == "object":
                return first
    return None


def _is_string_like(node: Any, scope: Scope) -> bool:
    node = _unwrap(node)
    if node.type in ("object", *_FUNCTIONS):
        return False
    if node.type == "identifier":
        hit = scope.lookup(text(node))
        return hit is None or _unwrap(hit[0]).type not in ("object", *_FUNCTIONS)
    return True


def _in_tools_array(obj: Any) -> bool:
    parent = obj.parent
    if parent is None or parent.type != "array":
        return False
    pair = parent.parent
    if pair is None or pair.type != "pair":
        return False
    key = pair.child_by_field_name("key")
    return key is not None and text(key).strip("\"'`") == "tools"


def _from_call(node: Any, scope: Scope) -> Found | None:
    func = node.child_by_field_name("function")
    if func is None or func.type != "member_expression":
        return None
    method = text(func.child_by_field_name("property"))
    if method not in ("tool", "registerTool"):
        return None
    args_node = node.child_by_field_name("arguments")
    args = [a for a in args_node.named_children if a.type != "comment"] if args_node else []
    if len(args) < 2:
        return None
    name = resolve(args[0], scope)[0]
    line = node.start_point[0] + 1
    if method == "registerTool":
        config = _unwrap(args[1])
        if config.type != "object":
            return None
        desc_node = _pair(config, "description", scope)
        desc = resolve(desc_node, scope) if desc_node is not None else ("", True)
        params = _params(_pair(config, "inputSchema", scope), scope)
        return Found(line, "ts.registerTool", name, *desc, params)
    if _unwrap(args[-1]).type not in (*_FUNCTIONS, "identifier", "member_expression"):
        return None  # server.tool always ends with a handler
    rest = args[1:]
    desc: Resolved = ("", True)
    if rest and _is_string_like(rest[0], scope) and len(rest) > 1:
        desc = resolve(rest[0], scope)
        rest = rest[1:]
    schema = rest[0] if len(rest) > 1 else None
    params = _params(schema, scope) if schema is not None else []
    return Found(line, "ts.server.tool", name, *desc, params)


def _from_object(node: Any, scope: Scope) -> Found | None:
    desc_node = _pair(node, "description", scope)
    if desc_node is None:
        return None
    schema = next((v for k in _SCHEMA_KEYS if (v := _pair(node, k, scope)) is not None), None)
    name_node = _pair(node, "name", scope)
    if name_node is None:
        # A map of tools keyed by name, e.g. { list_tables: { description, parameters } }
        parent = node.parent
        if schema is None or parent is None or parent.type != "pair":
            return None
        name = _key(parent, scope)
        if not name or name in ("properties", *_SCHEMA_KEYS):
            return None
    else:
        if schema is None and not _in_tools_array(node):
            return None
        name, name_ok = resolve(name_node, scope)
        if not name_ok and _unwrap(name_node).type != "identifier":
            return None
    desc = resolve(desc_node, scope)
    params = _params(schema, scope) if schema is not None else []
    return Found(node.start_point[0] + 1, "ts.object", name, *desc, params)


def _from_class(node: Any, scope: Scope) -> Found | None:
    """Class-based tools such as ``class FindTool extends ToolBase { static toolName = ... }``."""
    class_name = node.child_by_field_name("name")
    body = node.child_by_field_name("body")
    if class_name is None or body is None or not text(class_name).endswith("Tool"):
        return None
    fields: dict[str, Any] = {}
    for member in body.named_children:
        if member.type not in ("public_field_definition", "field_definition"):
            continue
        key = member.child_by_field_name("name") or member.child_by_field_name("property")
        value = member.child_by_field_name("value")
        if key is not None and value is not None:
            fields[text(key)] = value
    name_node = next((fields[k] for k in _CLASS_NAME_KEYS if k in fields), None)
    if name_node is None or "description" not in fields:
        return None
    name = resolve(name_node, scope)[0]
    desc = resolve(fields["description"], scope)
    return Found(node.start_point[0] + 1, "ts.class", name, *desc, [])


def extract(root: Any, scope: Scope) -> list[Found]:
    found = []
    for node in walk(root):
        hit = None
        if node.type == "call_expression":
            hit = _from_call(node, scope)
        elif node.type == "object":
            hit = _from_object(node, scope)
        elif node.type in ("class_declaration", "class"):
            hit = _from_class(node, scope)
        if hit is not None:
            found.append(hit)
    return found
