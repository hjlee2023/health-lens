"""
Abstract rehydration layer.

The public repo does NOT ship PubMed abstract text -- publishers hold the copyright.
data/*.jsonl carries pmid + label only; each user fetches the text from PubMed into
data/_texts.jsonl (gitignored).

  python rehydrate.py        # fetch abstracts by pmid and build the cache

Record rules:
  - if "text" is already there, keep it   (gold/seed_train = hand-written synthetic sentences)
  - otherwise look up "pmid" in the cache (pool_labeled/to_label = PubMed text)
  - if neither works, fail loudly with instructions instead of skipping silently
"""
import hashlib
import json
import os

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")
TEXTS_PATH = os.path.join(DATA, "_texts.jsonl")

_HINT = (
    "\nNo abstract cache found. For copyright reasons the repo ships pmids only.\n"
    "Fetch the texts from PubMed first (one time, about a minute):\n\n"
    "    python rehydrate.py\n"
)


def text_hash(text: str) -> str:
    """Fingerprint of an abstract, for reproducibility checks. A hash isn't the text, so it's safe to commit."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_texts() -> dict[str, str]:
    """pmid -> abstract text. Empty dict if there's no cache."""
    if not os.path.exists(TEXTS_PATH):
        return {}
    out = {}
    with open(TEXTS_PATH, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            r = json.loads(ln)
            if r.get("pmid") and r.get("text"):
                out[r["pmid"]] = r["text"]
    return out


def save_texts(mapping: dict[str, str]) -> int:
    """Merge pmid -> text into the cache. Returns the total number of entries stored."""
    merged = load_texts()
    merged.update({k: v for k, v in mapping.items() if k and v})
    os.makedirs(DATA, exist_ok=True)
    tmp = TEXTS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for pmid in sorted(merged):
            f.write(json.dumps({"pmid": pmid, "text": merged[pmid]}, ensure_ascii=False) + "\n")
    os.replace(tmp, TEXTS_PATH)
    return len(merged)


def hydrate(records: list[dict], texts: dict[str, str] | None = None) -> list[dict]:
    """Fill in abstract text on records. Does not mutate the input list.

    Existing text is kept (synthetic sentences); otherwise it's pulled from the
    cache by pmid. Raises SystemExit if anything is left unfilled -- no silent failures.
    """
    texts = load_texts() if texts is None else texts
    out, missing = [], []
    for r in records:
        if r.get("text"):
            out.append(r)
            continue
        pmid = r.get("pmid")
        body = texts.get(pmid) if pmid else None
        if not body:
            missing.append(pmid or "(no pmid)")
            continue
        out.append({**r, "text": body})

    if missing:
        head = ", ".join(missing[:8]) + (" …" if len(missing) > 8 else "")
        raise SystemExit(
            f"No abstract text for {len(missing)} record(s): {head}{_HINT}"
        )
    return out
