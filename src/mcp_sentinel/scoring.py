"""Score extracted tools with the rules and, when given, the classifier."""

from __future__ import annotations

from typing import Any

from .models import ParamText, Tool
from .signals import level, scan_tool, score


def tool_from_row(row: dict) -> Tool:
    params = [ParamText(p["name"], p["text"]) for p in row.get("params") or []]
    return Tool(**{**row, "params": params})


def final_level(rule_level: str, model_flag: bool) -> str:
    """Rules decide the level, and a model flag lifts anything below medium to medium."""
    if model_flag and rule_level in ("none", "low"):
        return "medium"
    return rule_level


SCORE_CHUNK = 2_000  # character n-gram features for the whole registry do not fit in memory


def score_tools(tools: list[Tool], model: Any = None) -> list[dict]:
    """One record per tool with rule findings, model output and the final level."""
    results = []
    for begin in range(0, len(tools), SCORE_CHUNK):
        results.extend(_score_chunk(tools[begin : begin + SCORE_CHUNK], model))
    return results


def _score_chunk(tools: list[Tool], model: Any) -> list[dict]:
    texts: list[str] = []
    model_scores = None
    if model is not None:
        from .model import tool_text

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
            record["model"] = {"version": model.version, "score": m, "flag": bool(flag)}
            if flag:
                record["model"]["top_terms"] = model.top_terms(texts[i])
        record["level"] = final_level(record["rule_level"], flag)
        results.append(record)
    return results
