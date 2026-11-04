# Model card for watcher-lr-1

This model was named sentinel-lr-1 until the project was renamed to MCP Watcher in November 2026. The file was saved again under the new name with the same fitted weights, and its scores on 725 test texts matched the old file exactly. The raw results in `docs/results/phase3.json` keep the old name because they record the original run.

watcher-lr-1 scores the text of an MCP tool for signs of tool poisoning. Tool poisoning means a description or parameter description that tries to turn the model against the person using it, for example by asking it to read private files, send data away, change how other tools behave, or hide what it is doing. All numbers below come from `research/train_eval.py` with seed 20261102, and the raw results live in `docs/results/phase3.json`.

## What the model is

The model is a logistic regression over TF-IDF word and character n-grams, plus the nine rule signal families from Phase 2. It is small enough to run on a laptop CPU in milliseconds, and every score can be explained through the words that raised it and the rule findings with their evidence spans. Scores are rankings and should not be read as probabilities. The decision threshold is set so that about one percent of real benign training tools would be flagged in cross-validation.

The deployed policy flags a tool when the rules reach medium severity or the model crosses its threshold. This policy was chosen after the first evaluation run showed that the two approaches miss different attacks, and that order of events is stated here so nobody mistakes it for a choice made in advance.

## Training data

| Part | Rows | Where it comes from |
|---|---|---|
| Real benign tools | 1,478 | Benchmark repositories assigned to the training split by a stable hash of the repository name |
| Synthetic poisoned tools | 696 | Attack text inserted into real benign descriptions across eight families |
| Synthetic benign variants | 696 | Ordinary documentation notes inserted with the same placements and wrappers |

The synthetic attack templates follow the attack categories described in MCPTox, the OWASP MCP Top 10 and the Invariant Labs disclosures. They were written without reusing the wording of any real attack, and a unit test checks that distinctive phrases from the real test attacks never appear in the templates. Benign notes get the same `<IMPORTANT>` tags, HTML comments and placements as attacks, so the model cannot learn that an inserted paragraph or a tag means poisoned.

## Labels for real tools

Real labels live in `datasets/labels.json` as ordered rules with a reason for each decision. Three kinds of example were excluded on purpose because a description classifier should not be judged on them. The first is tools that openly describe harmful capabilities, such as the 287 Cisco evaluation tools named like "Exploit sudo vulnerability". The second is attacks that live only in code or appear only at runtime, such as rug pulls. The third is teaching text that names a vulnerability openly. Exact duplicates were removed, and copies of the same attack across repositories share one family so they count once in confidence intervals.

## Evaluation one, real published attacks

The test set holds 16 real poisoned tools from 12 attack families, gathered from Invariant Labs, the Cisco MCP scanner examples, Damn Vulnerable MCP Server, the Invariant mcp-scan demo server and mcp-guardbench. None of these were used in training. They sit among 281 benign tools from repositories the model never saw and 248 hard negatives, which are benign tools taken from those same security projects. Intervals are 95% bootstrap intervals that resample whole attack families and whole repositories.

| Approach | PR-AUC | Recall | False positives |
|---|---|---|---|
| Rules only | 0.80 (0.56 to 0.97) | 0.81 (0.57 to 1.00) | 1 of 529 |
| Model, text features only | 0.79 (0.55 to 0.95) | 0.63 (0.31 to 0.84) | 2 of 529 |
| Model, text and rule features | 0.84 (0.64 to 0.96) | 0.69 (0.43 to 0.89) | 0 of 529 |
| Deployed policy, rules or model | not applicable | 0.88 (0.67 to 1.00) | 1 of 529 |

The deployed policy catches 14 of the 16 attacks and flags one benign tool in 529. That false positive is a demo tool that wraps a harmless note about number types in an `<IMPORTANT>` tag. The two attacks it misses are a hidden BCC instruction written as a plain compliance note and a Spanish attack whose phrasing looks nothing like the training templates. The intervals overlap heavily because there are only 16 real attacks, so the honest reading is that the policy is at least as good as rules alone and catches attacks that contain no rule keywords.

## Evaluation two, attack families never seen in training

Each attack family was removed from training in turn and then used as the test set, built on repositories the model never saw. This measures whether the model generalizes to new kinds of attack text, which matters more than its score on familiar ones.

| Held-out family | Rules recall | Model recall | Policy recall | Model false positive rate |
|---|---|---|---|---|
| Data exfiltration | 0.34 | 0.94 | 0.94 | 0.002 |
| Tool shadowing | 0.25 | 0.89 | 0.90 | 0.000 |
| Spanish attacks | 0.41 | 0.74 | 0.78 | 0.000 |
| Secret file reads | 0.65 | 0.72 | 0.77 | 0.000 |
| Fake compliance steps | 0.28 | 0.52 | 0.61 | 0.000 |
| Command injection | 0.46 | 0.49 | 0.60 | 0.000 |
| Instruction override | 0.24 | 0.26 | 0.40 | 0.000 |
| Preference manipulation | 0.26 | 0.24 | 0.40 | 0.000 |

The model generalizes well to attack families that share structure with others, such as exfiltration and shadowing. It struggles with families whose wording has little overlap with anything it saw, such as instruction override written without the usual keywords. The policy's false positive rate in this experiment is about nine percent, and all of it comes from the rules reacting to synthetic benign notes wrapped in tags. Those negatives were designed to look suspicious, and on real tools the policy's false positive rate is 0.2 percent.

## Comparison with earlier work

A 2026 study trained classifiers on MCPTox and reported perfect binary scores, while noting that the task might be too easy and that paraphrases were added before splitting. This project avoids those issues by testing only on real attacks that were never used for training, by grouping splits by repository and attack family, and by measuring generalization to unseen attack families.

## Known limits

The real test set is small, so every number here carries wide uncertainty. Synthetic templates cannot cover every way a person might phrase an attack, which the two missed real attacks show clearly. The model reads only text, so attacks that live in code or swap descriptions at runtime are out of scope. Benign labels for benchmark repositories rest on a full manual review of medium and high rule findings, but a quiet attack could still hide among the unreviewed low and none results. The full registry crawl in Phase 4 will grow both the benign corpus and the chance of finding real attacks in the wild.

## Reproducing

```bash
uv pip install -e ".[dev,ml]"
mcp-watcher extract $(sed 's/^/--repo /' docs/benchmark_repos.txt) --out data/bench_tools.jsonl --report data/bench_report.jsonl
mcp-watcher extract $(sed 's/^/--repo /' datasets/attack_repos.txt) --out data/attack_tools.jsonl --report data/attack_report.jsonl
python research/train_eval.py --tools data/bench_tools.jsonl data/attack_tools.jsonl
mcp-watcher scan --tools data/bench_tools.jsonl --out data/findings.jsonl --model models/watcher-lr-1.pkl
```
