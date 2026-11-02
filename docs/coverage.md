# Extraction coverage

These numbers come from running the extractor over the forty repositories listed in `benchmark_repos.txt`. The list mixes official servers, large vendor monorepos and a few known attack demonstrations, so it stresses every supported pattern.

| Metric | Value |
|---|---|
| Repositories cloned | 40 of 40 |
| Repositories with no Python, TypeScript or Go source | 1 (Rust) |
| Repositories with supported source that yielded tools | 37 of 39 (95%) |
| Tools extracted | 1,916 |
| Descriptions fully resolved from source | 91% |
| Parameter descriptions extracted | 2,853 across 768 tools |
| Wall time for the full run | about 35 seconds |

## Known gaps

Two repositories with supported source returned no tools, and both cases are expected. The Playwright server keeps its tool definitions in the main Playwright repository, and the Microsoft server collection is written in C# with only build tooling in TypeScript. The Notion server builds its tools from an OpenAPI file at runtime, so static extraction finds only one helper tool there.

Static extraction also cannot see a description that is swapped while the server runs. The WhatsApp takeover demonstration from Invariant Labs uses exactly that trick, so the extractor records only the harmless version. A later phase will look for code paths that rewrite descriptions after startup and flag them as a separate signal.

Rust, C# and Java servers are not covered yet, and their share of the registry will decide whether they are worth adding.
