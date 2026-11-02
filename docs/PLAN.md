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

## Phase 3. Labeled data and classifier

Combine public proof-of-concept datasets as positives with crawled tools as negatives, then add synthetic minority examples. Train a calibrated classifier on text embeddings plus the Phase 2 signals, using splits grouped by server so that no repository leaks across train and test.

Exit criteria
- PR-AUC and recall at a fixed precision are reported with confidence intervals against the rule-only baseline.
- A model card records data sources, label noise, and known failure cases.

## Phase 4. Daily pipeline

A scheduled GitHub Actions workflow discovers new and updated servers, rescans only repositories whose commit changed, scores every tool, and publishes versioned snapshots plus a history file for trends.

Exit criteria
- Two consecutive scheduled runs succeed, and the second run reuses cached results for unchanged repositories.

## Phase 5. Public site

A static site on GitHub Pages offers search, a page per server with flagged evidence, trend charts and a methodology page with a dispute link.

Exit criteria
- The site loads from published data, works at phone width, and every flag links to its evidence.

## Phase 6. Evaluation and write-up

Error analysis, a findings write-up, and resume bullets backed by real numbers from the pipeline.
