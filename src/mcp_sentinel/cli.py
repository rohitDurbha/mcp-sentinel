"""Command line entry point: ``discover``, ``extract`` and ``scan``."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from . import registry
from .extract import extract_repo
from .fetch import FetchError, clone, normalize_repo_url
from .models import ParamText, Tool
from .signals import level, scan_tool, score
from .store import read_jsonl, write_jsonl


@dataclass(frozen=True)
class Job:
    repo_url: str | None
    subfolder: str | None
    server_name: str | None


def cmd_discover(args: argparse.Namespace) -> int:
    with registry.make_client(args.base_url) as client:
        servers = sorted(
            registry.iter_servers(client, updated_since=args.updated_since), key=lambda s: s.name
        )
    n = write_jsonl(args.out, (s.to_dict() for s in servers))
    with_repo = sum(1 for s in servers if s.repo_url)
    print(f"servers: {n}  with fetchable repo: {with_repo}  -> {args.out}")
    return 0


def _jobs(args: argparse.Namespace) -> list[Job]:
    jobs: list[Job] = []
    if args.servers:
        for row in read_jsonl(args.servers):
            jobs.append(Job(row.get("repo_url"), row.get("subfolder"), row["name"]))
    for raw in args.repo or []:
        normalized = normalize_repo_url(raw)
        if normalized is None:
            print(f"skipping unsupported repo url: {raw}", file=sys.stderr)
            continue
        jobs.append(Job(normalized[0], normalized[1], None))
    return jobs[: args.limit] if args.limit else jobs


def cmd_extract(args: argparse.Namespace) -> int:
    jobs = _jobs(args)
    urls = sorted({j.repo_url for j in jobs if j.repo_url})

    def fetch(url: str) -> tuple[str, tuple[Path, str] | str]:
        try:
            return url, clone(url, args.cache)
        except FetchError as exc:
            return url, str(exc)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        clones = dict(pool.map(fetch, urls))

    tools, report = [], []
    for job in jobs:
        entry = {
            "server_name": job.server_name,
            "repo_url": job.repo_url,
            "subfolder": job.subfolder,
        }
        result = clones.get(job.repo_url) if job.repo_url else None
        if job.repo_url is None:
            report.append({**entry, "status": "no_repo", "tools": 0})
            continue
        if isinstance(result, str) or result is None:
            report.append({**entry, "status": "clone_failed", "error": result, "tools": 0})
            continue
        path, commit = result
        found = extract_repo(
            path,
            repo_url=job.repo_url,
            commit=commit,
            subfolder=job.subfolder,
            server_name=job.server_name,
        )
        tools.extend(found.tools)
        report.append(
            {
                **entry,
                "status": "ok" if found.files_scanned else "no_supported_source",
                "commit": commit,
                "files_scanned": found.files_scanned,
                "languages": dict(sorted(found.languages.items())),
                "tools": len(found.tools),
            }
        )

    tools.sort(key=lambda t: (*t.sort_key(), t.server_name or ""))
    write_jsonl(args.out, (t.to_dict() for t in tools))
    report.sort(key=lambda r: (r["repo_url"] or "", r["subfolder"] or "", r["server_name"] or ""))
    write_jsonl(args.report, report)
    _summary(report, tools)
    return 0


def _summary(report: list[dict], tools: list) -> None:
    status = Counter(r["status"] for r in report)
    ok = [r for r in report if r["status"] == "ok"]
    yielded = sum(1 for r in ok if r["tools"] > 0)
    resolved = sum(1 for t in tools if t.description_resolved)
    print(f"jobs: {len(report)}  " + "  ".join(f"{k}: {v}" for k, v in sorted(status.items())))
    if ok:
        print(f"repos yielding tools: {yielded}/{len(ok)} ({yielded / len(ok):.0%})")
    if tools:
        print(f"tools: {len(tools)}  fully resolved descriptions: {resolved / len(tools):.0%}")
        for pattern, n in Counter(t.pattern for t in tools).most_common():
            print(f"  {pattern:<20} {n}")


def _tool_from_row(row: dict) -> Tool:
    params = [ParamText(p["name"], p["text"]) for p in row.get("params") or []]
    return Tool(**{**row, "params": params})


def final_level(rule_level: str, model_flag: bool) -> str:
    """Rules decide the level, and a model flag lifts anything below medium to medium."""
    if model_flag and rule_level in ("none", "low"):
        return "medium"
    return rule_level


def cmd_scan(args: argparse.Namespace) -> int:
    tools = [_tool_from_row(row) for row in read_jsonl(args.tools)]
    model_scores = None
    if args.model:
        from .model import SentinelModel, tool_text

        model = SentinelModel.load(args.model)
        texts = [tool_text(t) for t in tools]
        model_scores = model.decision(texts) if texts else []
    results = []
    for i, tool in enumerate(tools):
        findings = scan_tool(tool)
        value = score(findings)
        record = {
            "repo_url": tool.repo_url,
            "commit": tool.commit,
            "path": tool.path,
            "line": tool.line,
            "name": tool.name,
            "server_name": tool.server_name,
            "rule_score": value,
            "rule_level": level(value),
            "findings": [f.to_dict() for f in findings],
        }
        flag = False
        if model_scores is not None:
            m = round(float(model_scores[i]), 4)
            flag = m >= model.threshold
            record["model"] = {"version": model.version, "score": m, "flag": flag}
            if flag:
                record["model"]["top_terms"] = model.top_terms(texts[i])
        record["level"] = final_level(record["rule_level"], flag)
        results.append(record)
    write_jsonl(args.out, results)
    levels = Counter(r["level"] for r in results)
    print(
        f"tools: {len(results)}  "
        + "  ".join(f"{k}: {levels[k]}" for k in ("high", "medium", "low", "none"))
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mcp-sentinel")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="list servers from the official MCP registry")
    p.add_argument("--out", type=Path, default=Path("data/servers.jsonl"))
    p.add_argument("--base-url", default=registry.DEFAULT_BASE_URL)
    p.add_argument("--updated-since", help="RFC3339 timestamp for incremental pulls")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser("extract", help="clone repos and extract tool definitions")
    p.add_argument("--servers", type=Path, help="servers.jsonl produced by discover")
    p.add_argument("--repo", action="append", help="repository URL, can be repeated")
    p.add_argument("--out", type=Path, default=Path("data/tools.jsonl"))
    p.add_argument("--report", type=Path, default=Path("data/extract_report.jsonl"))
    p.add_argument("--cache", type=Path, default=Path(".cache/repos"))
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--limit", type=int, help="process only the first N jobs")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("scan", help="score extracted tools with the rule-based signals")
    p.add_argument("--tools", type=Path, default=Path("data/tools.jsonl"))
    p.add_argument("--out", type=Path, default=Path("data/findings.jsonl"))
    p.add_argument("--model", type=Path, help="classifier file, e.g. models/sentinel-lr-1.pkl")
    p.set_defaults(func=cmd_scan)

    args = parser.parse_args(argv)
    if args.command == "extract" and not (args.servers or args.repo):
        parser.error("extract needs --servers or --repo")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
