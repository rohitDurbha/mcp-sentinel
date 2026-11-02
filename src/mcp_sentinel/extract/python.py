"""Static extraction of MCP tools from Python source using ``ast``."""

from __future__ import annotations

import ast
import inspect

from ..models import ParamText
from .common import MAX_DEPTH, Resolved, Scope, concat, dedent, unresolved
from .found import Found

LANGUAGE = "python"
SUFFIXES = (".py",)


def parse(source: bytes) -> ast.Module | None:
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError):
        return None


def constants(module: ast.Module) -> dict[str, ast.expr]:
    out: dict[str, ast.expr] = {}
    for stmt in module.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            target, value = stmt.target, stmt.value
        else:
            continue
        if isinstance(target, ast.Name):
            out[target.id] = value
    for stmt in module.body:  # functions too, so mcp.tool()(fn) can find fn's docstring
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            out.setdefault(stmt.name, stmt)
    return out


def resolve(node: ast.AST, scope: Scope, depth: int = 0) -> Resolved:
    if depth > MAX_DEPTH:
        return unresolved(ast.unparse(node))
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, True
    if isinstance(node, ast.JoinedStr):
        parts: list[Resolved] = []
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                text, ok = resolve(value.value, scope, depth + 1)
                parts.append((text, True) if ok else unresolved(ast.unparse(value.value)))
            else:
                parts.append(resolve(value, scope, depth + 1))
        return concat(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return concat([resolve(node.left, scope, depth + 1), resolve(node.right, scope, depth + 1)])
    if isinstance(node, ast.Name):
        hit = scope.lookup(node.id)
        if hit is None:
            return unresolved(node.id)
        target, target_scope = hit
        if isinstance(target, ast.FunctionDef | ast.AsyncFunctionDef):
            return unresolved(node.id)
        return resolve(target, target_scope, depth + 1)
    if isinstance(node, ast.Call):
        return _resolve_call(node, scope, depth)
    return unresolved(ast.unparse(node))


def _resolve_call(node: ast.Call, scope: Scope, depth: int) -> Resolved:
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr == "join" and len(node.args) == 1:
        sep = resolve(func.value, scope, depth + 1)
        arg = node.args[0]
        if isinstance(arg, ast.List | ast.Tuple):
            items = [resolve(e, scope, depth + 1) for e in arg.elts]
            return sep[0].join(t for t, _ in items), sep[1] and all(ok for _, ok in items)
    if isinstance(func, ast.Attribute) and func.attr == "strip" and not node.args:
        text, ok = resolve(func.value, scope, depth + 1)
        return text.strip(), ok
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if name == "dedent" and len(node.args) == 1:
        text, ok = resolve(node.args[0], scope, depth + 1)
        return dedent(text), ok
    return unresolved(ast.unparse(node))


def _keyword(call: ast.Call, *names: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg in names:
            return kw.value
    return None


def _is_tool_decorator(dec: ast.expr) -> ast.Call | bool:
    target = dec.func if isinstance(dec, ast.Call) else dec
    if isinstance(target, ast.Attribute) and target.attr == "tool":
        return dec if isinstance(dec, ast.Call) else True
    return False


def _field_description(node: ast.AST | None, scope: Scope) -> Resolved | None:
    if node is None:
        return None
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            fname = sub.func.attr if isinstance(sub.func, ast.Attribute) else None
            fname = fname or getattr(sub.func, "id", None)
            desc = _keyword(sub, "description")
            if fname == "Field" and desc is not None:
                return resolve(desc, scope)
    return None


def _function_params(fn: ast.FunctionDef | ast.AsyncFunctionDef, scope: Scope) -> list[ParamText]:
    a = fn.args
    positional = a.posonlyargs + a.args
    defaults: dict[str, ast.expr] = {}
    for arg, default in zip(
        positional[len(positional) - len(a.defaults) :], a.defaults, strict=True
    ):
        defaults[arg.arg] = default
    for arg, default in zip(a.kwonlyargs, a.kw_defaults, strict=True):
        if default is not None:
            defaults[arg.arg] = default
    out = []
    for arg in positional + a.kwonlyargs:
        found = _field_description(arg.annotation, scope) or _field_description(
            defaults.get(arg.arg), scope
        )
        if found:
            out.append(ParamText(arg.arg, found[0]))
    return out


def _schema_params(
    node: ast.AST | None, scope: Scope, parent: str | None = None
) -> list[ParamText]:
    if not isinstance(node, ast.Dict):
        return []
    out = []
    for key, value in zip(node.keys, node.values, strict=True):
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            continue
        if key.value == "description" and parent != "properties":
            out.append(ParamText(parent, resolve(value, scope)[0]))
        elif isinstance(value, ast.Dict):
            out.extend(_schema_params(value, scope, key.value))
    return out


def _from_function(
    fn: ast.FunctionDef | ast.AsyncFunctionDef | None,
    fn_name: str,
    call: ast.Call | None,
    line: int,
    pattern: str,
    scope: Scope,
    fn_scope: Scope | None = None,
) -> Found:
    """Build a tool from a function plus optional overrides.

    Overrides on ``call`` resolve in ``scope`` (the calling file). The docstring and
    parameter descriptions belong to ``fn_scope`` when the function lives elsewhere.
    """
    name_node = _keyword(call, "name") if call else None
    desc_node = _keyword(call, "description") if call else None
    name = resolve(name_node, scope)[0] if name_node else fn_name
    if desc_node is not None:
        desc = resolve(desc_node, scope)
    elif fn is not None:
        desc = (inspect.cleandoc(ast.get_docstring(fn, clean=False) or ""), True)
    else:
        desc = ("", False)  # function lives somewhere we could not follow
    params = _function_params(fn, fn_scope or scope) if fn is not None else []
    return Found(line, pattern, name, *desc, params)


def _registered_function(node: ast.Call, scope: Scope) -> Found | None:
    """``mcp.tool()(fn)``, ``mcp.tool(fn, name=...)`` and ``mcp.add_tool(fn, ...)``."""
    func = node.func
    if isinstance(func, ast.Call) and _is_tool_decorator(func.func) and not func.args:
        config = func  # mcp.tool(...)(fn): overrides live on the inner call
    elif isinstance(func, ast.Attribute) and func.attr in ("tool", "add_tool"):
        config = node
    else:
        return None
    if not node.args or not isinstance(node.args[0], ast.Name):
        return None
    fn_name = node.args[0].id
    hit = scope.lookup(fn_name)
    fn = hit[0] if hit and isinstance(hit[0], ast.FunctionDef | ast.AsyncFunctionDef) else None
    fn_scope = hit[1] if fn is not None else scope
    return _from_function(fn, fn_name, config, node.lineno, "fastmcp.call", scope, fn_scope)


def extract(module: ast.Module, scope: Scope) -> list[Found]:
    found: list[Found] = []
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for dec in node.decorator_list:
                hit = _is_tool_decorator(dec)
                if hit:
                    call = hit if isinstance(hit, ast.Call) else None
                    found.append(
                        _from_function(
                            node, node.name, call, dec.lineno, "fastmcp.decorator", scope
                        )
                    )
                    break
        elif isinstance(node, ast.Call):
            registered = _registered_function(node, scope)
            if registered is not None:
                found.append(registered)
                continue
            fname = node.func.attr if isinstance(node.func, ast.Attribute) else None
            fname = fname or getattr(node.func, "id", None)
            name_node = _keyword(node, "name")
            if fname != "Tool" or name_node is None:
                continue
            desc_node = _keyword(node, "description")
            desc = resolve(desc_node, scope) if desc_node is not None else ("", True)
            params = _schema_params(_keyword(node, "inputSchema", "input_schema"), scope)
            found.append(
                Found(node.lineno, "python.Tool", resolve(name_node, scope)[0], *desc, params)
            )
    return found
