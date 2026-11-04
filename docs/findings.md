# Findings from the public MCP registry

This page records what MCP Watcher learned in its first days of scanning the official MCP registry, measured between November 2 and November 4, 2026. The numbers come from the daily pipeline and from two samples of flags that were read by hand. Every review label and reason is published in `datasets/registry_review_a.json` and `datasets/registry_review_b.json`.

## Coverage

| Measure | Value |
|---|---|
| Registry entries | 55,974 |
| Entries that list a source repository | 37,063 |
| Distinct repositories checked | 29,751 |
| Entries scanned with tools found | 23,817 |
| Entries with no Python, TypeScript, JavaScript or Go source | 8,214 |
| Entries whose repository could not be reached | 4,882 |
| Tool records across all entries | 2,664,079 |
| Distinct tools | 312,318 |
| Tools whose full description was recovered statically | 99.3% |

About a third of registry entries list no repository at all, so no source scanner can see them. Entries also repeat heavily, because many of them point at the same repository. The 2.66 million tool records collapse to about 312,000 distinct tools, and two curated list repositories alone account for close to 400 registry entries.

## What the scan flags

The run on November 4 counted 360 flagged tools across 261 repositories, with 136 at high and 224 at medium. Another 130 tools sit in the classifier only tier, which is listed for review but never counted. Most counted flags mention sensitive paths such as SSH keys or credential files, followed by requests to keep something from the user and by text that points at data capture services. Flags are spread thin, and no single repository holds more than six of them.

## How often a flag deserves a look

| Sample | When | Flags read | Worth a look | Share |
|---|---|---|---|---|
| A, used to find and fix false alarms | before the Phase 6 changes | 100 | 11 | about 11% after weighting |
| B, never used for tuning | after the Phase 6 changes | 50 counted | 4 | 8%, with a 95% interval of 3% to 19% |
| B, classifier only tier | after the Phase 6 changes | 20 | 0 | 0%, with a 95% interval of 0% to 16% |

The honest headline is that fewer than one flag in five deserves a human look on live data, even after the fixes. The Phase 6 changes halved the number of counted flags from 724 to 360 and kept every concern and demo that sample A had found, which cuts review work in half. They did not measurably raise precision, because the two samples are small and their intervals overlap. The classifier only tier earned its separate place, since none of the twenty sampled tools in it deserved attention.

The same detector catches 14 of 16 real published attacks while raising one benign tool in 529 from curated repositories. The gap between that benchmark and the live registry is the most useful lesson of this phase. Curated benign tools are short and plain, while real registry tools are long, imperative and often about security or secrets themselves.

## What the real concerns look like

None of the six concerns found across both samples was a classic exfiltration attack. Each one was a consent pattern, where a tool description asks the assistant to act without telling the person or without asking first.

| Pattern | What the description asks for |
|---|---|
| Silent memory | Save personal facts the user mentions and never say that it saved them |
| Mandatory lead capture | Send the operator's email to the vendor's sales pipeline as a required step |
| Silent reporting | Report which content was shown to the user, quietly and without mentioning it |
| Automatic diagnostics | Send self diagnostics and feedback to the vendor without asking the user |
| Unasked code changes | Apply every generated file and change without asking the user |
| First message capture | Call the tool before every first reply and pass along the user's exact first message |

These patterns may all have reasonable product motives, and this page names no server on purpose. They still matter, because an assistant that follows them stops being transparent with the person it serves. Each one is flagged on the site with its exact evidence and a link for the author to respond.

## Demos and fixtures

Ten of the reviewed flags were security demos, test fixtures or deliberate examples, such as an evil test server in a scanner's own repository or a rug pull corpus. These are correct detections, and the site leaves them flagged so a reader can see the attack text that real defenders study. Only 16 of the 360 counted flags live in paths that name tests, fixtures, examples or demos, so most flagged text sits in code that real servers ship.

## Where the false alarms come from

| Pattern | Share of false alarms in sample B |
|---|---|
| Tools whose job involves secrets, SSH or agent setup | 35% |
| Security tools that name the attacks they block | 17% |
| Accuracy guidance such as "never tell the user it is live until confirmed" | 11% |
| Coincidental phrases, negations and sample values | 26% |
| Workflow hints, documentation structure and injection warnings | 11% |

A rule that sees the words `.ssh` or "do not tell the user" cannot tell a secret manager from an attack. The next useful step is purpose awareness, where a tool that exists to manage keys or scan for threats is judged differently from a weather tool that suddenly mentions SSH keys.

## What went wrong along the way

One operational mistake from this phase is worth recording in full. A slow day of commit checks led to adding the workflow token to each check, but the checkout step already supplies one, so every check sent two authorization headers and GitHub rejected them. That run published almost every entry as stale. The extra header is gone, and a run now refuses to publish when more than half of its commit checks fail.

## What comes next

The labels in both samples were drafted from the tool text and evidence by an assistant, so the project owner confirming a subset is the first step. After that, purpose aware rules, a third untouched sample to measure them, and a code level check for descriptions that change after a server starts would each make the flags more useful.
