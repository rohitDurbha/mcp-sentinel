"""The daily run: discover, check commits, extract what changed, score, publish.

A repository is cloned only when its default-branch commit differs from the previous run
or the extractor itself has changed. Everything the next run needs lives in the output
directory, which the workflow stores on the ``data`` branch.
"""

from __future__ import annotations

import gzip
import io
import json
import multiprocessing
import shutil
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from . import fetch
from .extract import extract_repo
from .fetch import FetchError
from .models import ParamText, Server, Tool
from .redact import redact
from .scoring import score_tools, tool_from_row

# Bump whenever a change to extraction could change its output, so cached repos rescan.
EXTRACTOR_VERSION = "2"
FLAGGED = ("medium", "high")
PROGRESS_EVERY = 100
LARGEST_REPOS = 25
SLOW_REPO_SECONDS = 60


@dataclass(frozen=True)
class Sources:
    remote_head: Callable[[str], str] = fetch.remote_head
    clone: Callable[[str, Path], tuple[Path, str]] = fetch.clone


@dataclass(frozen=True)
class Job:
    key: str
    server_name: str
    repo_url: str | None
    subfolder: str | None


# Files


def write_gz_jsonl(path: Path, records: Iterable[dict]) -> None:
    """Gzip with a fixed timestamp so identical data gives identical bytes."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        for record in records:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            gz.write(line.encode("utf-8"))
    path.write_bytes(buf.getvalue())


def read_gz_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _log(message: str) -> None:
    """Progress goes to stderr so long runs show where they are in the Actions log."""
    print(message, file=sys.stderr, flush=True)


# Steps


def _jobs(servers: list[Server]) -> list[Job]:
    return sorted(
        (Job(s.name, s.name, s.repo_url, s.subfolder) for s in servers), key=lambda j: j.key
    )


def _redacted(tool: Tool) -> Tool:
    params = [ParamText(p.name, redact(p.text)) for p in tool.params]
    return replace(tool, description=redact(tool.description), params=params)


def _flag_ids(findings: list[dict]) -> set[str]:
    return {
        f"{r['server_name']}|{r['path']}|{r['name']}" for r in findings if r["level"] in FLAGGED
    }


def _flagged(tools: list[Tool], findings: list[dict]) -> Iterable[dict]:
    """Flagged findings with the text they were found in, small enough to publish."""
    for tool, record in zip(tools, findings, strict=True):
        if record["level"] in FLAGGED:
            text = {"description": tool.description, "params": tool.to_dict()["params"]}
            yield record | text


def _share(tools: list[Tool]) -> float | None:
    return round(sum(t.description_resolved for t in tools) / len(tools), 4) if tools else None


def run_pipeline(
    servers: list[Server],
    *,
    previous: Path | None,
    out: Path,
    cache: Path,
    now: str,
    model: Any = None,
    sources: Sources | None = None,
    workers: int = 8,
    procs: int = 0,
    budget_seconds: float | None = None,
) -> dict:
    """Run one snapshot.

    ``procs`` moves parsing into that many processes, because parsing is CPU bound and threads
    share one core. After ``budget_seconds`` no new repo is started, and the jobs left over are
    published as ``pending`` so the run still finishes and the next one picks them up.
    """
    sources = sources or Sources()
    deadline = None if budget_seconds is None else time.monotonic() + budget_seconds
    prev_dir = previous if previous is not None and Path(previous).is_dir() else None
    prev_state = _read_json(prev_dir / "state.json") if prev_dir else {}
    prev_jobs = prev_state.get("jobs", {})
    # Reuse needs the previous tools, which live in the run cache and not on the public branch.
    same_extractor = (
        prev_state.get("extractor_version") == EXTRACTOR_VERSION
        and (prev_dir / "tools.jsonl.gz").exists()
    )
    prev_tools: dict[str, list[dict]] = defaultdict(list)
    for row in read_gz_jsonl(prev_dir / "tools.jsonl.gz") if prev_dir else []:
        prev_tools[row["server_name"]].append(row)

    jobs = _jobs(servers)
    urls = sorted({j.repo_url for j in jobs if j.repo_url})

    def head(url: str) -> tuple[str, str | None, str | None]:
        try:
            return url, sources.remote_head(url), None
        except FetchError as exc:
            return url, None, str(exc)

    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        heads = {url: (sha, err) for url, sha, err in pool.map(head, urls)}
    _log(f"heads checked for {len(urls)} repos in {time.monotonic() - started:.0f}s")

    def reusable(job: Job) -> bool:
        prev = prev_jobs.get(job.key)
        sha = heads.get(job.repo_url, (None, None))[0]
        return bool(
            same_extractor
            and prev
            and prev.get("status") in ("ok", "no_supported_source")
            and prev.get("commit") == sha
            and prev.get("subfolder") == job.subfolder
            and prev.get("repo_url") == job.repo_url
        )

    to_extract: dict[str, list[Job]] = defaultdict(list)
    for job in jobs:
        if job.repo_url and heads[job.repo_url][0] and not reusable(job):
            to_extract[job.repo_url].append(job)

    parsers = (
        ProcessPoolExecutor(procs, mp_context=multiprocessing.get_context("spawn"))
        if procs > 0
        else None
    )

    def extract(path: Path, url: str, commit: str, subfolder: str | None) -> Any:
        if parsers is None:
            return extract_repo(path, repo_url=url, commit=commit, subfolder=subfolder)
        future = parsers.submit(
            extract_repo, path, repo_url=url, commit=commit, subfolder=subfolder
        )
        return future.result()

    def work(url: str) -> tuple[list[tuple[Job, dict, list[Tool]]], float] | None:
        started = time.monotonic()
        if deadline is not None and started >= deadline:
            return None
        try:
            path, commit = sources.clone(url, cache)
        except FetchError as exc:
            failed = {"status": "clone_failed", "error": str(exc)}
            return [(j, failed, []) for j in to_extract[url]], time.monotonic() - started
        results = []
        by_folder: dict[str | None, Any] = {}  # many registry entries can share one folder
        try:
            for j in to_extract[url]:
                if j.subfolder not in by_folder:
                    try:
                        by_folder[j.subfolder] = extract(path, url, commit, j.subfolder)
                    except Exception as exc:  # one odd repo must not sink the whole run
                        by_folder[j.subfolder] = f"{type(exc).__name__}: {exc}"
                        _log(f"extract failed for {url}: {by_folder[j.subfolder]}")
                ex = by_folder[j.subfolder]
                if isinstance(ex, str):
                    failed = {"status": "extract_failed", "commit": commit, "error": ex}
                    results.append((j, failed, []))
                    continue
                status = "ok" if ex.files_scanned else "no_supported_source"
                info = {"status": status, "commit": commit, "files_scanned": ex.files_scanned}
                tools = [replace(t, server_name=j.server_name) for t in ex.tools]
                results.append((j, info, tools))
        finally:
            if Path(path).resolve().is_relative_to(Path(cache).resolve()):
                shutil.rmtree(path, ignore_errors=True)  # keep runner disk usage flat
        return results, time.monotonic() - started

    batches = []
    skipped = 0
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(work, url): url for url in sorted(to_extract)}
            for done, future in enumerate(as_completed(futures), 1):
                outcome = future.result()
                if outcome is None:
                    skipped += 1
                else:
                    batch, seconds = outcome
                    batches.append(batch)
                    if seconds >= SLOW_REPO_SECONDS:
                        _log(f"slow repo {futures[future]} took {seconds:.0f}s")
                if done % PROGRESS_EVERY == 0 or done == len(futures):
                    _log(f"extracted {done - skipped}/{len(futures)} repos")
    finally:
        if parsers is not None:
            parsers.shutdown()
    if skipped:
        _log(f"time budget reached, {skipped} repos left pending for the next run")
    fresh = {j.key: (info, tools) for batch in batches for j, info, tools in batch}

    state_jobs: dict[str, dict] = {}
    all_tools: list[Tool] = []
    reused = 0
    for job in jobs:
        base = {"repo_url": job.repo_url, "subfolder": job.subfolder}
        if job.repo_url is None:
            state_jobs[job.key] = {**base, "status": "no_repo", "tools": 0}
            continue
        sha, err = heads[job.repo_url]
        if job.key in fresh:
            info, tools = fresh[job.key]
            tools = [_redacted(t) for t in tools]
        elif sha and reusable(job):
            reused += 1
            kept = ("status", "commit", "files_scanned")
            info = {k: v for k, v in prev_jobs[job.key].items() if k in kept}
            tools = [tool_from_row(r) for r in prev_tools.get(job.key, [])]
        elif job.repo_url in to_extract:  # ran out of time before this repo started
            prev = prev_jobs.get(job.key, {})
            info = {"status": "pending", "commit": prev.get("commit")}
            tools = [tool_from_row(r) for r in prev_tools.get(job.key, [])]
        elif job.key in prev_jobs and prev_jobs[job.key].get("status") in ("ok", "stale"):
            info = {"status": "stale", "commit": prev_jobs[job.key].get("commit"), "error": err}
            tools = [tool_from_row(r) for r in prev_tools.get(job.key, [])]
        else:
            info, tools = {"status": "unreachable", "error": err}, []
        state_jobs[job.key] = {**base, **info, "tools": len(tools)}
        all_tools.extend(tools)

    all_tools.sort(key=lambda t: (t.server_name or "", *t.sort_key()))
    _log(f"scoring {len(all_tools)} tools")
    findings = score_tools(all_tools, model)
    _log("writing outputs")
    prev_findings = read_gz_jsonl(prev_dir / "findings.jsonl.gz") if prev_dir else []
    now_flags, then_flags = _flag_ids(findings), _flag_ids(prev_findings)

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write_gz_jsonl(
        out / "servers.jsonl.gz", (s.to_dict() for s in sorted(servers, key=lambda s: s.name))
    )
    write_gz_jsonl(out / "tools.jsonl.gz", (t.to_dict() for t in all_tools))
    write_gz_jsonl(out / "findings.jsonl.gz", findings)
    write_gz_jsonl(out / "flagged.jsonl.gz", _flagged(all_tools, findings))
    write_json(out / "state.json", {"extractor_version": EXTRACTOR_VERSION, "jobs": state_jobs})

    levels = Counter(r["level"] for r in findings)
    per_repo: dict[str, dict] = defaultdict(lambda: {"servers": set(), "tools": set()})
    for t in all_tools:
        per_repo[t.repo_url]["servers"].add(t.server_name)
        per_repo[t.repo_url]["tools"].add((t.path, t.line, t.name))
    largest = sorted(
        (
            {"repo_url": url, "servers": len(v["servers"]), "tools": len(v["tools"])}
            for url, v in per_repo.items()
        ),
        key=lambda r: (-r["tools"], r["repo_url"]),
    )[:LARGEST_REPOS]
    summary = {
        "generated_at": now,
        "extractor_version": EXTRACTOR_VERSION,
        "model_version": getattr(model, "version", None),
        "servers": len(servers),
        "servers_with_repo": sum(1 for s in servers if s.repo_url),
        "jobs": dict(sorted(Counter(j["status"] for j in state_jobs.values()).items())),
        "repos_checked": len(urls),
        "repos_cloned": len(to_extract),
        "jobs_reused": reused,
        "tools": len(all_tools),
        "tools_unique": sum(len(v["tools"]) for v in per_repo.values()),
        "resolved_share": _share(all_tools),
        "levels": {k: levels[k] for k in ("high", "medium", "low", "none")},
        "new_flags": sorted(now_flags - then_flags) if prev_dir else [],
        "cleared_flags": sorted(then_flags - now_flags) if prev_dir else [],
        "largest_repos": largest,
    }
    write_json(out / "summary.json", summary)

    history_file = prev_dir / "history.jsonl" if prev_dir else None
    history = (
        history_file.read_text().splitlines() if history_file and history_file.exists() else []
    )
    skip = ("new_flags", "cleared_flags", "largest_repos")
    entry = {k: v for k, v in summary.items() if k not in skip}
    entry |= {
        "new_flags": len(summary["new_flags"]),
        "cleared_flags": len(summary["cleared_flags"]),
    }
    history.append(json.dumps(entry, sort_keys=True))
    (out / "history.jsonl").write_text("\n".join(history) + "\n")
    return summary
