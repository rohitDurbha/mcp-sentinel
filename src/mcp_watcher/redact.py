"""Remove credential-looking strings before anything is published.

Tool descriptions occasionally contain real keys copied from a developer's setup. The
pipeline publishes descriptions and evidence text, so known token formats and long
secret values in obvious assignments are replaced with a short typed marker. Attack
text such as file paths and email addresses is left alone, because readers need to see
it to judge a flag.
"""

from __future__ import annotations

import re

_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),  # noqa: E501
    ("aws-key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})\b")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{30,}")),
    ("openai-key", re.compile(r"\bsk-(proj-|svcacct-)?[A-Za-z0-9_-]{32,}")),
    ("stripe-key", re.compile(r"\b[rs]k_live_[A-Za-z0-9]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{20,}\b")),
    ("google-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{20,}")),
)  # fmt: skip

# key = "value" where the key names a secret and the value looks random enough to be one.
_ASSIGNMENT = re.compile(
    r"""(?P<key>\b[\w-]*(api[_-]?key|secret|token|passw(or)?d|credential)[\w-]*\b\s*[:=]\s*["']?)"""
    r"""(?P<value>[A-Za-z0-9_\-/+]{16,})""",
    re.IGNORECASE,
)


def _looks_random(value: str) -> bool:
    kinds = sum(bool(re.search(p, value)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]"))
    return kinds >= 2 and not value.isalpha()


def redact(text: str) -> str:
    if not text:
        return text
    for name, pattern in _PATTERNS:
        text = pattern.sub(f"[REDACTED:{name}]", text)

    def _assign(m: re.Match) -> str:
        if not _looks_random(m.group("value")):
            return m.group(0)
        return m.group("key") + "[REDACTED:secret]"

    return _ASSIGNMENT.sub(_assign, text)
