# stance training data — provenance and copyright

This folder contains no PubMed abstract text. Journals and publishers hold the copyright on
abstracts and NCBI grants no redistribution right, so the repo stores pmids and labels only;
each user fetches the bodies from PubMed themselves.

```bash
python rehydrate.py     # builds data/_texts.jsonl (once, about a minute)
python train.py         # then train
```

Run `train.py` without rehydrating and it will not fail quietly: it stops, lists the pmids
it could not resolve, and points back at the command above.

---

## What is in each file

| file | rows | body text | source |
|---|---|---|---|
| `seed_train.jsonl` | 41 | included | hand-written synthetic sentences |
| `gold.jsonl` | 40 | included | hand-written synthetic sentences (frozen eval set) |
| `pool_labeled.jsonl` | 50 | pmid only | PubMed abstracts |
| `to_label.jsonl` | 18 | pmid only | PubMed abstracts (active-learning queue) |
| `_texts.jsonl` | — | generated | output of `rehydrate.py`, gitignored |

### Why seed_train / gold keep their text

The `text` in these two files is not excerpted from abstracts; each is a single sentence
written from scratch for stance training. That is why they carry no pmid and no publisher
copyright applies.

This was checked, not assumed. ANDing every content word of a sentence into a PubMed `[tiab]`
search returned `count=0` for several of them. AND search is a superset of exact-phrase search,
so count=0 means no record in PubMed contains all of those words. The few sentences that did
return candidates were compared against the abstracts fetched with efetch: zero substring
matches, and not even an 8-word run in common.

Structurally they are single sentences of median length 115-125 characters, with zero instances
of multi-sentence text, 95% CIs, p-values, or abstract section headers
(BACKGROUND/METHODS/RESULTS).

### Why pool_labeled / to_label keep only pmids

Their `text`, by contrast, held complete abstracts verbatim. In the efetch comparison, 9 of 10
sampled records matched the real abstract byte for byte, down to the length (pmid `37702300`,
for one, was the full 6,260-character abstract). A lossless copy with no summarizing or
rewriting counts as redistribution.

Every row had a pmid, so the bodies could be stripped with no loss of information.
`text_sha256` is a fingerprint of the original body, used to check that a rehydrated abstract
matches what was trained on. A hash is not the text, so it is safe to commit.

---

## Does rehydration reproduce the originals? Not exactly — 5 differ

`rehydrate.py` reproduces 44 of the 49 pmids exactly; 5 come back different. The cause is not
PubMed revising the abstracts, it is our parser having improved.

When this training data was mined, `pubmed.py` read `AbstractText.text`, which truncates at the
first inline markup element such as `<sub>` or `<i>`.

```
stored:      ... for HbA        Minor differences were noted ...
rehydrated:  ... for HbA1c and high density lipoprotein ...
                     ^^^ the characters inside <sub>1c</sub> were dropped
```

The current parser uses `itertext()` and reads through markup, so it returns the more complete
body. The rehydrated text is more accurate than what was stored.

The difference was measured and does not change training results:

| | train | gold | accuracy | macro F1 |
|---|---|---|---|---|
| before migration (stored bodies) | 91 | 40 | 0.900 | 0.902 |
| after rehydration (current parser) | 91 | 40 | 0.900 | 0.902 |

The confusion matrices matched too.

Every run of `rehydrate.py` hashes the cached bodies against each row's `text_sha256` and reports
how many differ and which pmids they are, printed as
`Fingerprints: N match / N differ / N with none recorded`. The check runs even when the cache is
already complete and nothing is fetched (no network needed), so if PubMed ever does revise an
abstract, a pmid outside the known 5 shows up in that list. To refetch everything and compare,
run `python rehydrate.py --verify`.

For records whose abstract is gone (retracted, merged), `pubmed._parse` puts the title in the
abstract's place, so `rehydrate.py` rejects bodies under 80 characters to keep titles out of the
training data.

---

## Label provenance — not human experts

The stance labels in this data were not reviewed by a medical expert.

- `seed_train.jsonl`, `gold.jsonl`: written and labeled by the developer
- `pool_labeled.jsonl`: abstracts selected by active learning, labeled by an LLM teacher
  (Claude); the 18 entries of the `LABELS` dict in `commit_labels.py` are that output

So the numbers in `runs.jsonl` (macro F1 0.928 and so on) measure how closely the student
imitates the LLM teacher's verdicts, not how medically correct it is. The eval set
`gold.jsonl` is only 40 rows, so 2 of them (5%) move the metric noticeably.

This limitation is stated in the project design ([`../README.md`](../README.md)); review by a
pharmacist or EBM specialist is a planned next step.

---

## Attribution

- Abstract metadata comes from NCBI E-utilities (PubMed). This project is not affiliated with,
  endorsed by, or sponsored by NLM/NCBI.
- Without an API key the rate limit is 3 requests per second; set the `NCBI_API_KEY` environment
  variable to raise it.
- Copyright in each abstract belongs to its journal or publisher. The rehydrated `_texts.jsonl`
  is for local training only and is not for redistribution.
