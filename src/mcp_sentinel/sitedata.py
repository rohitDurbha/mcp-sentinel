"""Turn the public snapshot on the data branch into the small JSON files the site reads."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .pipeline import read_gz_jsonl

LEVELS = ("none", "low", "medium", "high")
DISPUTE_STATUSES = ("open", "confirmed", "cleared")
COLUMNS = (
    "name",
    "title",
    "description",
    "repo_url",
    "subfolder",
    "status",
    "tools",
    "flags",
    "level",
)
PER_SERVER = ("server_name",)  # dropped from a flag, which lists all its servers instead


def _dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _source_url(row: dict) -> str:
    repo = row["repo_url"].rstrip("/").removesuffix(".git")
    return f"{repo}/blob/{row['commit']}/{row['path']}#L{row['line']}"


def _load_disputes(path: Path | None) -> dict[tuple[str, str, str], dict]:
    if path is None or not Path(path).exists():
        return {}
    out = {}
    for d in json.loads(Path(path).read_text()):
        if d.get("status") not in DISPUTE_STATUSES:
            raise ValueError(f"dispute status must be one of {DISPUTE_STATUSES}: {d.get('status')}")
        dispute = {k: d.get(k, "") for k in ("status", "note", "issue")}
        out[(d["repo_url"], d["path"], d["name"])] = dispute
    return out


def _flags(rows: list[dict], disputes: dict) -> list[dict]:
    """One record per distinct tool, since many registry entries share one repository."""
    grouped: dict[tuple, dict] = {}
    for row in rows:
        key = (row["repo_url"], row["path"], row["line"], row["name"])
        if key not in grouped:
            flag = {k: v for k, v in row.items() if k not in PER_SERVER}
            digest = hashlib.sha1("|".join(map(str, key)).encode()).hexdigest()
            flag |= {"id": digest[:12], "source_url": _source_url(row), "servers": []}
            dispute = disputes.get((row["repo_url"], row["path"], row["name"]))
            if dispute:
                flag["dispute"] = dispute
            grouped[key] = flag
        grouped[key]["servers"].append(row["server_name"])
    for flag in grouped.values():
        flag["servers"].sort()
    return [grouped[k] for k in sorted(grouped)]


def _counts(flags: list[dict]) -> dict[str, tuple[int, str]]:
    """Flag count and highest level per server, leaving out flags cleared by review."""
    out: dict[str, tuple[int, str]] = {}
    for flag in flags:
        if flag.get("dispute", {}).get("status") == "cleared":
            continue
        for name in flag["servers"]:
            count, top = out.get(name, (0, "none"))
            top = max(top, flag["level"], key=LEVELS.index)
            out[name] = (count + 1, top)
    return out


def build_site(
    public: Path, out: Path, *, static: Path, disputes: Path | None = None
) -> dict[str, int]:
    public, out = Path(public), Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(static, out)
    (out / "data").mkdir(exist_ok=True)

    flags = _flags(read_gz_jsonl(public / "flagged.jsonl.gz"), _load_disputes(disputes))
    counts = _counts(flags)
    jobs = json.loads((public / "state.json").read_text())["jobs"]
    rows = []
    for s in sorted(read_gz_jsonl(public / "servers.jsonl.gz"), key=lambda s: s["name"]):
        job = jobs.get(s["name"], {})
        count, top = counts.get(s["name"], (0, "none"))
        values = (s.get("title"), s.get("description"), s.get("repo_url"), s.get("subfolder"))
        rows.append(
            [
                s["name"],
                *(v or "" for v in values),
                job.get("status", ""),
                job.get("tools", 0),
                count,
                top,
            ]
        )

    lines = (public / "history.jsonl").read_text().splitlines()
    history = [json.loads(line) for line in lines if line.strip()]
    _dump(out / "data" / "servers.json", {"columns": list(COLUMNS), "rows": rows})
    _dump(out / "data" / "flags.json", flags)
    _dump(out / "data" / "summary.json", json.loads((public / "summary.json").read_text()))
    _dump(out / "data" / "history.json", history)
    return {"servers": len(rows), "flags": len(flags)}
