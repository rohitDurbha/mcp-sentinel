import json
from pathlib import Path

import httpx

from mcp_watcher.registry import iter_servers

FIXTURES = Path(__file__).parent / "fixtures" / "registry"


def make_client(seen: list[httpx.Request]) -> httpx.Client:
    pages = {
        None: json.loads((FIXTURES / "page1.json").read_text()),
        "abc": json.loads((FIXTURES / "page2.json").read_text()),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=pages[request.url.params.get("cursor")])

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://reg.test")


def test_paginates_and_parses_servers():
    seen: list[httpx.Request] = []
    servers = list(iter_servers(make_client(seen)))

    assert [s.name for s in servers] == [
        "io.github.acme/weather",
        "io.github.acme/mono-a",
        "com.example/remote-only",
    ]
    assert len(seen) == 2
    assert seen[0].url.params["version"] == "latest"
    assert seen[1].url.params["cursor"] == "abc"

    weather, mono, remote = servers
    assert weather.repo_url == "https://github.com/acme/weather"
    assert weather.package_types == ("npm",)
    assert weather.updated_at == "2026-10-01T00:00:00Z"
    assert mono.subfolder == "servers/a"
    assert mono.has_remote
    assert remote.repo_url is None


def test_retries_on_server_error():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"servers": [], "metadata": {}})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://reg.test")
    assert list(iter_servers(client, backoff=0)) == []
    assert calls["n"] == 2
