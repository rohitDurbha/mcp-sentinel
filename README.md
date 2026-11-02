# mcp-sentinel

mcp-sentinel watches the public MCP ecosystem and flags tools whose descriptions could steer an AI assistant against the person using it. Every MCP tool ships with a description that the model reads and the user usually never sees, which makes that text a quiet place to hide instructions. This project reads those descriptions straight from source code, scores them, and publishes the results on a site that refreshes every day.

## How it works

The pipeline pulls every server from the official MCP registry and makes a shallow clone of each linked repository. Each clone is parsed with Python's `ast` module or tree-sitter, so nothing from an untrusted repository is ever installed or executed. The extractor finds tool definitions written for the TypeScript, Python and Go SDKs and follows constants across files to rebuild the full description text. Later phases score each tool with explainable rules and a trained classifier, and every flag points back to the exact text that triggered it.

## Quick start

```bash
uv venv && uv pip install -e ".[dev]"
mcp-sentinel discover --out data/servers.jsonl
mcp-sentinel extract --servers data/servers.jsonl --out data/tools.jsonl
mcp-sentinel extract --repo https://github.com/modelcontextprotocol/servers --out data/one.jsonl
mcp-sentinel scan --tools data/tools.jsonl --out data/findings.jsonl
pytest
```

## Status

The project is being built in phases, and `docs/PLAN.md` lists each phase with the checks it must pass before the next one starts. Discovery, extraction and the rule-based risk signals are working today, and the classifier and the public site come next.

## A note on scores

Scores from this project are automated risk signals and should never be read as a verdict on any author. Every flagged tool will show the text that caused the flag, and authors will have a clear way to dispute a result they believe is wrong.

## License

The code is released under the MIT license, so you are free to use it, change it and share it.
