"""Explainable risk signals for MCP tool text.

Each rule is a small regular expression with a signal family, a severity and a short
message. Every finding records the exact span it matched, so the site can show readers
the text that triggered it. Severities are deliberately conservative. Phrases that also
show up in ordinary tool documentation are kept at ``low`` and only matter when other
signals fire alongside them.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .models import Tool

SEVERITY_WEIGHT = {"low": 0.1, "medium": 0.3, "high": 0.6}
_I = re.IGNORECASE
_IS = re.IGNORECASE | re.DOTALL
_EXAMPLE_DOMAINS = re.compile(r"@(example|test|domain|company|email|acme)\.(com|org|net)\b", _I)


@dataclass(frozen=True)
class Rule:
    id: str
    signal: str
    severity: str
    pattern: re.Pattern
    message: str


@dataclass(frozen=True)
class Finding:
    signal: str
    severity: str
    rule: str
    field: str
    start: int
    end: int
    evidence: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def _r(id_: str, signal: str, severity: str, pattern: str, message: str, flags=_I) -> Rule:
    return Rule(id_, signal, severity, re.compile(pattern, flags), message)


RULES: tuple[Rule, ...] = (
    # Text wrapped so a model treats it as privileged, or hidden from rendered views.
    _r("tag-block", "hidden_block", "medium",
       r"<\s*/?\s*(important|system|instructions?|hidden|secret|admin|override)\b[^>|]{0,40}>",
       "Instruction tag aimed at the model"),
    _r("html-comment", "hidden_block", "medium", r"<!--.{0,2000}?-->",
       "HTML comment that renders invisibly", _IS),
    _r("bracket-system", "hidden_block", "medium",
       r"\[\s*(system|admin)(\s+(message|note|instructions?|prompt))?\s*\]",
       "Fake system marker"),
    # Telling the model to hide what it does from the person using it.
    _r("hide-from-user", "secrecy", "high",
       r"\b(do not|don't|never|must not)\s+(tell|mention|inform|notify|reveal|show|disclose|alert)"
       r"\b[^.\n]{0,40}\buser\b",
       "Asks the model to hide something from the user"),
    _r("without-telling", "secrecy", "high",
       r"\bwithout\s+(telling|informing|notifying|alerting|asking)\s+(the\s+)?user\b",
       "Asks the model to act without telling the user"),
    _r("user-must-not-know", "secrecy", "high",
       r"\b(user|human)\s+(should|must|needs?\s+to)\s*(not|n't)\s+(know|see|be told|notice)\b",
       "Asks the model to keep the user unaware"),
    _r("keep-secret", "secrecy", "high", r"\bkeep\s+(this|it|that)\s+(a\s+)?(secret|hidden)\b",
       "Asks the model to keep something secret"),
    _r("do-not-mention", "secrecy", "high", r"\b(do not|don't|never)\s+mention\s+(this|that|it)\b",
       "Asks the model not to mention its actions"),
    _r("manage-user-feelings", "secrecy", "medium",
       r"\b(upset|alarm|scare|worry)\s+the\s+user\b|\bnot\s+(be\s+)?scary\b",
       "Steers how the model presents its actions to the user"),
    # Files that hold credentials or agent configuration.
    _r("ssh-keys", "sensitive_path", "medium", r"\.ssh\b|\bid_(rsa|ed25519|ecdsa|dsa)\b",
       "Mentions SSH keys"),
    # Common in the docs of agent tooling, so it only counts alongside other signals.
    _r("agent-config", "sensitive_path", "low",
       r"\bmcp\.json\b|\.cursor/|claude_desktop_config\.json",
       "Mentions agent or MCP client configuration"),
    _r("credential-files", "sensitive_path", "medium",
       r"\.aws/credentials|\.git-credentials|\.npmrc\b|\.pypirc\b|\.kube/config|"
       r"\.docker/config\.json|\.netrc\b|/etc/shadow\b",
       "Mentions a credential file"),
    _r("etc-passwd", "sensitive_path", "low", r"/etc/passwd\b",
       "Mentions /etc/passwd, a common path traversal example"),
    _r("dotenv", "sensitive_path", "low", r"(?<![\w.])\.env\b", "Mentions a .env file"),
    # Moving data somewhere it should not go.
    _r("pass-content-as", "exfiltration", "high",
       r"\bpass\s+(its|the|their|this|that)\s+(full\s+)?(content|output|value)s?\s+"
       r"(as|in|into|to)\b",
       "Asks the model to smuggle content through a parameter"),
    _r("send-to-destination", "exfiltration", "high",
       r"\b(send|forward|post|upload|email|copy)\s+(all|every|the|any|its|their)\b"
       r"(?!\s+(user|users|customer|customers|person|people|reader)\b)[^.\n]{0,60}"
       r"\bto\s+(\S+@\S+|https?://)",
       "Asks the model to send data to a fixed destination"),
    _r("capture-endpoint", "exfiltration", "high",
       r"\b(webhook\.site|ngrok(-free)?\.(io|app|dev)|requestbin|pipedream\.net|pastebin\.com|"
       r"interact\.sh|burpcollaborator|oast\.(fun|live|site|me|pro))",
       "Mentions a request capture service"),
    _r("email-address", "exfiltration", "low", r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b",
       "Contains an email address"),
    # Overriding earlier instructions.
    _r("ignore-instructions", "override", "high",
       r"\b(ignore|disregard|forget)\s+(all\s+)?(the\s+)?(previous|prior|above|earlier|other)\s+"
       r"(instructions|rules|prompts?|messages?)\b",
       "Tries to override earlier instructions"),
    # Pressure that makes the model comply.
    _r("tool-will-not-work", "coercion", "high",
       r"\botherwise\b[^.\n]{0,30}\b(will\s+not|won't|will\s+fail|does\s+not|doesn't)\s+work\b",
       "Threatens failure unless the model complies"),
    _r("very-very", "coercion", "medium", r"\bvery\s+very\b", "Escalating emphasis"),
    _r("before-using-read", "coercion", "low",
       r"\bbefore\s+(using|calling|invoking|running)\s+(this|any|the)\b[^.\n]{0,30}"
       r"\b(read|call|run|execute|fetch|send|open)\b",
       "Asks for an action before the tool runs"),
    # Reaching into other tools on the same client.
    _r("when-tool-present", "cross_tool", "high",
       r"\bwhen\s+this\s+tool\s+is\s+(available|present|installed|loaded|enabled)\b",
       "Changes behavior based on its own presence"),
    _r("side-effect-on-tool", "cross_tool", "high",
       r"\bside[ -]effects?\s+on\s+(the\s+)?(also\s+)?(present\s+)?[\w-]+\s+tool\b",
       "Claims to change how another tool behaves"),
    _r("other-tool-must", "cross_tool", "medium",
       r"\b[\w-]+\s+tool\s+(must|should)\s+(always\s+)?(send|use|call|include|forward|add)\b",
       "Dictates how another tool must behave"),
    _r("mcp-tool-prefix", "cross_tool", "medium", r"\bmcp_tool_[a-z0-9_]+",
       "Names another tool by its client-side identifier", 0),
    _r("instead-of-tool", "cross_tool", "low",
       r"\binstead\s+of\s+(using\s+|calling\s+)?(the\s+)?[\w-]+\s+tool\b",
       "Steers the model away from another tool"),
)  # fmt: skip

_TAG_CHARS = (0xE0000, 0xE007F)
_BIDI = set(range(0x202A, 0x202F)) | set(range(0x2066, 0x206A))
_ZERO_WIDTH = {
    0x200B,
    0x200C,
    0x200D,
    0x200E,
    0x200F,
    0x2060,
    0x2061,
    0x2062,
    0x2063,
    0x2064,
    0xFEFF,
}
LONG_DESCRIPTION = 4000


def _invisible(text: str, field: str) -> list[Finding]:
    """Group runs of invisible or direction-changing characters into single findings."""
    out: list[Finding] = []
    i = 0
    while i < len(text):
        cp = ord(text[i])
        is_tag = _TAG_CHARS[0] <= cp <= _TAG_CHARS[1]
        if not (is_tag or cp in _BIDI or cp in _ZERO_WIDTH):
            i += 1
            continue
        j = i
        severity = "medium"
        while j < len(text):
            c = ord(text[j])
            tag = _TAG_CHARS[0] <= c <= _TAG_CHARS[1]
            if not (tag or c in _BIDI or c in _ZERO_WIDTH):
                break
            if tag or c in _BIDI:
                severity = "high"
            j += 1
        run = text[i:j]
        codes = " ".join(f"U+{ord(c):04X}" for c in run[:12]) + (" ..." if len(run) > 12 else "")
        hidden = "".join(chr(ord(c) - 0xE0000) for c in run if 0xE0020 <= ord(c) <= 0xE007E)
        message = "Invisible or direction-changing characters"
        if hidden:
            message += f" that decode to {hidden[:80]!r}"
        out.append(
            Finding("invisible_unicode", severity, "invisible-chars", field, i, j, codes, message)
        )
        i = j
    return out


# Context checks found by reviewing real registry flags (datasets/registry_review_a.json). Each
# one removes a pattern of harmless text, and tests/test_signals.py pins attacks that must stay.
_BOUNDARY = re.compile(r"[.!?;](?=\s|$)|\n")
_REFUSAL = re.compile(
    r"\b(never|not|no|refuses?|refused|rejects?|rejected|skips?|skipped|excludes?|excluding|"
    r"except|without|blocks?|blocked|denies|denied)\b",
    _I,
)
_ACTION = re.compile(
    r"\b(read|reads|send|sends|cat|open|opens|load|loads|include|includes|upload|uploads|copy|"
    r"copies|fetch|access|accesses|get|forward|exfiltrate)\b",
    _I,
)
_NEGATION = re.compile(r"\b(never|not|no)\b|n't\b", _I)
_CONDITION = re.compile(r"\b(until|unless|before|without)\b", _I)
_DOC_SECTIONS = re.compile(r"<\s*/?\s*(usecase|examples?)\b", _I)


def _sentence(text: str, start: int, end: int) -> tuple[str, str]:
    """The text from the sentence start to ``start``, and from ``end`` to the sentence end."""
    before = [m.end() for m in _BOUNDARY.finditer(text, 0, start)]
    after = _BOUNDARY.search(text, end)
    stop = after.start() if after else len(text)
    return text[before[-1] if before else 0 : start], text[end:stop]


def _harmless(rule: Rule, text: str, m: re.Match) -> bool:
    head, tail = _sentence(text, m.start(), m.end())
    if rule.id == "hide-from-user":
        # "do not tell the user to reconnect", "never tell the user it is live until it is"
        return bool(re.match(r"\s+to\b", tail) or _CONDITION.search(m.group(0) + tail))
    if rule.id == "without-telling":
        return bool(_NEGATION.search(head))  # "never publish without asking the user"
    if rule.id == "tag-block":
        name = m.group(1).lower()
        if name in ("instructions", "instruction", "important") and _DOC_SECTIONS.search(text):
            return True  # <usecase> <instructions> <examples> used as documentation sections
        return name == "secret" and not re.search(r"<\s*/\s*secret\s*>", text, _I)
    if rule.id == "html-comment":
        return len(m.group(0)[4:-3].split()) <= 4  # short markers such as <!-- Page N -->
    if rule.signal == "sensitive_path":
        cue = list(_REFUSAL.finditer(head))
        return bool(cue) and not _ACTION.search(head[cue[-1].end() :])
    return False


def scan_text(text: str, field: str) -> list[Finding]:
    """Run every rule over one piece of text. Findings are sorted by position."""
    findings: list[Finding] = []
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            if rule.id == "email-address" and _EXAMPLE_DOMAINS.search(m.group(0)):
                continue
            if _harmless(rule, text, m):
                continue
            findings.append(
                Finding(
                    rule.signal,
                    rule.severity,
                    rule.id,
                    field,
                    m.start(),
                    m.end(),
                    m.group(0),
                    rule.message,
                )
            )
    findings.extend(_invisible(text, field))
    if field == "description" and len(text) > LONG_DESCRIPTION:
        findings.append(
            Finding("long_text", "low", "long-description", field, 0, 0, f"{len(text)} characters",
                    "Description is unusually long")
        )  # fmt: skip
    findings.sort(key=lambda f: (f.start, f.end, f.rule))
    return findings


def scan_tool(tool: Tool) -> list[Finding]:
    findings = scan_text(tool.description, "description")
    for param in tool.params:
        findings.extend(scan_text(param.text, f"param:{param.name or ''}"))
    return findings


def score(findings: list[Finding]) -> float:
    """Noisy-OR over the strongest finding in each signal family, rounded for stable output."""
    strongest: dict[str, float] = {}
    for f in findings:
        strongest[f.signal] = max(strongest.get(f.signal, 0.0), SEVERITY_WEIGHT[f.severity])
    remaining = 1.0
    for weight in strongest.values():
        remaining *= 1.0 - weight
    return round(1.0 - remaining, 4)


def level(value: float) -> str:
    if value >= 0.6:
        return "high"
    if value >= 0.3:
        return "medium"
    return "low" if value > 0 else "none"
