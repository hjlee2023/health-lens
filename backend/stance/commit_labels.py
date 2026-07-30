"""
Merges the teacher's verdicts (pmid -> stance) with to_label.jsonl and appends
them to pool_labeled.jsonl. Commit tool for the human-teacher loop.

  python commit_labels.py

Abstract bodies never go into the repo, so only the pmid and a body fingerprint
(text_sha256) are recorded. Run `python rehydrate.py` if you need the bodies.
"""
import json
import os
import sys

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from texts import hydrate, text_hash  # noqa: E402

# Round 3 verdicts (Fable teacher, 18 mined items):
LABELS = {
    "37702300": "NEUTRAL",  # Cochrane AMD (eye) review -> off-topic for cancer prevention
    "38922615": "OPPOSE",   # large cohort: no mortality benefit from multivitamins
    "15277288": "OPPOSE",   # meta of 7 RCTs: no cardiovascular effect from vitamin E
    "39534260": "SUPPORT",  # RCT: magnesium (+/- potassium) cut insomnia severity
    "32599716": "SUPPORT",  # RCT: creatine significantly increased strength
    "40265319": "NEUTRAL",  # creatine vs hair loss/DHT, not strength -> off-topic
    "37432180": "SUPPORT",  # meta of 26 RCTs: collagen improved skin hydration and elasticity
    "11926784": "SUPPORT",  # meta of 54 RCTs: aerobic exercise lowered blood pressure
    "14633804": "SUPPORT",  # RCT: cinnamon 1-6g lowered fasting glucose
    "33591366": "SUPPORT",  # umbrella review: fiber inversely linked to CRC risk (convincing)
    "39685902": "SUPPORT",  # NMA: glucosamine combination therapy reduced pain
    "33509399": "OPPOSE",   # updated meta: no mortality effect from multivitamins
    "38917435": "SUPPORT",  # meta of 28 RCTs: cinnamon lowered fasting glucose and HbA1c
    "30675873": "SUPPORT",  # HTA IPD meta of 25 RCTs: vitamin D lowered ARI risk
    "28202713": "SUPPORT",  # 2017 BMJ IPD meta: vitamin D lowered ARI risk
    "30705687": "SUPPORT",  # RCT: nanocurcumin lowered TNF-a, CRP, IL-6
    "40918053": "SUPPORT",  # RCT: magnesium bisglycinate modestly improved insomnia
    "38932663": "SUPPORT",  # RCT: IF 16:8/14:10 beat control on weight loss
}


def main():
    src = os.path.join(DATA, "to_label.jsonl")
    dst = os.path.join(DATA, "pool_labeled.jsonl")
    with open(src, "r", encoding="utf-8") as f:
        items = [json.loads(ln) for ln in f if ln.strip()]
    items = hydrate(items)  # need the body to compute the fingerprint
    added = 0
    with open(dst, "a", encoding="utf-8") as out:
        for it in items:
            st = LABELS.get(it["pmid"])
            if st is None:
                continue
            out.write(json.dumps({
                "claim": it["claim"], "polarity": it.get("polarity", "beneficial"),
                "stance": st, "pmid": it["pmid"],
                "text_sha256": text_hash(it["text"]),
            }, ensure_ascii=False) + "\n")
            added += 1
    print(f"Appended {added} rows to pool_labeled.jsonl (out of {len(LABELS)} labels)")


if __name__ == "__main__":
    main()
