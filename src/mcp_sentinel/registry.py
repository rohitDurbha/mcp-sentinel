"""Client for the official MCP registry (https://registry.modelcontextprotocol.io)."""

from __future__ import annotations

import time
from collections.abc import Iterator

import httpx

from .fetch import normalize_repo_url
from .models import Server

DEFAULT_BASE_URL = "https://registry.modelcontextprotocol.io"
USER_AGENT = "mcp-sentinel/0.1 (+https://github.com/rohitDurbha/mcp-sentinel)"
_OFFICIAL = "io.modelcontextprotocol.registry/official"
_RETRY_STATUS = {429, 500, 502, 503, 504}


def make_client(base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(base_url=base_url, timeout=timeout, headers={"User-Agent": USER_AGENT})


def _get(client: httpx.Client, params: dict, retries: int, backoff: float) -> dict:
    for attempt in range(retries + 1):
        try:
            resp = client.get("/v0.1/servers", params=params)
        except httpx.TransportError:
            if attempt == retries:
                raise
        else:
            if resp.status_code not in _RETRY_STATUS or attempt == retries:
                resp.raise_for_status()
                return resp.json()
        time.sleep(backoff * 2**attempt)
    raise RuntimeError("unreachable")


def _parse(item: dict) -> Server | None:
    server = item.get("server") or {}
    meta = (item.get("_meta") or {}).get(_OFFICIAL) or {}
    if not server.get("name"):
        return None
    repo = server.get("repository") or {}
    normalized = normalize_repo_url(repo.get("url") or "")
    repo_url, url_subfolder = normalized if normalized else (None, None)
    subfolder = repo.get("subfolder") or url_subfolder
    if subfolder and (".." in subfolder.split("/") or subfolder.startswith("/")):
        subfolder = None
    return Server(
        name=server["name"],
        description=server.get("description") or "",
        version=server.get("version") or "",
        repo_url=repo_url,
        subfolder=subfolder.strip("/") if subfolder else None,
        title=server.get("title"),
        package_types=tuple(p.get("registryType", "") for p in server.get("packages") or []),
        has_remote=bool(server.get("remotes")),
        status=meta.get("status") or "active",
        updated_at=meta.get("updatedAt"),
    )


def iter_servers(
    client: httpx.Client,
    *,
    page_size: int = 100,
    updated_since: str | None = None,
    retries: int = 4,
    backoff: float = 1.0,
) -> Iterator[Server]:
    """Yield the latest version of every non-deleted server, following cursors to the end."""
    cursor: str | None = None
    seen_names: set[str] = set()
    seen_cursors: set[str] = set()
    while True:
        params: dict = {"version": "latest", "limit": page_size}
        if cursor:
            params["cursor"] = cursor
        if updated_since:
            params["updated_since"] = updated_since
        data = _get(client, params, retries, backoff)
        for item in data.get("servers") or []:
            server = _parse(item)
            if server and server.status != "deleted" and server.name not in seen_names:
                seen_names.add(server.name)
                yield server
        cursor = (data.get("metadata") or {}).get("nextCursor")
        if not cursor or cursor in seen_cursors:
            return
        seen_cursors.add(cursor)
