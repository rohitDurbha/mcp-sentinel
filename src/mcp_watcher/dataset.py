"""Turn extracted tools plus hand labels into labeled rows for the classifier."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from .store import read_jsonl


@dataclass(frozen=True)
class Row:
    text: str
    params: tuple[tuple[str, str], ...]
    label: int  # 1 poisoned, 0 benign
    family: str  # attack family for positives, "real_benign" or "benign_note" otherwise
    group: str  # unit for grouped splits and bootstrap (repository or attack family)
    source: str  # "real" or "synthetic"
    key: str  # repo/path:line#name for real rows


def model_text(description: str, params) -> str:
    """The exact string the classifier reads for one tool."""
    parts = [description.strip()]
    parts += [f"[param {name}] {text.strip()}" for name, text in params if text.strip()]
    return "\n".join(p for p in parts if p)


def _repo_slug(url: str) -> str:
    return "/".join(url.rstrip("/").split("/")[-2:]).lower()


def _matches(rule: dict, slug: str, row: dict) -> bool:
    if "repo" in rule and rule["repo"].lower() != slug:
        return False
    path = row["path"]
    if "path" in rule and not (path == rule["path"] or path.startswith(rule["path"])):
        return False
    if "name" in rule and rule["name"] != row["name"]:
        return False
    return "contains" not in rule or rule["contains"] in row["description"]


def load_labels(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def label_tool(row: dict, labels: dict) -> dict | None:
    """Return the first matching rule for an extracted tool, or None."""
    slug = _repo_slug(row["repo_url"])
    return next((r for r in labels["rules"] if _matches(r, slug, row)), None)


def real_rows(tool_files: list[Path], labels: dict) -> tuple[list[Row], dict[str, int]]:
    """Labeled real rows, deduplicated by text. Also returns counts of what was dropped."""
    markers = labels.get("strip_markers", [])
    seen: set[str] = set()
    rows: list[Row] = []
    dropped = {"excluded": 0, "placeholder": 0, "duplicate": 0, "empty": 0}
    for tool_file in tool_files:
        for t in read_jsonl(tool_file):
            rule = label_tool(t, labels)
            if rule is None or rule["label"] == "excluded":
                dropped["excluded"] += 1
                continue
            desc = t["description"]
            for marker in markers:
                desc = desc.replace(marker, "")
            params = tuple((p["name"] or "", p["text"]) for p in t["params"])
            for marker in markers:
                params = tuple((n, x.replace(marker, "")) for n, x in params)
            if desc.startswith("{") and desc.endswith("}") and not params:
                dropped["placeholder"] += 1
                continue
            text = model_text(desc, params)
            if not text:
                dropped["empty"] += 1
                continue
            norm = " ".join(text.lower().split())
            if norm in seen:
                dropped["duplicate"] += 1
                continue
            seen.add(norm)
            poisoned = rule["label"] == "poisoned"
            slug = _repo_slug(t["repo_url"])
            rows.append(
                Row(
                    text=desc,
                    params=params,
                    label=int(poisoned),
                    family=rule.get("family", "real_benign") if poisoned else "real_benign",
                    group=rule["family"] if poisoned else slug,
                    source="real",
                    key=f"{slug}/{t['path']}:{t['line']}#{t['name']}",
                )
            )
    return rows, dropped


def split_of(group: str, test_share: float = 0.3) -> str:
    """Stable train or test assignment for a repository."""
    bucket = int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "test" if bucket < test_share else "train"
