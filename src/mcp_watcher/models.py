"""Records shared by every pipeline stage."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Server:
    """One server entry from the official MCP registry (latest version only)."""

    name: str
    description: str
    version: str
    repo_url: str | None
    subfolder: str | None = None
    title: str | None = None
    package_types: tuple[str, ...] = ()
    has_remote: bool = False
    status: str = "active"
    updated_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ParamText:
    """Description text attached to one input parameter of a tool."""

    name: str | None
    text: str


@dataclass
class Tool:
    """One tool definition found statically in a repository."""

    repo_url: str
    commit: str
    path: str
    line: int
    language: str
    pattern: str
    name: str | None
    description: str
    description_resolved: bool
    params: list[ParamText] = field(default_factory=list)
    server_name: str | None = None

    def sort_key(self) -> tuple:
        return (self.repo_url, self.path, self.line, self.name or "")

    def to_dict(self) -> dict:
        return asdict(self)
