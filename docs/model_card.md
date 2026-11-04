# Model card for watcher-lr-2

watcher-lr-2 scores the text of an MCP tool for signs of tool poisoning. Tool poisoning means a description or parameter description that tries to turn the model against the person using it, for example by asking it to read private files, send data away, change how other tools behave, or hide what it is doing. All numbers below come from `research/train_eval.py` with seed 20261102, and the raw results live in `docs/results/phase6.json`.

watcher-lr-2 replaced watcher-lr-1 as the deployed model in Phase 6. The architecture, training data and seed did not change, but the rules feed the model as features and several rules were narrowed after a review of live registry flags, so the model was trained again. watcher-lr-1 was itself named sentinel-lr-1 until the project was renamed, and its original results remain in `docs/results/phase3.json`.

## What the model is

The model is a logistic regression over TF-IDF word and character n-grams, plus the nine rule signal families from Phase 2. It is small enough to run on a laptop CPU in milliseconds, and every score can be explained through the words that raised it and the rule findings with their evidence spans. Scores are rankings and should not be read as probabilities. The decision threshold is set so that about one percent of real benign training tools would be flagged in cross-validation.

## How a tool is labeled

| Rule evidence | Model crosses its threshold | Published level |
|---|---|---|
| Medium or high | either way | the rule level |
| Low | yes | medium |
| Low | no | low, not published |
| None | yes | watch, published for review and never counted as a flag |
| None | no | none |

The watch tier is new in Phase 6. A review of 100 live flags found that tools flagged by the classifier with no rule evidence at all were worth a human look only about three times in a hundred, so they no longer count toward the number of flagged tools. They stay on the site under a classifier only tab, because the same evaluation showed that dropping them would cost recall on real attacks.

Two choices here were made with results already in view, and they are stated so nobody mistakes them for choices made in advance. The original policy of flagging when the rules reach medium or the model crosses its threshold was chosen after the first evaluation run showed that the two approaches miss different attacks. The watch tier was chosen after the Phase 6 run showed that requiring rule evidence for every flag would lower recall on the real test attacks from 14 of 16 to 13 of 16.

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

The test set holds 16 real poisoned tools from 12 attack families, gathered from Invariant Labs, the Cisco MCP scanner examples, Damn Vulnerable MCP Server, the Invariant mcp-scan demo server and mcp-guardbench. None of these attacks were ever used in training. They sit among 281 benign tools from repositories the model never saw and 248 hard negatives, which are benign tools taken from those same security projects. Intervals are 95% bootstrap intervals that resample whole attack families and whole repositories.

| Approach | PR-AUC | Recall | False positives |
|---|---|---|---|
| Rules only | 0.80 (0.56 to 0.97) | 0.81 (0.57 to 1.00) | 1 of 529 |
| Model, text features only | 0.79 (0.55 to 0.95) | 0.62 (0.31 to 0.84) | 2 of 529 |
| Model, text and rule features | 0.84 (0.64 to 0.96) | 0.69 (0.43 to 0.89) | 0 of 529 |
| Flags plus the watch tier | not applicable | 0.88 (0.67 to 1.00) | 1 of 529 |
| Counted flags only | not applicable | 0.81 (0.57 to 1.00) | 1 of 529 |

Flags and the watch tier together catch 14 of the 16 attacks and raise one benign tool in 529. That false positive is a demo tool that wraps a harmless note about number types in an `<IMPORTANT>` tag. Counted flags alone catch 13 of 16, and the one difference is a Cisco line jumping example that only the classifier noticed, which now appears in the watch tier. The two attacks that nothing catches are a hidden BCC instruction written as a plain compliance note and a Spanish attack whose phrasing looks nothing like the training templates. These numbers match watcher-lr-1 to two decimals, because the narrowed rules changed nothing in this benchmark.

## Evaluation two, attack families never seen in training

Each attack family was removed from training in turn and then used as the test set, built on repositories the model never saw. This measures whether the model generalizes to new kinds of attack text, which matters more than its score on familiar ones.

| Held-out family | Rules recall | Model recall | Flags plus watch | Counted flags only | Model false positive rate | Policy false positive rate |
|---|---|---|---|---|---|---|
| Data exfiltration | 0.34 | 0.94 | 0.94 | 0.66 | 0.002 | 0.100 |
| Tool shadowing | 0.25 | 0.89 | 0.90 | 0.63 | 0.000 | 0.077 |
| Spanish attacks | 0.39 | 0.74 | 0.77 | 0.59 | 0.000 | 0.072 |
| Secret file reads | 0.65 | 0.72 | 0.77 | 0.68 | 0.000 | 0.086 |
| Fake compliance steps | 0.27 | 0.53 | 0.60 | 0.27 | 0.000 | 0.086 |
| Command injection | 0.45 | 0.48 | 0.58 | 0.45 | 0.000 | 0.070 |
| Instruction override | 0.21 | 0.24 | 0.37 | 0.21 | 0.000 | 0.095 |
| Preference manipulation | 0.26 | 0.24 | 0.40 | 0.26 | 0.000 | 0.072 |

The model generalizes well to attack families that share structure with others, such as exfiltration and shadowing. It struggles with families whose wording has little overlap with anything it saw, such as instruction override written without the usual keywords. The policy's false positive rate in this experiment comes entirely from the rules reacting to synthetic benign notes wrapped in tags, and it fell in every family after the Phase 6 rule changes, by between one and six tools. Rules recall on these synthetic attacks also fell by up to three points, because the narrowed rules no longer fire on some synthetic text that borrows ordinary documentation phrasing.

## Evaluation three, flags on the live registry

The benchmarks above say little about the live registry, where tool text is far more varied. Phase 6 therefore drew 100 flags from the run published on November 3, 2026, stratified by how each tool was caught and by level, and read every one in context. Each was labeled a concern when the text steers the assistant against the person using it, a demo when it is a security example or test fixture, and a false alarm otherwise. The labels and reasons live in `datasets/registry_review_a.json`.

| How it was caught | Flags in the run | Reviewed | Concern or demo |
|---|---|---|---|
| Rules and model, high | 71 | 10 | 4 |
| Rules only, high | 110 | 15 | 4 |
| Rules and model, medium | 168 | 23 | 1 |
| Rules only, medium | 123 | 17 | 1 |
| Model only | 252 | 35 | 1 |

Weighted back to the 724 flags in that run, roughly one flag in nine deserved a human look. The false alarms fell into clear patterns, which were tools whose whole job is SSH, agent setup or `.env` handling, negated or conditional sentences such as "never publish without asking the user", documentation tags used as section headings, short HTML comment markers, and long imperative product text that only the classifier reacted to. The narrowed rules and the watch tier answer those patterns. Because this sample guided the changes, it is a development set and its precision is not a fair measure of the new policy.

A second sample was drawn from the run published on November 4, after the changes, with every tool from sample A left out of the frame. Nothing was tuned on it, and its labels live in `datasets/registry_review_b.json`.

| Group in sample B | Read | Concern or demo | 95% interval |
|---|---|---|---|
| Counted flags | 50 | 4 (8%) | 3% to 19% |
| High | 19 | 3 (16%) | 6% to 38% |
| Medium from a rule alone | 12 | 0 | 0% to 24% |
| Medium lifted by the model | 19 | 1 (5%) | 1% to 25% |
| Watch tier | 20 | 0 | 0% to 16% |

The changes halved the counted flags from 724 to 360 while keeping every concern and demo from sample A, but they did not measurably raise precision on live data. The watch tier held nothing worth a look, which supports keeping it out of the count. Most remaining false alarms come from tools whose purpose involves secrets or security, and `docs/findings.md` describes them along with the consent patterns that made up every real concern.

## Comparison with earlier work

A 2026 study trained classifiers on MCPTox and reported perfect binary scores, while noting that the task might be too easy and that paraphrases were added before splitting. This project avoids those issues by testing only on real attacks that were never used for training, by grouping splits by repository and attack family, by measuring generalization to unseen attack families, and by reviewing its own flags on live data.

## Known limits

The real test set is small, so every number here carries wide uncertainty. Synthetic templates cannot cover every way a person might phrase an attack, which the two missed real attacks show clearly. The model reads only text, so attacks that live in code or swap descriptions at runtime are out of scope. The live review shows that a clean score on curated benchmarks does not carry over to the registry, and the precision measured there is the number to trust. The review labels were drafted from the tool text and evidence by an assistant and await confirmation by the project owner.

## Reproducing

```bash
uv pip install -e ".[dev,ml]"
mcp-watcher extract $(sed 's/^/--repo /' docs/benchmark_repos.txt) --out data/bench_tools.jsonl --report data/bench_report.jsonl
mcp-watcher extract $(sed 's/^/--repo /' datasets/attack_repos.txt) --out data/attack_tools.jsonl --report data/attack_report.jsonl
python research/train_eval.py --tools data/bench_tools.jsonl data/attack_tools.jsonl
mcp-watcher scan --tools data/bench_tools.jsonl --out data/findings.jsonl --model models/watcher-lr-2.pkl
```
