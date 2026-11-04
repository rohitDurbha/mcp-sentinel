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

The second live run checked 29,534 repositories in eight minutes and extracted all 25,515 that needed it in 74 minutes. It then lost the runner while scoring, because the classifier built character features for every tool in one matrix, and that matrix grew by about a gigabyte for every forty thousand tools. Scoring now runs in chunks of two thousand tools, and a test with 191,800 tools peaked at 0.35 GB of memory.

The third live run scored all 2,669,055 tools and then stopped while writing, because some descriptions held half of an escaped emoji that UTF-8 cannot encode. Extraction now joins those pairs and replaces any lone half, which bumped the extractor to version 2. That run also showed that the full tools file would be about 500 MB compressed, far above the 100 MB GitHub allows for one file. The run output is now kept as a workflow artifact for three days, so the size problem can be studied with real data before the snapshot format changes.

The fourth live run stopped after an hour of extraction, because a parameter with no name reached the new text cleanup as an empty value. The cleanup now accepts missing names, and any error inside one repository now marks that repository as `extract_failed` while the rest of the run carries on. The full output with every tool now lives in the Actions cache, since only the next run needs it. The data branch receives only the public files, which are the servers, the run state, the summary, the history and a new `flagged.jsonl.gz` that holds each flagged tool with its text. A previous snapshot without a tools file is never reused, so losing the cache simply means one full rescan.

The fifth live run succeeded in 1 hour and 55 minutes and published the data branch for the first time. The registry listed 55,624 server entries, and 36,901 of them pointed at a repository. The run checked 29,593 repositories, cloned 25,571 and found tools for 23,832 entries. Those entries held 2,668,605 tools, but only 312,081 were distinct, because many entries share one repository. It flagged 723 distinct tools in 456 repositories, with 182 at high and 541 at medium. The largest public file was the 12.7 MB state file, and the flagged file was only 470 KB.

The sixth live run started from the cache of the fifth and finished in 53 minutes. It reused 30,645 jobs, cloned only the 367 repositories whose commit had changed and reported no new or cleared flags. The fifth run was started by a push and the sixth by hand, which tests the same code path as the schedule. Phase 4 is done. Storing each repository folder once, instead of once per registry entry, would shrink the cache and the scoring time about eightfold, and it remains a sensible later improvement.

## Phase 5. Public site

A static site on GitHub Pages offers search, a page per server with flagged evidence, trend charts and a methodology page with a dispute link.

Exit criteria
- The site loads from published data, works at phone width, and every flag links to its evidence.

Status. Built and checked locally on the published data from the sixth run. The site is plain HTML, CSS and JavaScript with no build step, and `mcp-sentinel site` turns the data branch into four small JSON files. The home page needs about 480 KB of compressed data, and the 3.1 MB server index loads only for search and server pages. All 723 flags were opened in a headless browser, and each one showed its source link and the marked evidence. The pages had no horizontal scroll at 390 pixels wide. A `pages` workflow rebuilds the site after every successful daily run, and each flag page links to a GitHub issue form for disputes. Reviewed disputes live in `datasets/disputes.json`, where an open dispute adds a note and a cleared flag stops counting toward totals. The phase is done once the live GitHub Pages address serves the same result.

A one-screen list and detail layout was tried next and then withdrawn at the owner's request, so the multi-page design returned. The `llms.txt` file for AI agents stayed, because it describes the JSON data that every version of the site reads. The multi-page design then took a few small patterns ported by hand from Magic UI, 21st.dev, uiverse and Mobbin, without any new dependency. Evidence now sits under a hand-drawn marker, the list rows carry a level pill and a chevron, the filters became a search field and a segmented control, and the main actions use a sliding hover button. All 723 flag pages were checked again in a headless browser after the change. The home page then gained an Inside the scan section. It shows what happened to every registry entry, followed by six linked charts covering signal family, rule, detection method, evidence location, classifier score and repository. A click on any bar filters the other charts and the list of matching tools below them. The single example at the top of the home page became a reel of six real tools that replays the scan for each one. A scan line passes over the text, the rule matches are marked in order, and the classifier meter fills to its score before the result appears. Two of the six were caught by the classifier alone, which shows the model working where no rule matched. The reel pauses on hover, on focus and off screen, and it stays still for anyone who prefers reduced motion.

## Phase 6. Evaluation and write-up

Error analysis, a findings write-up, and resume bullets backed by real numbers from the pipeline.
