"""
Unattended closed-loop orchestrator (Claude = Fable teacher).

One round = mine (pull uncertain abstracts) -> teacher.label_batch (Fable labels)
-> append to pool_labeled.jsonl -> train (retrain + gold eval + log to runs.jsonl).

  ANTHROPIC_API_KEY=... python auto_loop.py --rounds 5

ANTHROPIC_API_KEY is required to run fully unattended (e.g. an AWS deployment).
Without a key it only mines, then points you at manual labeling.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)

import mine as miner  # noqa: E402
import teacher  # noqa: E402
import train as trainer  # noqa: E402
from texts import hydrate, text_hash  # noqa: E402

DATA = os.path.join(HERE, "data")


def _append_pool(items: list[dict], stances: list[str | None]) -> int:
    """Abstract bodies never land in the repo — only pmid + body fingerprint."""
    dst = os.path.join(DATA, "pool_labeled.jsonl")
    added = 0
    with open(dst, "a", encoding="utf-8") as out:
        for it, st in zip(items, stances):
            if st not in ("SUPPORT", "OPPOSE", "NEUTRAL"):
                continue
            out.write(json.dumps({
                "claim": it["claim"], "polarity": it.get("polarity", "beneficial"),
                "stance": st, "pmid": it.get("pmid"),
                "text_sha256": text_hash(it["text"]),
            }, ensure_ascii=False) + "\n")
            added += 1
    return added


def run(rounds: int, batch: int):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY -> can't run unattended. Mining only, then exiting.")
        miner.mine(total=batch)
        print("Label to_label.jsonl by hand, then run commit_labels.py.")
        return

    history = []
    for r in range(rounds):
        tag = f"auto_r{r}"
        print(f"\n########## ROUND {tag} ##########")
        miner.mine(total=batch)
        with open(os.path.join(DATA, "to_label.jsonl"), "r", encoding="utf-8") as f:
            items = [json.loads(ln) for ln in f if ln.strip()]
        if not items:
            print("No new abstracts mined -> stopping early")
            break
        items = hydrate(items)  # fill in the abstract bodies the teacher reads
        stances = teacher.label_batch(items)
        added = _append_pool(items, stances)
        print(f"[{tag}] committed {added}/{len(items)} Fable teacher labels")
        metrics = trainer.train(round_tag=tag)
        history.append(metrics)
        # Early stop: bail out if macro_f1 hasn't improved over the last two rounds
        if len(history) >= 3:
            a, b, c = history[-3]["macro_f1"], history[-2]["macro_f1"], history[-1]["macro_f1"]
            if c <= a + 0.002 and c <= b + 0.002:
                print("macro_F1 plateaued -> stopping early")
                break

    print("\n=== auto loop summary ===")
    for m in history:
        print(f"{m['round']}: train={m['n_train']} acc={m['accuracy']} macroF1={m['macro_f1']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--batch", type=int, default=18)
    a = ap.parse_args()
    run(a.rounds, a.batch)
