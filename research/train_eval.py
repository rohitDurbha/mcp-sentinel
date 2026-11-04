"""Phase 3 training and evaluation.

Usage:
    python research/train_eval.py --tools data/bench_tools.jsonl data/attack_tools.jsonl

Writes docs/results/phase3.json and models/watcher-lr-1.pkl. Every random choice is
seeded, so the numbers in the model card can be reproduced exactly.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score
from sklearn.model_selection import GroupKFold

from mcp_watcher.dataset import Row, load_labels, model_text, real_rows, split_of
from mcp_watcher.model import WatcherModel, threshold_for_fpr
from mcp_watcher.signals import scan_text
from mcp_watcher.signals import score as rule_score
from mcp_watcher.synth import ATTACK_FAMILIES, benign_variant, poison

SEED = 20261102
TARGET_FPR = 0.01
RULE_THRESHOLD = 0.3  # rule level medium or above
BENCH_REPOS = {
    line.split("github.com/")[1].lower()
    for line in Path("docs/benchmark_repos.txt").read_text().split()
}


def text_of(row: Row) -> str:
    return model_text(row.text, row.params)


def synth_rows(bases: list[Row], families, rng: random.Random, per_base: int = 1) -> list[Row]:
    out = []
    for base in bases:
        for _ in range(per_base):
            s = poison(base.text, base.key, rng.choice(families), rng)
            # Grouped by the base repository so folds never share base text.
            out.append(Row(s.text, s.params, 1, s.family, base.group, "synthetic", base.key))
        b = benign_variant(base.text, base.key, rng)
        out.append(Row(b.text, b.params, 0, "benign_note", base.group, "synthetic", base.key))
    return out


def usable_base(row: Row) -> bool:
    return row.label == 0 and not row.params and 20 <= len(row.text) <= 1500 and "{" not in row.text


def rule_scores(texts: list[str]) -> np.ndarray:
    return np.array([rule_score(scan_text(t, "description")) for t in texts])


def oof_threshold(variant: dict, rows: list[Row]) -> float:
    """Threshold for the target FPR, from out-of-fold scores on real benign training rows."""
    texts = [text_of(r) for r in rows]
    labels = np.array([r.label for r in rows])
    groups = np.array([r.group for r in rows])
    real_benign = np.array([r.source == "real" and r.label == 0 for r in rows])
    oof = np.zeros(len(rows))
    for tr, te in GroupKFold(n_splits=5).split(texts, labels, groups):
        m = WatcherModel(**variant).fit([texts[i] for i in tr], labels[tr])
        oof[te] = m.decision([texts[i] for i in te])
    return threshold_for_fpr(oof[real_benign], TARGET_FPR)


def metrics(scores: np.ndarray, labels: np.ndarray, threshold: float) -> dict:
    pred = scores >= threshold
    pos, neg = labels == 1, labels == 0
    return {
        "pr_auc": round(float(average_precision_score(labels, scores)), 4) if pos.any() else None,
        "recall": round(float(pred[pos].mean()), 4) if pos.any() else None,
        "fpr": round(float(pred[neg].mean()), 4),
        "false_positives": int(pred[neg].sum()),
        "negatives": int(neg.sum()),
        "positives": int(pos.sum()),
    }


def bootstrap(scores, labels, groups, threshold, n=1000, seed=SEED) -> dict:
    """95% intervals, resampling whole groups (attack families and repositories)."""
    rng = np.random.default_rng(seed)
    by_group = defaultdict(list)
    for i, g in enumerate(groups):
        by_group[g].append(i)
    pos_g = [g for g, idx in by_group.items() if labels[idx[0]] == 1]
    neg_g = [g for g, idx in by_group.items() if labels[idx[0]] == 0]
    pr, rec = [], []
    for _ in range(n):
        idx = []
        for pool in (pos_g, neg_g):
            for g in rng.choice(pool, size=len(pool), replace=True):
                idx += by_group[g]
        s, y = scores[idx], labels[idx]
        pr.append(average_precision_score(y, s))
        rec.append((s[y == 1] >= threshold).mean())
    q = lambda a: [round(float(np.percentile(a, 2.5)), 4), round(float(np.percentile(a, 97.5)), 4)]  # noqa: E731
    return {"pr_auc_95": q(pr), "recall_95": q(rec)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tools", nargs="+", type=Path, required=True)
    ap.add_argument("--labels", type=Path, default=Path("datasets/labels.json"))
    ap.add_argument("--out", type=Path, default=Path("docs/results/phase3.json"))
    ap.add_argument("--model", type=Path, default=Path("models/watcher-lr-1.pkl"))
    args = ap.parse_args()

    rows, dropped = real_rows(args.tools, load_labels(args.labels))
    real_pos = [r for r in rows if r.label == 1]
    bench_benign = [r for r in rows if r.label == 0 and r.group in BENCH_REPOS]
    attack_benign = [r for r in rows if r.label == 0 and r.group not in BENCH_REPOS]
    train_benign = [r for r in bench_benign if split_of(r.group) == "train"]
    test_benign = [r for r in bench_benign if split_of(r.group) == "test"]
    print(f"real positives {len(real_pos)} in {len({r.family for r in real_pos})} families, "
          f"train benign {len(train_benign)}, test benign {len(test_benign)} + {len(attack_benign)} hard, dropped {dropped}")  # fmt: skip

    rng = random.Random(SEED)
    train_bases = [r for r in train_benign if usable_base(r)]
    test_bases = [r for r in test_benign if usable_base(r)]
    variants = {
        "text_only": {"use_text": True, "use_rules": False},
        "combined": {"use_text": True, "use_rules": True},
    }
    results: dict = {"seed": SEED, "target_fpr": TARGET_FPR, "dropped": dropped}
    results["data"] = {
        "real_positives": len(real_pos), "real_positive_families": sorted({r.family for r in real_pos}),
        "train_benign": len(train_benign), "test_benign": len(test_benign), "hard_negatives": len(attack_benign),
        "train_bases": len(train_bases), "test_bases": len(test_bases),
    }  # fmt: skip

    # Experiment 1. Train on synthetic positives only, test on real published attacks.
    train = train_benign + synth_rows(train_bases, ATTACK_FAMILIES, rng)
    test = real_pos + test_benign + attack_benign
    test_texts = [text_of(r) for r in test]
    y = np.array([r.label for r in test])
    groups = [r.group for r in test]
    e1: dict = {}
    rs = rule_scores(test_texts)
    e1["rules"] = {**metrics(rs, y, RULE_THRESHOLD), **bootstrap(rs, y, groups, RULE_THRESHOLD)}
    rules_missed = [i for i, r in enumerate(test) if r.label == 1 and rs[i] < RULE_THRESHOLD]
    e1["rules_missed_keys"] = [test[i].key for i in rules_missed]
    for name, variant in variants.items():
        thr = oof_threshold(variant, train)
        model = WatcherModel(**variant, threshold=thr).fit(
            [text_of(r) for r in train], [r.label for r in train]
        )
        s = model.decision(test_texts)
        e1[name] = {
            **metrics(s, y, thr),
            **bootstrap(s, y, groups, thr),
            "threshold": round(thr, 6),
        }
        e1[name]["recall_on_rule_misses"] = (
            round(float((s[rules_missed] >= thr).mean()), 4) if rules_missed else None
        )
        e1[name]["false_positive_keys"] = [test[i].key for i in np.where((s >= thr) & (y == 0))[0]]
        e1[name]["missed_keys"] = [test[i].key for i in np.where((s < thr) & (y == 1))[0]]
        if name == "combined":
            model.save(args.model)
            combined_scores, combined_thr = s, thr
    # Deployed policy: flag when rules reach medium or the model crosses its threshold.
    # This policy was chosen after the first run showed the two fail on different attacks.
    flags = ((rs >= RULE_THRESHOLD) | (combined_scores >= combined_thr)).astype(float)
    policy = {**metrics(flags, y, 0.5), **bootstrap(flags, y, groups, 0.5)}
    policy.pop("pr_auc"), policy.pop("pr_auc_95")
    policy["missed_keys"] = [test[i].key for i in np.where((flags < 0.5) & (y == 1))[0]]
    policy["false_positive_keys"] = [test[i].key for i in np.where((flags > 0.5) & (y == 0))[0]]
    e1["policy_rules_or_model"] = policy
    results["real_world"] = e1

    # Experiment 2. Leave one attack family out, test on that family over unseen repositories.
    e2: dict = {}
    for held in ATTACK_FAMILIES:
        fam_rng = random.Random(f"{SEED}-{held}")
        others = [f for f in ATTACK_FAMILIES if f != held]
        train = train_benign + synth_rows(train_bases, others, fam_rng)
        test_pos = []
        for b in test_bases:
            s_ = poison(b.text, b.key, held, fam_rng)
            test_pos.append(
                Row(s_.text, s_.params, 1, held, f"synth:{held}:{b.group}", "synthetic", b.key)
            )
        test_neg = test_benign + [
            r for r in synth_rows(test_bases, others, fam_rng) if r.label == 0
        ]
        test = test_pos + test_neg
        texts = [text_of(r) for r in test]
        y2 = np.array([r.label for r in test])
        row = {"rules": metrics(rule_scores(texts), y2, RULE_THRESHOLD)}
        variant = variants["combined"]
        thr = oof_threshold(variant, train)
        m = WatcherModel(**variant).fit([text_of(r) for r in train], [r.label for r in train])
        ms = m.decision(texts)
        row["combined"] = metrics(ms, y2, thr)
        either = ((rule_scores(texts) >= RULE_THRESHOLD) | (ms >= thr)).astype(float)
        row["policy_rules_or_model"] = metrics(either, y2, 0.5)
        row["policy_rules_or_model"].pop("pr_auc")
        e2[held] = row
        print(f"  held out {held:<24} rules {row['rules']['recall']:.2f}  model {row['combined']['recall']:.2f}  either {row['policy_rules_or_model']['recall']:.2f}  fpr {row['policy_rules_or_model']['fpr']:.3f}")  # fmt: skip
    results["unseen_families"] = e2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    for name in ("rules", "text_only", "combined"):
        r = e1[name]
        print(f"{name:<10} PR-AUC {r['pr_auc']} {r['pr_auc_95']}  recall {r['recall']} {r['recall_95']}  "
              f"FP {r['false_positives']}/{r['negatives']}")  # fmt: skip
    p = e1["policy_rules_or_model"]
    print(
        f"policy     recall {p['recall']} {p['recall_95']}  FP {p['false_positives']}/{p['negatives']}  missed {p['missed_keys']}"
    )
    print("rules missed:", e1["rules_missed_keys"])
    print("combined recall on rule misses:", e1["combined"]["recall_on_rule_misses"])


if __name__ == "__main__":
    main()
