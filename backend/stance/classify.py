"""
Run the trained stance model: (claim, abstract) -> stance + confidence.
Deterministic -- loads the saved model.joblib, so the same input always gives the same output.
The live path in main.py uses this to split PubMed results into support vs. oppose.
"""
import os
import sys

import joblib

HERE = os.path.dirname(__file__)
MODEL_PATH = os.path.join(HERE, "model.joblib")
sys.path.insert(0, HERE)

_bundle = None


def _load():
    global _bundle
    if _bundle is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError("No stance model found. Run train.py first.")
        _bundle = joblib.load(MODEL_PATH)
    return _bundle


def classify(claim: str, text: str) -> dict:
    b = _load()
    rec = [{"claim": claim, "text": text}]
    X = b["featurizer"].transform(rec)
    proba = b["clf"].predict_proba(X)[0]
    labels = list(b["clf"].classes_)
    dist = {lab: float(p) for lab, p in zip(labels, proba)}
    top = max(dist, key=dist.get)
    return {"stance": top, "confidence": dist[top], "dist": dist}


def is_available() -> bool:
    return os.path.exists(MODEL_PATH)
