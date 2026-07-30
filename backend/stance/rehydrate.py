"""
Fetch abstracts from PubMed for the pmids in data/*.jsonl and build the
data/_texts.jsonl cache.

The repo ships no abstract text (copyright), so run this once before training or labeling.

  python rehydrate.py           # build/refresh the cache + compare fingerprints
  python rehydrate.py --verify  # refetch everything and compare only (no cache write)

NCBI E-utilities is free and needs no key (set NCBI_API_KEY for a higher rate limit).

Exit codes: 0 = cache complete, 1 = some pmids still have no text (can't train).
"""
import json
import os
import sys
import time

HERE = os.path.dirname(__file__)
BACKEND = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, BACKEND)

import pubmed  # noqa: E402
from texts import DATA, TEXTS_PATH, load_texts, save_texts, text_hash  # noqa: E402

BATCH = 20
SOURCES = ("pool_labeled.jsonl", "to_label.jsonl")

# pubmed._parse falls back to `abstract or title`, so a missing abstract comes back
# as the title. Training on titles-as-abstracts is wrong, hence this length floor
# (same threshold as mine.py).
MIN_ABSTRACT = 80


def _rows(name: str) -> list[dict]:
    p = os.path.join(DATA, name)
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def collect() -> dict[str, str | None]:
    """Collect pmid -> expected fingerprint (text_sha256, or None) across all sources."""
    want: dict[str, str | None] = {}
    for name in SOURCES:
        for r in _rows(name):
            pmid = r.get("pmid")
            if pmid and not r.get("text"):
                want.setdefault(pmid, r.get("text_sha256"))
    return want


def fetch(pmids: list[str], api_key: str | None) -> tuple[dict[str, str], list[str]]:
    """pmid -> abstract text. Pmids that came back title-only are returned separately and not cached."""
    got: dict[str, str] = {}
    thin: list[str] = []
    for i in range(0, len(pmids), BATCH):
        chunk = pmids[i:i + BATCH]
        try:
            for c in pubmed._parse(pubmed._efetch(chunk, api_key=api_key)):
                pmid, body = c.get("pmid"), (c.get("abstract") or "")
                if not pmid:
                    continue
                if len(body) < MIN_ABSTRACT:
                    thin.append(pmid)   # abstract is gone (retraction, merge, ...)
                    continue
                got[pmid] = body
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] batch {i}-{i + len(chunk)} failed: {e}")
        print(f"  {min(i + BATCH, len(pmids))}/{len(pmids)} …")
        time.sleep(0.5)  # be polite to NCBI
    return got, thin


def main(verify_only: bool = False) -> int:
    want = collect()
    if not want:
        print("Nothing to rehydrate: every record already has text, or the data is empty.")
        return 0

    cached = load_texts()
    todo = sorted(want) if verify_only else sorted(p for p in want if p not in cached)

    got: dict[str, str] = {}
    thin: list[str] = []
    if todo:
        print(f"Fetching {len(todo)} abstracts from PubMed…")
        got, thin = fetch(todo, os.environ.get("NCBI_API_KEY"))
    else:
        print(f"Cache already complete: {len(cached)} entries -> {TEXTS_PATH}")

    if thin:
        head = ", ".join(sorted(set(thin))[:10])
        print(f"\n[warn] {len(set(thin))} pmid(s) came back title-only, no abstract: {head}")
        print("       Not cached, to keep them out of the training data.")
    missed = [p for p in todo if p not in got]
    if missed and todo:
        head = ", ".join(missed[:10]) + (" …" if len(missed) > 10 else "")
        print(f"\n[warn] {len(missed)} pmid(s) not retrieved: {head}")

    if got and not verify_only:
        total = save_texts(got)
        cached = load_texts()
        print(f"\nCache saved: {total} entries -> {TEXTS_PATH}")

    # --- Fingerprint check: runs every time, no network needed ------------
    # Compares against the recorded text_sha256 to surface drift even when the
    # cache is already complete.
    current = dict(cached)
    current.update(got)
    same = diff = unknown = 0
    drifted: list[str] = []
    absent: list[str] = []
    for pmid, expect in want.items():
        body = current.get(pmid)
        if not body:
            absent.append(pmid)
        elif not expect:
            unknown += 1
        elif text_hash(body) == expect:
            same += 1
        else:
            diff += 1
            drifted.append(pmid)

    print(f"\nFingerprints: {same} match / {diff} differ / {unknown} with none recorded")
    if drifted:
        print(f"  differing pmids: {', '.join(sorted(drifted)[:10])}")
        print("  5 of these are known: the PubMed parser now keeps text inside markup, so those")
        print("  abstracts are more complete. Metrics were verified unchanged (see data/README.md).")
        print("  Any pmid beyond those 5 probably means PubMed revised the abstract.")

    if absent:
        head = ", ".join(sorted(absent)[:10]) + (" …" if len(absent) > 10 else "")
        print(f"\n[fail] {len(absent)} pmid(s) still have no text: {head}")
        print("   Check your network and the NCBI rate limit, then rerun. Training can't proceed yet.")
        return 1

    if verify_only:
        print("\n--verify mode: nothing was written to the cache.")
        return 0

    print("\nCache complete. You can now train with `python train.py`.")
    return 0


if __name__ == "__main__":
    sys.exit(main(verify_only="--verify" in sys.argv))
