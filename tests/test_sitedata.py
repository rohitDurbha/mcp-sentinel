import json

import pytest

from mcp_sentinel.pipeline import write_gz_jsonl, write_json
from mcp_sentinel.sitedata import build_site

REPO = "https://github.com/acme/tools"


def finding(evidence="never tell the user", severity="high"):
    return {
        "signal": "secrecy",
        "severity": severity,
        "rule": "hide-from-user",
        "field": "description",
        "start": 4,
        "end": 4 + len(evidence),
        "evidence": evidence,
        "message": "Asks the model to hide something from the user",
    }


def flagged_row(server, name="lookup", level="high", line=12):
    return {
        "repo_url": REPO,
        "commit": "c" * 40,
        "path": "src/tools.ts",
        "line": line,
        "name": name,
        "server_name": server,
        "rule_score": 0.6,
        "rule_level": level,
        "level": level,
        "findings": [finding()],
        "model": {"version": "m1", "score": 0.2, "flag": False},
        "description": "and never tell the user",
        "params": [],
    }


@pytest.fixture
def public(tmp_path):
    d = tmp_path / "public"
    d.mkdir()
    servers = [
        {"name": "io.acme/b", "title": "B", "description": "Second", "repo_url": REPO},
        {"name": "io.acme/a", "title": "A", "description": "First", "repo_url": REPO},
        {"name": "com.remote/only", "title": None, "description": "Remote", "repo_url": None},
    ]
    write_gz_jsonl(d / "servers.jsonl.gz", servers)
    jobs = {
        "io.acme/a": {"status": "ok", "tools": 3, "repo_url": REPO, "subfolder": None},
        "io.acme/b": {"status": "ok", "tools": 3, "repo_url": REPO, "subfolder": None},
        "com.remote/only": {"status": "no_repo", "tools": 0, "repo_url": None},
    }
    write_json(d / "state.json", {"extractor_version": "2", "jobs": jobs})
    rows = [
        flagged_row("io.acme/a"),
        flagged_row("io.acme/b"),
        flagged_row("io.acme/a", name="fetch", level="medium", line=40),
    ]
    write_gz_jsonl(d / "flagged.jsonl.gz", rows)
    write_json(d / "summary.json", {"generated_at": "2026-11-03T08:30:48Z", "servers": 3})
    (d / "history.jsonl").write_text('{"generated_at": "a"}\n{"generated_at": "b"}\n')
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html>")
    return d, static


def build(public, tmp_path, disputes=None):
    data, static = public
    out = tmp_path / "site"
    build_site(data, out, static=static, disputes=disputes)
    return out, {p.stem: json.loads(p.read_text()) for p in (out / "data").glob("*.json")}


def test_index_has_one_row_per_server_with_flag_counts(public, tmp_path):
    _, data = build(public, tmp_path)
    cols = data["servers"]["columns"]
    rows = [dict(zip(cols, r, strict=True)) for r in data["servers"]["rows"]]
    assert [r["name"] for r in rows] == ["com.remote/only", "io.acme/a", "io.acme/b"]
    a = rows[1]
    assert (a["status"], a["tools"], a["flags"], a["level"]) == ("ok", 3, 2, "high")
    assert (rows[0]["flags"], rows[0]["level"]) == (0, "none")


def test_flags_are_distinct_tools_listing_every_server_and_the_source_line(public, tmp_path):
    _, data = build(public, tmp_path)
    flags = {f["name"]: f for f in data["flags"]}
    assert set(flags) == {"lookup", "fetch"}
    lookup = flags["lookup"]
    assert lookup["servers"] == ["io.acme/a", "io.acme/b"]
    assert lookup["source_url"] == f"{REPO}/blob/{'c' * 40}/src/tools.ts#L12"
    assert lookup["findings"][0]["evidence"] == "never tell the user"
    assert len(lookup["id"]) == 12 and lookup["id"] != flags["fetch"]["id"]
    assert "server_name" not in lookup


def test_disputes_keep_open_flags_visible_and_drop_cleared_ones_from_counts(public, tmp_path):
    disputes = tmp_path / "disputes.json"
    disputes.write_text(
        json.dumps(
            [
                {
                    "repo_url": REPO,
                    "path": "src/tools.ts",
                    "name": "lookup",
                    "status": "cleared",
                    "note": "The phrase protects users from a false claim.",
                    "issue": "https://github.com/rohitDurbha/mcp-sentinel/issues/1",
                },
                {
                    "repo_url": REPO,
                    "path": "src/tools.ts",
                    "name": "fetch",
                    "status": "open",
                    "note": "",
                    "issue": "https://github.com/rohitDurbha/mcp-sentinel/issues/2",
                },
            ]
        )
    )
    _, data = build(public, tmp_path, disputes=disputes)
    flags = {f["name"]: f for f in data["flags"]}
    assert flags["lookup"]["dispute"]["status"] == "cleared"
    assert flags["fetch"]["dispute"]["status"] == "open"
    cols = data["servers"]["columns"]
    a = dict(zip(cols, data["servers"]["rows"][1], strict=True))
    assert (a["flags"], a["level"]) == (1, "medium")


def test_unknown_dispute_status_is_rejected(public, tmp_path):
    disputes = tmp_path / "disputes.json"
    disputes.write_text(
        json.dumps([{"repo_url": REPO, "path": "x", "name": "y", "status": "gone"}])
    )
    with pytest.raises(ValueError, match="gone"):
        build(public, tmp_path, disputes=disputes)


def test_site_carries_summary_history_and_static_files_deterministically(public, tmp_path):
    out, data = build(public, tmp_path)
    assert data["summary"]["servers"] == 3
    assert [h["generated_at"] for h in data["history"]] == ["a", "b"]
    assert (out / "index.html").read_text() == "<!doctype html>"
    again = tmp_path / "again"
    build_site(public[0], again, static=public[1])
    for p in (out / "data").glob("*.json"):
        assert p.read_bytes() == (again / "data" / p.name).read_bytes(), p.name
