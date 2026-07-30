"""
Train and evaluate the stance classifier.
Training set = seed_train.jsonl + pool_labeled.jsonl (grown by active learning; empty at first)
Eval set     = gold.jsonl, never trained on, so the numbers stay honest

  python train.py            # train + evaluate + save the model
  python train.py --round r2 # tag the round in runs.jsonl
"""
import json
import os
import sys

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")
MODEL_PATH = os.path.join(HERE, "model.joblib")          # deployed = best checkpoint on gold
LATEST_PATH = os.path.join(HERE, "model_latest.joblib")  # always the most recent round
BEST_PATH = os.path.join(HERE, "best.json")
RUNS_PATH = os.path.join(HERE, "runs.jsonl")
LABELS = ["SUPPORT", "OPPOSE", "NEUTRAL"]

sys.path.insert(0, HERE)
from features import StanceFeaturizer  # noqa: E402
from texts import hydrate  # noqa: E402


def load_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def train(round_tag: str = "r0") -> dict:
    train_recs = load_jsonl(os.path.join(DATA, "seed_train.jsonl"))
    train_recs += load_jsonl(os.path.join(DATA, "pool_labeled.jsonl"))
    gold = load_jsonl(os.path.join(DATA, "gold.jsonl"))
    if not train_recs or not gold:
        raise SystemExit("No training or eval data.")

    # The repo carries no abstract text (copyright), so fill it in from the local
    # cache keyed by pmid. Missing cache fails loudly, pointing at `python rehydrate.py`.
    train_recs = hydrate(train_recs)
    gold = hydrate(gold)

    feat = StanceFeaturizer()
    Xtr = feat.fit_transform(train_recs)
    ytr = [r["stance"] for r in train_recs]

    clf = LogisticRegression(
        max_iter=2000, C=4.0, class_weight="balanced", random_state=42
    )
    clf.fit(Xtr, ytr)

    Xte = feat.transform(gold)
    yte = [r["stance"] for r in gold]
    pred = clf.predict(Xte)

    macro_f1 = f1_score(yte, pred, labels=LABELS, average="macro", zero_division=0)
    acc = float(np.mean([p == t for p, t in zip(pred, yte)]))
    report = classification_report(yte, pred, labels=LABELS, zero_division=0, digits=3)
    cm = confusion_matrix(yte, pred, labels=LABELS)

    bundle = {"featurizer": feat, "clf": clf, "labels": LABELS}
    joblib.dump(bundle, LATEST_PATH)

    # Best-checkpoint rule: only replace the deployed model when gold macro F1
    # is at least as good as the previous best.
    prev_best = -1.0
    if os.path.exists(BEST_PATH):
        with open(BEST_PATH, "r", encoding="utf-8") as f:
            prev_best = json.load(f).get("macro_f1", -1.0)
    deployed = float(macro_f1) >= prev_best
    if deployed:
        joblib.dump(bundle, MODEL_PATH)
        with open(BEST_PATH, "w", encoding="utf-8") as f:
            json.dump({"round": round_tag, "macro_f1": round(float(macro_f1), 4),
                       "accuracy": round(acc, 4), "n_train": len(train_recs)}, f, ensure_ascii=False)

    metrics = {"round": round_tag, "n_train": len(train_recs), "n_gold": len(gold),
               "accuracy": round(acc, 4), "macro_f1": round(float(macro_f1), 4), "deployed": deployed}
    with open(RUNS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(metrics, ensure_ascii=False) + "\n")

    print(f"=== round {round_tag} | train={len(train_recs)} gold={len(gold)} ===")
    print(f"accuracy={acc:.3f}  macro_F1={macro_f1:.3f}  deployed={deployed} (prev_best={prev_best})")
    print(report)
    print("confusion (rows=true, cols=pred)", LABELS)
    print(cm)
    return metrics


if __name__ == "__main__":
    tag = "r0"
    if "--round" in sys.argv:
        tag = sys.argv[sys.argv.index("--round") + 1]
    train(tag)
