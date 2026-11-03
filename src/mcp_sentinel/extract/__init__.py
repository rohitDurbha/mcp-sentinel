"""Walk a checked-out repository and extract every MCP tool definition statically.

Nothing in the repository is executed or imported. Files are parsed with ``ast`` or
tree-sitter, constants are resolved across files of the same language, and every
tool comes back with its file, line and the pattern that matched.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ..models import Tool
from . import golang, python, typescript
from .common import Scope, register

SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", "out", "vendor", "target", "coverage",
    "__pycache__", ".venv", "venv", "site-packages", ".next",
    "test", "tests", "__tests__", "spec", "testdata", "__mocks__", "e2e",
}  # fmt: skip
SKIP_SUFFIXES = (".d.ts", ".min.js", ".test.ts", ".spec.ts", ".test.js", ".spec.js", "_test.go")
MAX_FILE_BYTES = 512_000
MAX_FILES = 5_000

_LANGS = (python, typescript, golang)


def _language(path: Path) -> Any | None:
    name = path.name
    if name.endswith(SKIP_SUFFIXES) or (name.startswith("test_") and name.endswith(".py")):
        return None
    return next((lang for lang in _LANGS if name.endswith(lang.SUFFIXES)), None)


def iter_source_files(root: Path) -> Iterator[tuple[Path, Any]]:
    """Yield (path, language module) in a stable order, skipping vendored and test code."""
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for filename in sorted(filenames):
            path = Path(dirpath) / filename
            lang = _language(path)
            if lang is None or path.is_symlink():
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            yield path, lang
            count += 1
            if count >= MAX_FILES:
                return


@dataclass
class Extraction:
    tools: list[Tool] = field(default_factory=list)
    files_scanned: int = 0
    languages: Counter = field(default_factory=Counter)


def _parse(lang: Any, path: Path, source: bytes) -> Any:
    if lang is typescript:
        return typescript.parse(source, path.suffix)
    return lang.parse(source)


def _valid(text: str | None) -> str | None:
    """Join escaped surrogate pairs and replace lone halves, so the text encodes as UTF-8."""
    if text is None:
        return None
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def extract_repo(
    repo_root: Path,
    *,
    repo_url: str,
    commit: str,
    subfolder: str | None = None,
    server_name: str | None = None,
) -> Extraction:
    """Extract tools under ``repo_root/subfolder``. Paths are relative to ``repo_root``."""
    repo_root = Path(repo_root)
    scan_root = (repo_root / subfolder) if subfolder else repo_root
    result = Extraction()
    if not scan_root.is_dir():
        return result

    units: list[tuple[Path, Any, Any, Scope]] = []
    tables: dict[Any, dict] = {lang: {} for lang in _LANGS}
    for path, lang in iter_source_files(scan_root):
        try:
            tree = _parse(lang, path, path.read_bytes())
        except OSError:
            continue
        if tree is None:
            continue
        scope = Scope(lang.constants(tree), tables[lang])
        register(tables[lang], scope)
        units.append((path, lang, tree, scope))
        result.files_scanned += 1
        result.languages[lang.LANGUAGE] += 1

    tools = result.tools
    for path, lang, tree, scope in units:
        rel = path.relative_to(repo_root).as_posix()
        for f in lang.extract(tree, scope):
            tools.append(
                Tool(
                    repo_url=repo_url,
                    commit=commit,
                    path=rel,
                    line=f.line,
                    language=lang.LANGUAGE,
                    pattern=f.pattern,
                    name=_valid(f.name),
                    description=_valid(f.description),
                    description_resolved=f.description_resolved,
                    params=[replace(p, name=_valid(p.name), text=_valid(p.text)) for p in f.params],
                    server_name=server_name,
                )
            )
    tools.sort(key=Tool.sort_key)
    return result
