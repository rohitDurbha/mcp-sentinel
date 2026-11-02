---
name: add-risk-signal
description: Use when adding or changing a rule in src/mcp_sentinel/signals.py, or when a real tool is wrongly flagged or missed by the rule-based signals.
---

# Adding or changing a risk signal

Rules are judged on real tool text, so every change follows the same loop.

1. Write the triggering example into `tests/test_signals.py` first. A new attack pattern goes in as a positive case, and a wrongly flagged real description goes in as a negative or low-severity case. Quote real text where possible and name its source in a comment.
2. Run `pytest tests/test_signals.py` and confirm the new test fails for the right reason.
3. Change or add the rule in `RULES`. Prefer narrowing an existing pattern over adding a new one, and keep phrases that also appear in ordinary documentation at `low` severity.
4. Run the full suite, then rescan the benchmark data with `mcp-sentinel scan --tools data/bench_tools.jsonl --out data/bench_findings.jsonl`.
5. Read every medium and high result in context. Any new false positive means the rule is too broad, so narrow it before moving on.
6. Update the tables and numbers in `docs/signals_review.md` so the published precision stays honest.

Severity guide. Use `high` only for text that has no ordinary reason to exist in a tool description, such as asking the model to hide actions from the user. Use `medium` for text that is unusual but has rare legitimate uses. Use `low` for phrases common in normal documentation that only matter alongside other signals.
