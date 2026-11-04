import gzip
import json
from pathlib import Path

import pytest

from mcp_watcher.fetch import FetchError
from mcp_watcher.models import Server
from mcp_watcher.pipeline import Sources, run_pipeline

FIXTURES = Path(__file__).parent / "fixtures"
A, B = "https://github.com/acme/py", "https://github.com/acme/ts"
SERVERS = [
    Server(name="io.github.acme/py", description="", version="1", repo_url=A),
    Server(name="io.github.acme/ts", description="", version="1", repo_url=B),
    Server(name="com.example/remote", description="", version="1", repo_url=None),
]


class FakeForge:
    """Stands in for git so tests never touch the network."""

    def __init__(self, heads: dict[str, str]):
        self.heads = dict(heads)
        self.cloned: list[str] = []
        self.down: set[str] = set()

    def remote_head(self, url: str) -> str:
        if url in self.down:
            raise FetchError("unreachable")
        return self.heads[url]

    def clone(self, url: str, cache: Path) -> tuple[Path, str]:
        self.cloned.append(url)
        return FIXTURES / ("python" if url == A else "ts"), self.heads[url]


def run(forge, tmp_path, name, previous=None, now="2026-11-02T00:00:00Z"):
    out = tmp_path / name
    summary = run_pipeline(
        SERVERS,
        previous=previous,
        out=out,
        cache=tmp_path / "cache",
        now=now,
        sources=Sources(remote_head=forge.remote_head, clone=forge.clone),
        workers=2,
    )
    return out, summary


def rows(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def test_first_run_extracts_everything_and_writes_outputs(tmp_path):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    out, summary = run(forge, tmp_path, "day1")
    assert sorted(forge.cloned) == [A, B]
    for name in (
        "servers.jsonl.gz",
        "tools.jsonl.gz",
        "findings.jsonl.gz",
        "state.json",
        "summary.json",
        "history.jsonl",
    ):
        assert (out / name).exists(), name
    assert summary["tools"] == len(rows(out / "tools.jsonl.gz")) > 0
    assert summary["jobs"] == {"no_repo": 1, "ok": 2}
    assert summary["repos_cloned"] == 2 and summary["jobs_reused"] == 0
    assert {r["server_name"] for r in rows(out / "tools.jsonl.gz")} == {
        "io.github.acme/py",
        "io.github.acme/ts",
    }


def test_second_run_reuses_unchanged_repos_without_cloning(tmp_path):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    day1, _ = run(forge, tmp_path, "day1")
    forge.cloned.clear()
    day2, summary = run(forge, tmp_path, "day2", previous=day1, now="2026-11-03T00:00:00Z")
    assert forge.cloned == []
    assert summary["jobs_reused"] == 2
    assert rows(day2 / "tools.jsonl.gz") == rows(day1 / "tools.jsonl.gz")
    history = (day2 / "history.jsonl").read_text().splitlines()
    assert [json.loads(h)["generated_at"] for h in history] == [
        "2026-11-02T00:00:00Z",
        "2026-11-03T00:00:00Z",
    ]


def test_changed_commit_triggers_a_fresh_extraction(tmp_path):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    day1, _ = run(forge, tmp_path, "day1")
    forge.cloned.clear()
    forge.heads[B] = "c" * 40
    day2, _ = run(forge, tmp_path, "day2", previous=day1)
    assert forge.cloned == [B]
    assert {t["commit"] for t in rows(day2 / "tools.jsonl.gz") if t["repo_url"] == B} == {"c" * 40}


def test_unreachable_repo_keeps_previous_tools_marked_stale(tmp_path):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    day1, _ = run(forge, tmp_path, "day1")
    forge.down.add(A)
    day2, summary = run(forge, tmp_path, "day2", previous=day1)
    assert summary["jobs"]["stale"] == 1
    assert any(t["repo_url"] == A for t in rows(day2 / "tools.jsonl.gz"))


def test_unreachable_on_first_sight_is_recorded_without_tools(tmp_path):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    forge.down.add(A)
    out, summary = run(forge, tmp_path, "day1")
    assert summary["jobs"]["unreachable"] == 1
    state = json.loads((out / "state.json").read_text())
    assert state["jobs"]["io.github.acme/py"]["status"] == "unreachable"


def test_extractor_version_change_invalidates_the_cache(tmp_path, monkeypatch):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    day1, _ = run(forge, tmp_path, "day1")
    forge.cloned.clear()
    monkeypatch.setattr("mcp_watcher.pipeline.EXTRACTOR_VERSION", "999")
    run(forge, tmp_path, "day2", previous=day1)
    assert sorted(forge.cloned) == [A, B]


def test_output_bytes_are_identical_for_identical_input(tmp_path):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    one, _ = run(forge, tmp_path, "one")
    two, _ = run(forge, tmp_path, "two")
    for name in (
        "servers.jsonl.gz",
        "tools.jsonl.gz",
        "findings.jsonl.gz",
        "flagged.jsonl.gz",
        "state.json",
        "summary.json",
    ):
        assert (one / name).read_bytes() == (two / name).read_bytes(), name


def test_new_flags_are_reported_against_the_previous_run(tmp_path):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    day1, s1 = run(forge, tmp_path, "day1")
    assert s1["new_flags"] == []  # nothing to compare against on the first run
    _, s2 = run(forge, tmp_path, "day2", previous=day1)
    assert s2["new_flags"] == [] and s2["cleared_flags"] == []


@pytest.mark.parametrize("bad", ["", "not-a-dir"])
def test_missing_previous_directory_is_a_first_run(tmp_path, bad):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    _, summary = run(forge, tmp_path, "day1", previous=(tmp_path / bad) if bad else None)
    assert summary["jobs_reused"] == 0


def test_shared_repo_folder_is_extracted_once_for_all_its_servers(tmp_path, monkeypatch):
    import mcp_watcher.pipeline as pipeline

    calls = []
    real = pipeline.extract_repo

    def counting(*args, **kwargs):
        calls.append(kwargs["subfolder"])
        return real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "extract_repo", counting)
    servers = [
        Server(name="io.github.acme/one", description="", version="1", repo_url=A),
        Server(name="io.github.acme/two", description="", version="1", repo_url=A),
    ]
    forge = FakeForge({A: "a" * 40})
    run_pipeline(
        servers,
        previous=None,
        out=tmp_path / "out",
        cache=tmp_path / "cache",
        now="2026-11-02T00:00:00Z",
        sources=Sources(remote_head=forge.remote_head, clone=forge.clone),
    )
    assert calls == [None]
    tools = rows(tmp_path / "out" / "tools.jsonl.gz")
    by_server = {
        name: [t for t in tools if t["server_name"] == name]
        for name in ("io.github.acme/one", "io.github.acme/two")
    }
    assert len(by_server["io.github.acme/one"]) == len(by_server["io.github.acme/two"]) > 0


def test_progress_is_logged_to_stderr(tmp_path, capsys):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    run(forge, tmp_path, "day1")
    err = capsys.readouterr().err
    assert "heads checked" in err and "extracted 2/2 repos" in err


def test_time_budget_publishes_partial_results_and_marks_the_rest_pending(tmp_path):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    out = tmp_path / "day1"
    summary = run_pipeline(
        SERVERS,
        previous=None,
        out=out,
        cache=tmp_path / "cache",
        now="2026-11-02T00:00:00Z",
        sources=Sources(remote_head=forge.remote_head, clone=forge.clone),
        workers=1,
        budget_seconds=0,
    )
    assert forge.cloned == []
    assert summary["jobs"] == {"no_repo": 1, "pending": 2}
    assert (out / "summary.json").exists()
    # the next run picks the pending repos up
    _, s2 = run(forge, tmp_path, "day2", previous=out)
    assert sorted(forge.cloned) == [A, B] and s2["jobs"]["ok"] == 2


def test_pending_repo_keeps_its_previous_tools(tmp_path):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    day1, _ = run(forge, tmp_path, "day1")
    forge.heads[A] = "c" * 40
    out = tmp_path / "day2"
    run_pipeline(
        SERVERS,
        previous=day1,
        out=out,
        cache=tmp_path / "cache",
        now="2026-11-03T00:00:00Z",
        sources=Sources(remote_head=forge.remote_head, clone=forge.clone),
        budget_seconds=0,
    )
    assert any(t["repo_url"] == A for t in rows(out / "tools.jsonl.gz"))


def test_process_pool_gives_the_same_tools_as_threads(tmp_path):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    threaded, _ = run(forge, tmp_path, "threads")
    out = tmp_path / "procs"
    run_pipeline(
        SERVERS,
        previous=None,
        out=out,
        cache=tmp_path / "cache",
        now="2026-11-02T00:00:00Z",
        sources=Sources(remote_head=forge.remote_head, clone=forge.clone),
        procs=2,
    )
    assert (out / "tools.jsonl.gz").read_bytes() == (threaded / "tools.jsonl.gz").read_bytes()


def test_summary_counts_unique_tools_and_names_the_largest_repos(tmp_path):
    copy = Server(name="io.github.acme/py-copy", description="", version="1", repo_url=A)
    servers = [*SERVERS, copy]
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    summary = run_pipeline(
        servers,
        previous=None,
        out=tmp_path / "out",
        cache=tmp_path / "cache",
        now="2026-11-02T00:00:00Z",
        sources=Sources(remote_head=forge.remote_head, clone=forge.clone),
    )
    assert summary["tools_unique"] < summary["tools"]
    top = summary["largest_repos"][0]
    assert top["repo_url"] == A and top["servers"] == 2 and top["tools"] > 0


def test_extractor_crash_fails_one_repo_and_the_run_continues(tmp_path, monkeypatch, capsys):
    import mcp_watcher.pipeline as pipeline

    real = pipeline.extract_repo

    def flaky(path, *, repo_url, **kwargs):
        if repo_url == B:
            raise AttributeError("boom")
        return real(path, repo_url=repo_url, **kwargs)

    monkeypatch.setattr(pipeline, "extract_repo", flaky)
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    out, summary = run(forge, tmp_path, "day1")
    assert summary["jobs"] == {"no_repo": 1, "ok": 1, "extract_failed": 1}
    state = json.loads((out / "state.json").read_text())
    failed = [j for j in state["jobs"].values() if j["status"] == "extract_failed"]
    assert failed[0]["error"] == "AttributeError: boom"
    assert "extract failed for https://github.com/acme/ts" in capsys.readouterr().err


def test_flagged_file_holds_only_flagged_tools_with_their_text(tmp_path):
    class PoisonedForge(FakeForge):
        def clone(self, url, cache):
            path, commit = super().clone(url, cache)
            return (FIXTURES / "python3" if url == B else path), commit

    forge = PoisonedForge({A: "a" * 40, B: "b" * 40})
    out, summary = run(forge, tmp_path, "day1")
    flagged = rows(out / "flagged.jsonl.gz")
    assert len(flagged) == summary["levels"]["medium"] + summary["levels"]["high"] > 0
    tools = {
        (t["server_name"], t["path"], t["line"], t["name"]): t for t in rows(out / "tools.jsonl.gz")
    }
    for r in flagged:
        tool = tools[(r["server_name"], r["path"], r["line"], r["name"])]
        assert r["level"] in ("medium", "high")
        assert (r["description"], r["params"]) == (tool["description"], tool["params"])
    distinct = {(r["repo_url"], r["path"], r["line"], r["name"]): r["level"] for r in flagged}
    assert summary["flagged_unique"] == {
        level: sum(v == level for v in distinct.values()) for level in ("high", "medium")
    }


def test_previous_snapshot_without_tools_is_not_reused(tmp_path):
    forge = FakeForge({A: "a" * 40, B: "b" * 40})
    day1, _ = run(forge, tmp_path, "day1")
    (day1 / "tools.jsonl.gz").unlink()  # the public data branch carries no tools file
    forge.cloned.clear()
    day2, summary = run(forge, tmp_path, "day2", previous=day1)
    assert sorted(forge.cloned) == [A, B] and summary["jobs_reused"] == 0
    assert len((day2 / "history.jsonl").read_text().splitlines()) == 2
