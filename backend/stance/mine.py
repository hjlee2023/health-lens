"""
Active-learning miner: pulls a pool of unlabeled abstracts from PubMed live,
picks the ones the current model is least sure about (smallest top1-top2
probability margin), and writes them to to_label.jsonl for a human (or LLM)
teacher to label.

  python mine.py            # mine with the default claim set
"""
import json
import os
import sys

HERE = os.path.dirname(__file__)
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, BACKEND)

import pubmed  # noqa: E402
import classify  # noqa: E402
from texts import save_texts, text_hash  # noqa: E402

DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "to_label.jsonl")

# Fields written to to_label.jsonl (abstract body left out — copyright)
OUT_FIELDS = ("margin", "claim", "polarity", "pmid", "pred", "dist")

# Mining targets: (claim, PubMed query, polarity). Overlapping the training set
# is fine — the abstracts themselves are new. Topics that often turn up null or
# negative results are mixed in to push the OPPOSE boundary.
CLAIMS = [
    ("간헐적 단식이 체중 감량에 효과적이다", "intermittent fasting body weight randomized", "beneficial"),
    ("비타민D 보충이 호흡기 감염을 예방한다", "vitamin D respiratory infection randomized trial", "beneficial"),
    ("프로바이오틱스가 과민성대장증후군을 개선한다", "probiotics irritable bowel syndrome randomized", "beneficial"),
    ("커피가 사망률을 낮춘다", "coffee consumption all-cause mortality cohort", "beneficial"),
    ("아연 보충이 감기 지속 기간을 줄인다", "zinc common cold duration randomized", "beneficial"),
    ("글루코사민이 골관절염 통증을 완화한다", "glucosamine knee osteoarthritis pain trial", "beneficial"),
    ("마그네슘 보충이 수면을 개선한다", "magnesium sleep insomnia randomized", "beneficial"),
    ("커큐민이 염증을 줄인다", "curcumin inflammation CRP randomized trial", "beneficial"),
    ("종합비타민이 사망률을 낮춘다", "multivitamin all-cause mortality randomized trial", "beneficial"),
    ("항산화 보충제가 암을 예방한다", "antioxidant supplements cancer prevention randomized", "beneficial"),
    ("비타민E 보충이 심장병을 예방한다", "vitamin E cardiovascular events randomized trial", "beneficial"),
    ("크레아틴이 근력을 향상시킨다", "creatine supplementation muscle strength randomized", "beneficial"),
    ("식이섬유가 대장암 위험을 낮춘다", "dietary fiber colorectal cancer risk cohort", "beneficial"),
    ("계피가 공복 혈당을 낮춘다", "cinnamon fasting glucose type 2 diabetes randomized", "beneficial"),
    ("유산소 운동이 혈압을 낮춘다", "aerobic exercise blood pressure hypertension randomized", "beneficial"),
    ("콜라겐 보충이 피부 주름을 개선한다", "collagen supplementation skin wrinkles randomized trial", "beneficial"),
]


def load_seen() -> set:
    seen = set()
    for name in ("pool_labeled.jsonl", "to_label.jsonl"):
        p = os.path.join(DATA, name)
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                for ln in f:
                    if ln.strip():
                        pmid = json.loads(ln).get("pmid")
                        if pmid:
                            seen.add(pmid)
    return seen


def mine(per_claim_cap: int = 2, total: int = 18):
    api_key = os.environ.get("NCBI_API_KEY")
    seen = load_seen()
    candidates = []
    for claim, term, polarity in CLAIMS:
        cards = pubmed.search(term, retmax=10, api_key=api_key)
        picked = 0
        scored = []
        for c in cards:
            if not c.get("pmid") or c["pmid"] in seen:
                continue
            text = c.get("abstract") or c.get("summary") or ""
            if len(text) < 80:
                continue
            res = classify.classify(claim, text)
            d = sorted(res["dist"].values(), reverse=True)
            margin = d[0] - d[1]
            scored.append((margin, claim, polarity, c["pmid"], text, res))
        scored.sort(key=lambda x: x[0])  # most uncertain first
        for margin, claim, polarity, pmid, text, res in scored:
            if picked >= per_claim_cap:
                break
            candidates.append({
                "margin": round(margin, 3), "claim": claim, "polarity": polarity,
                "pmid": pmid, "text": text, "pred": res["stance"],
                "dist": {k: round(v, 3) for k, v in res["dist"].items()},
            })
            picked += 1

    candidates.sort(key=lambda x: x["margin"])
    candidates = candidates[:total]

    # Abstract bodies go to a gitignored local cache; the jsonl keeps only pmid + fingerprint.
    save_texts({c["pmid"]: c["text"] for c in candidates})
    with open(OUT, "w", encoding="utf-8") as f:
        for c in candidates:
            row = {k: c[k] for k in OUT_FIELDS if k in c}
            row["text_sha256"] = text_hash(c["text"])
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Mined {len(candidates)} items -> {OUT}\n")
    for i, c in enumerate(candidates):
        print(f"[{i}] margin={c['margin']} pred={c['pred']} pmid={c['pmid']}")
        print(f"    claim: {c['claim']}")
        print(f"    abstract: {c['text'][:300]}")
        print()


if __name__ == "__main__":
    mine()
