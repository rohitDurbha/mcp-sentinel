# Build plan

Each phase ends with exit criteria that must pass on real data before the next phase begins. The question the whole project answers is simple to state. Which public MCP tools carry text that could steer an AI assistant against the person using it, and how is that changing over time?

## Phase 0. Scaffold

Set up the package, project rules, tests, lint and CI so that every later phase lands in a working skeleton.

Exit criteria
- `pytest` and `ruff` pass locally and in GitHub Actions on an empty skeleton.

## Phase 1. Discovery and extraction

Pull every server from the official MCP registry, clone each linked repository safely, and extract tool names, descriptions and parameter descriptions from source code without running it.

Patterns covered at launch

| Language | Pattern |
|---|---|
| TypeScript and JavaScript | `server.tool(...)`, `server.registerTool(...)`, tool object literals with `name` and `description` |
| TypeScript and JavaScript | tool maps keyed by name, `paramsSchema` objects, classes ending in `Tool` with `toolName` and `description` fields |
| Python | FastMCP `@mcp.tool` with docstrings, `mcp.tool()(fn)`, `mcp.tool(fn, ...)`, `mcp.add_tool(fn, ...)`, `Tool(name=..., description=...)` |
| Go | `mcp.NewTool(...)` with `mcp.WithDescription(...)`, `&mcp.Tool{Name: ..., Description: ...}` with schema parameter descriptions |
| Go | `MustTool(name, description, ...)` helpers and `t("KEY", "default")` translation helpers |

Exit criteria
- Unit tests cover every pattern in the table above, including descriptions built from concatenation and constants.
- A real run over at least 30 known repositories reports how many repos yielded tools, so coverage is measured and visible.

## Phase 2. Rule-based risk signals

Build explainable detectors that return the exact evidence span for each finding. The first signals are hidden directives aimed at the model, secrecy phrases, sensitive file paths, exfiltration patterns, invisible Unicode, instructions that reference other tools, and descriptions that are unusually long for what the tool does.

Exit criteria
- Every signal has positive and negative unit tests, with positives drawn from published attack examples.
- A precision check on a hand-reviewed sample of real flagged tools is recorded in `docs/`.

Status. Done, see `docs/signals_review.md`.

## Phase 3. Labeled data and classifier

Real attacks from public security projects form the test set, and synthetic attacks inserted into real benign descriptions form the training positives. A logistic regression over TF-IDF text features and the Phase 2 signals is trained with splits grouped by repository, and its threshold targets a one percent false positive rate on real benign tools. Scores are treated as rankings, because synthetic training data makes calibrated probabilities misleading.

Exit criteria
- PR-AUC and recall at the deployed threshold are reported with bootstrap intervals against the rule-only baseline, on real attacks never used in training.
- Generalization is measured by holding out each attack family in turn.
- A model card records data sources, label decisions, the policy choice and known failure cases.

Status. Done, see `docs/model_card.md`.

## Phase 4. Daily pipeline

A scheduled GitHub Actions workflow discovers new and updated servers, rescans only repositories whose commit changed, scores every tool, and publishes versioned snapshots plus a history file for trends.

Exit criteria
- Two consecutive scheduled runs succeed, and the second run reuses cached results for unchanged repositories.

Status. Built and verified locally on the forty benchmark repositories. The first run cloned all forty in 46 seconds, and the second cloned none, reused every result and produced byte-identical files in 9 seconds. The criterion is fully met once two runs have succeeded in GitHub Actions against the live registry.

The first live run against the full registry kept extracting for five hours and was cancelled at the job limit, so it published nothing. Parsing had been running on threads, which share a single core in Python, so parsing now runs in a process pool and was byte-identical to the threaded output on the benchmark repositories. Each run also has a time budget of 220 minutes, after which no new repository starts and the rest are published as pending for the next run. A budget test on the benchmark left 28 of 40 repositories pending, and the following run finished them with output identical to a single full run.

## Phase 5. Public site

A static site on GitHub Pages offers search, a page per server with flagged evidence, trend charts and a methodology page with a dispute link.

Exit criteria
- The site loads from published data, works at phone width, and every flag links to its evidence.

## Phase 6. Evaluation and write-up

Error analysis, a findings write-up, and resume bullets backed by real numbers from the pipeline.
