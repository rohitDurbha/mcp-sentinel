"""Classifier that scores tool text for poisoning risk.

Features are TF-IDF word and character n-grams plus the Phase 2 rule signals, fed to a
logistic regression. The model is small, fast on a CPU, and explainable, because every
score can be traced to weighted terms and to rule findings with evidence spans.

Scores are rankings, not probabilities. Training positives are synthetic and far more
common than poisoning is in the wild, so a calibrated probability would be misleading.
The decision threshold is chosen to hit a target false positive rate on real benign
tools instead.
"""

from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from .models import Tool
from .signals import SEVERITY_WEIGHT, scan_text

SIGNAL_NAMES = (
    "hidden_block", "secrecy", "sensitive_path", "exfiltration", "override",
    "coercion", "cross_tool", "invisible_unicode", "long_text",
)  # fmt: skip
MODEL_VERSION = "sentinel-lr-1"


def rule_features(text: str) -> list[float]:
    """Strongest severity per signal family, plus count and log length."""
    strongest = dict.fromkeys(SIGNAL_NAMES, 0.0)
    findings = scan_text(text, "description")
    for f in findings:
        strongest[f.signal] = max(strongest[f.signal], SEVERITY_WEIGHT[f.severity])
    return [*strongest.values(), min(len(findings), 10) / 10, math.log1p(len(text)) / 10]


@dataclass
class SentinelModel:
    use_text: bool = True
    use_rules: bool = True
    C: float = 2.0
    threshold: float = 0.5
    version: str = MODEL_VERSION
    word: TfidfVectorizer = field(default=None, repr=False)
    char: TfidfVectorizer = field(default=None, repr=False)
    clf: LogisticRegression = field(default=None, repr=False)

    def _features(self, texts: list[str], fit: bool = False):
        blocks = []
        if self.use_text:
            if fit:
                self.word = TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=20000,
                                            sublinear_tf=True, lowercase=True)  # fmt: skip
                self.char = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=3,
                                            max_features=30000, sublinear_tf=True)  # fmt: skip
                blocks += [self.word.fit_transform(texts), self.char.fit_transform(texts)]
            else:
                blocks += [self.word.transform(texts), self.char.transform(texts)]
        if self.use_rules:
            blocks.append(csr_matrix(np.array([rule_features(t) for t in texts]) * 3.0))
        return hstack(blocks).tocsr()

    def fit(self, texts: list[str], labels: list[int]) -> SentinelModel:
        X = self._features(texts, fit=True)
        self.clf = LogisticRegression(C=self.C, class_weight="balanced", max_iter=4000)
        self.clf.fit(X, np.asarray(labels))
        return self

    def decision(self, texts: list[str]) -> np.ndarray:
        return self.clf.predict_proba(self._features(texts))[:, 1]

    def top_terms(self, text: str, k: int = 5) -> list[tuple[str, float]]:
        """Words and phrases that pushed this text's score up the most, for explanations."""
        if not self.use_text:
            return []
        names = self.word.get_feature_names_out()
        x = self.word.transform([text]).tocoo()
        coef = self.clf.coef_[0][: len(names)]
        contrib = sorted(
            ((names[j], v * coef[j]) for j, v in zip(x.col, x.data, strict=True)),
            key=lambda p: -p[1],
        )
        return [(term, round(float(w), 4)) for term, w in contrib[:k] if w > 0]

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(pickle.dumps(self, protocol=5))

    @staticmethod
    def load(path: Path) -> SentinelModel:
        # Only ever load model files produced by this project's own training script.
        return pickle.loads(Path(path).read_bytes())


def tool_text(tool: Tool) -> str:
    from .dataset import model_text

    return model_text(tool.description, [(p.name or "", p.text) for p in tool.params])


def threshold_for_fpr(benign_scores: np.ndarray, target_fpr: float) -> float:
    """Smallest threshold whose false positive rate on benign scores stays within target."""
    ordered = np.sort(np.asarray(benign_scores))[::-1]
    allowed = math.floor(target_fpr * len(ordered))
    return float(ordered[allowed]) + 1e-9 if allowed < len(ordered) else 0.0


__all__ = ["SentinelModel", "rule_features", "threshold_for_fpr", "tool_text"]
