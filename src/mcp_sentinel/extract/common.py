"""Pieces shared by the language extractors.

Descriptions are often built from constants, concatenation or ``join`` calls. Each
extractor resolves those statically and reports whether the result is complete, so
later stages know when they are looking at partial text.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

MAX_DEPTH = 8

# A resolved string plus a flag saying whether every part was known statically.
Resolved = tuple[str, bool]

_SIMPLE_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "0": "\0",
    "a": "\a",
}


def decode_escape(seq: str) -> str:
    """Decode one backslash escape as written in JS, TS or Go source."""
    body = seq[1:]
    if not body:
        return ""
    if body[0] in "\r\n":  # JS line continuation
        return ""
    if body[0] in _SIMPLE_ESCAPES and len(body) == 1:
        return _SIMPLE_ESCAPES[body[0]]
    if body[0] in "xuU":
        hexdigits = body[1:].strip("{}")
        try:
            return chr(int(hexdigits, 16))
        except ValueError:
            return seq
    if body.isdigit():  # Go octal escape such as \101
        try:
            return chr(int(body, 8))
        except ValueError:
            return seq
    return body  # \" \' \\ \` and anything unknown


def unresolved(source_text: str) -> Resolved:
    """Placeholder for an expression that cannot be resolved statically."""
    return "{" + " ".join(source_text.split()) + "}", False


def concat(parts: list[Resolved]) -> Resolved:
    return "".join(p[0] for p in parts), all(p[1] for p in parts)


@dataclass
class Scope:
    """Name lookup for one file, falling back to unique names across the repo."""

    local: dict[str, Any]
    table: dict[str, list[tuple[Any, Scope]]] = field(default_factory=dict)

    def lookup(self, name: str) -> tuple[Any, Scope] | None:
        if name in self.local:
            return self.local[name], self
        hits = self.table.get(name, [])
        return hits[0] if len(hits) == 1 else None


def register(table: dict[str, list[tuple[Any, Scope]]], scope: Scope) -> None:
    for name, node in scope.local.items():
        table.setdefault(name, []).append((node, scope))


def dedent(text: str) -> str:
    """Remove common leading indentation, matching the usual dedent helpers."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return text.strip()
    indent = min(len(ln) - len(ln.lstrip(" \t")) for ln in lines)
    out = "\n".join(ln[indent:] if ln.strip() else "" for ln in text.splitlines())
    return out.strip("\n")


def text(node: Any) -> str:
    """Source text of a tree-sitter node."""
    return node.text.decode("utf-8", errors="replace")


def walk(node: Any) -> Iterator[Any]:
    """Depth-first walk over named tree-sitter nodes in source order."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))
