"""
StanceFeaturizer: a (claim, abstract) pair -> feature vector.
TF-IDF over word 1-2 grams, plus hand-built cue features
(negation / effect / hedging / claim overlap).
Deterministic -- with the fitted vocabulary and IDF saved via joblib,
the same input always yields the same vector.
"""
import re

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer

from lexicon import HEDGE_CUES, NEG_CUES, NEUTRAL_CUES, POS_CUES, count_cues

_WORD = re.compile(r"[a-zA-Z][a-zA-Z\-]+")
_STOP = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "is",
         "are", "was", "were", "be", "with", "that", "this", "by", "as", "at"}


def _content_words(s: str) -> set[str]:
    return {w for w in _WORD.findall(s.lower()) if w not in _STOP and len(w) > 2}


def _engineered(claim: str, text: str) -> list[float]:
    low = text.lower()
    n = max(len(low.split()), 1)
    pos = count_cues(low, POS_CUES)
    neg = count_cues(low, NEG_CUES)
    hedge = count_cues(low, HEDGE_CUES)
    neutral = count_cues(low, NEUTRAL_CUES)
    cw = _content_words(claim)
    overlap = (len(cw & _content_words(text)) / len(cw)) if cw else 0.0
    return [
        pos / n * 10.0,
        neg / n * 10.0,
        hedge / n * 10.0,
        (pos - neg) / n * 10.0,
        1.0 if ("no significant" in low or "not significant" in low) else 0.0,
        1.0 if ("did not" in low or "failed to" in low) else 0.0,
        1.0 if "no better than placebo" in low else 0.0,
        overlap,
        min(neg, 1),  # any negative cue at all
        min(pos, 1),
        neutral / n * 10.0,           # NEUTRAL cue density
        min(neutral, 1),              # any NEUTRAL cue at all
        1.0 if overlap < 0.15 else 0.0,  # off-topic: barely overlaps the claim
    ]


class StanceFeaturizer:
    def __init__(self):
        self.tfidf = TfidfVectorizer(
            ngram_range=(1, 2), min_df=1, sublinear_tf=True, max_features=4000
        )

    def fit(self, records: list[dict]):
        self.tfidf.fit([r["text"] for r in records])
        return self

    def transform(self, records: list[dict]) -> csr_matrix:
        X_text = self.tfidf.transform([r["text"] for r in records])
        X_eng = np.array([_engineered(r.get("claim", ""), r["text"]) for r in records])
        return hstack([X_text, csr_matrix(X_eng)]).tocsr()

    def fit_transform(self, records: list[dict]) -> csr_matrix:
        return self.fit(records).transform(records)
