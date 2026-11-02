# mcp-sentinel project rules

mcp-sentinel crawls public MCP servers, extracts every tool definition from their source code, and scores each tool for poisoning and other risk signals. A scheduled GitHub Actions job refreshes the data every day, and a static site on GitHub Pages lets anyone search the results.

The phased roadmap lives in `docs/PLAN.md`, and every change should map to the phase that is currently in progress.

## Commands

```bash
uv venv && uv pip install -e ".[dev,ml]"  # install with dev and ML tools
pytest -q                                 # run the full test suite (no network)
ruff check . && ruff format --check .     # lint and format check
mcp-sentinel discover --out data/servers.jsonl      # pull server list from the official registry
mcp-sentinel extract --servers data/servers.jsonl --out data/tools.jsonl
mcp-sentinel extract --repo https://github.com/OWNER/REPO --out data/tools.jsonl
mcp-sentinel scan --tools data/tools.jsonl --out data/findings.jsonl --model models/sentinel-lr-1.pkl
python research/train_eval.py --tools data/bench_tools.jsonl data/attack_tools.jsonl   # retrain and re-evaluate
mcp-sentinel pipeline --previous previous --out out --model models/sentinel-lr-1.pkl  # the daily run
```

## Layout

```
src/mcp_sentinel/
  models.py        dataclasses shared by every stage
  registry.py      official MCP registry client
  fetch.py         shallow, hook-free git clones with size limits
  extract/         static extractors for Python, TypeScript and JavaScript, Go
  signals.py       explainable risk rules, evidence spans and scoring
  synth.py         synthetic poisoned and benign variants for training
  dataset.py       hand labels applied to extracted tools
  model.py         TF-IDF plus rule-feature classifier and explanations
  scoring.py       rules plus model into one record per tool
  redact.py        removes credential-looking strings before publication
  pipeline.py      daily run with commit-based caching and snapshot output
  cli.py           argparse entry point
tests/             pytest suite, fixtures live in tests/fixtures
research/          training and evaluation script for the classifier
datasets/          hand labels and the list of attack repositories
models/            trained classifier used by the scan command
docs/PLAN.md       phases, scope and exit criteria
```

## Safety rules

- Cloned repositories are untrusted input, so the pipeline must never execute, import, build or install anything from them.
- Parsing happens only through `ast` and tree-sitter, and every git call disables hooks, prompts and LFS downloads.
- Any credential-looking string found in a repo must be redacted before it reaches `data/` or the public site.
- Tests never touch the network, so registry responses and source snippets come from files in `tests/fixtures`.

## Engineering rules

- Each new extractor pattern or risk signal starts with a fixture and a failing test before the implementation is written.
- Every risk flag must carry the exact evidence text and its location, because an unexplained score is not useful to anyone.
- Output files are deterministic for a given input, with records sorted by stable keys so that daily diffs stay meaningful.
- Any change that could alter extraction output must bump `EXTRACTOR_VERSION` in `pipeline.py`, so cached repositories are rescanned.
- The daily workflow keeps its snapshot on the `data` branch as one force-pushed commit, so main never fills with data.
- New dependencies need a one-line justification in the pull request, and the default answer is to use the standard library.
- Code stays in small plain modules with type hints and dataclasses, and abstractions appear only after a second real use.
- A phase counts as done only after its exit criteria in `docs/PLAN.md` pass on real repositories with the output shown.

## Authorship rules

- Every commit, pull request and contributor entry belongs to Rohit Durbha, using the identity in this repo's git config.
- Never add Co-Authored-By trailers, session links, "Generated with" footers or any other AI attribution to commits or pull requests.

## Evaluation rules

- Real attacks are test data only, so they must never be used for training, threshold choice or template writing.
- Any change to the model, templates or labels is followed by a full run of `research/train_eval.py` and an update to `docs/model_card.md`.
- A choice made after looking at test results is stated as such in the model card.

## Publication rules

- The site presents scores as automated risk signals and never calls a server or its author malicious.
- Every flagged tool shows the triggering text, the rule or model that fired, and a link for authors to dispute the result.
- Disputed results stay visible with a note until a human reviews them and either confirms or clears the flag.

## Writing rules for docs and site copy

Prose in the README, docs and site follows the owner's style, which means warm and specific sentences with simple punctuation. Avoid colons, semicolons, em dashes and contractions in prose, and keep every sentence at eight words or longer. Never use the "X rather than Y" formula, and avoid stock AI phrasing such as "delve", "crucial" or "landscape". Headings, code blocks, tables and identifiers are exempt from these punctuation rules.
