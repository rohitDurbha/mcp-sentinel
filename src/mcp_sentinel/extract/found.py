from __future__ import annotations

from dataclasses import dataclass, field

from ..models import ParamText


@dataclass
class Found:
    """A tool located inside one file, before repo-level fields are attached."""

    line: int
    pattern: str
    name: str | None
    description: str
    description_resolved: bool
    params: list[ParamText] = field(default_factory=list)
