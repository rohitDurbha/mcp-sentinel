# Rule-based signals review

This page records how the Phase 2 rules behaved on real tool descriptions before any of them reach the public site. The run covers the 1,916 tools extracted at the time of review from the forty benchmark repositories, and every medium or high finding was read by hand in its full context.

## Signal families

| Signal | What it looks for | Strongest severity |
|---|---|---|
| `hidden_block` | `<IMPORTANT>` style tags, HTML comments and fake `[SYSTEM]` markers | medium |
| `secrecy` | Requests to hide actions from the user or to keep something secret | high |
| `sensitive_path` | SSH keys, MCP client configs and credential files | medium |
| `exfiltration` | Smuggling content through parameters or sending it to fixed destinations | high |
| `override` | Attempts to cancel earlier instructions | high |
| `coercion` | Threats that the tool fails unless the model complies | high |
| `cross_tool` | Text that changes how other tools on the same client behave | high |
| `invisible_unicode` | Zero-width, bidirectional and Unicode tag characters, with decoded payloads | high |
| `long_text` | Descriptions longer than 4,000 characters, kept as context only | low |

A tool's score combines the strongest finding from each family, so repeating one phrase many times does not inflate it. Scores of 0.6 and above count as high, and scores from 0.3 count as medium.

## Results on real tools

| Level | Tools |
|---|---|
| High | 2 |
| Medium | 0 |
| Low | 31 |
| None | 1,883 |

Both high results are the published tool poisoning demonstrations from Invariant Labs, and each one scores 0.97 with every expected signal family firing. The first review pass also produced one medium result on an AWS DynamoDB tool. That description mentions `/etc/passwd` only to say that path traversal attempts are blocked, so the rule for that path moved to low severity and a regression test now covers the case. After that change, every tool at medium or above was a true positive.

The thirty-one low results are almost all long descriptions, plus a few prerequisite notes such as "Before calling this tool, you MUST first call" another tool. Low findings never raise a tool above low on their own, and they exist to support the classifier in Phase 3.

## Limits worth stating plainly

This benchmark contains only a handful of real attacks, so these numbers show that the rules stay quiet on ordinary tools. They cannot yet measure recall on attacks that nobody has published. Phase 3 adds labeled attack data and paraphrased variants to measure recall properly, and the full registry crawl in Phase 4 will give a far larger sample for precision.

Rules also cannot see a description that changes while the server runs, which is how the WhatsApp takeover demonstration works. Detecting that needs a code-level check for descriptions rewritten after startup, which is planned for a later phase.

## Phase 6 changes from live registry flags

The benchmark above holds only forty repositories, so Phase 6 reviewed 100 flags from the full registry run in `datasets/registry_review_a.json`. Most rule false alarms followed a handful of patterns, and each rule below was narrowed with a regression test that quotes the real text, next to tests that pin the attacks the rule must still catch.

| Rule | What changed | Real example that no longer fires |
|---|---|---|
| `send-to-destination` | Ignores sentences that send the person somewhere | "send the user to https://tempos.min-saude.pt" |
| `hide-from-user` | Ignores conditional guidance and requests to tell the user to act | "NEVER tell the user the domain is bought or live until check_domain confirms it" |
| `without-telling` | Ignores negated sentences | "never publish without asking the user" |
| `tag-block` | Ignores documentation sections beside `<usecase>`, enum syntax with a bar, and a bare `<secret>` placeholder | "`<usecase>` ... `<instructions>` Searches names `</instructions>`" |
| `html-comment` | Ignores comments of four words or fewer | "`<!-- ds:block:N -->`" |
| `mcp-tool-prefix` | Matches only lower case client identifiers | "{MCP_TOOL_COPY.search_classes.description}" |
| `agent-config` | Moved to low severity, since agent tooling names these files routinely | "Writes the team rules into .cursor/rules and registers the server in mcp.json" |
| Sensitive paths | Ignore a path that directly follows a refusal with no action verb between | "Refuses hidden files and folders (dotfiles such as .env or .ssh)" |

On the 100 reviewed flags these changes kept every concern and every demo at the same rule level, and they moved 45 false alarms from medium or high down to low or none. The forty benchmark repositories and the attack repositories produced identical rule levels before and after the change.

