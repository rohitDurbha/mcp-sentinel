---
name: add-extractor-pattern
description: Use when adding support for a new way MCP servers declare tools (a new SDK call, decorator or language) to the static extractors in src/mcp_sentinel/extract.
---

# Adding an extractor pattern

Extractors read source code with `ast` or tree-sitter and never execute it. Follow these steps in order so that coverage only ever goes up.

1. Find two real repositories that use the pattern, and copy the smallest snippet that shows it into `tests/fixtures/<language>/<pattern>.<ext>`. Include one variant where the description is built from a constant or concatenation.
2. Write a failing test in `tests/test_extract_<language>.py` that asserts the tool name, the description text, the parameter descriptions and the line number.
3. Implement the pattern inside the matching module in `src/mcp_sentinel/extract/`. Reuse the string resolution helpers there instead of writing a new one.
4. Run `pytest -q` and `ruff check .` until both pass.
5. Run `mcp-sentinel extract --repo <url>` on both real repositories and confirm the tools match what the source declares.
6. Add the pattern to the table in `docs/PLAN.md` so the documented coverage matches the code.

Never mark a description as resolved when it was only partly resolved. Keep the `description_resolved` flag honest, because Phase 2 signals treat unresolved text differently.
