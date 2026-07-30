# Stance classifier — support vs. oppose, closed-loop self-training

A deterministic classifier that decides, on the live path, whether a PubMed abstract
supports (SUPPORT), refutes (OPPOSE), or is merely background/irrelevant (NEUTRAL) to a claim.

## Why this design
"Learning from nothing" is impossible without a label signal. What actually closes the loop
here is teacher-to-student distillation plus active learning.

1. **seed**: a small set of training sentences written and labeled by hand into
   `data/seed_train.jsonl`. These labels were not reviewed by a medical expert; see
   `data/README.md` for provenance.
2. **frozen eval set**: `data/gold.jsonl`, never trained on. It is the only honest yardstick.
3. **student**: TF-IDF plus hand-built cue features into a scikit-learn logistic regression.
   Training freezes the model into `model.joblib`, so the same input always gives the same output.
4. **the loop (one round)**:
   - `mine.py` pulls unlabeled abstracts from PubMed live and keeps the ones the model is least
     sure about (smallest top1-top2 probability margin) in `data/to_label.jsonl`.
   - A teacher labels them: `teacher.py` (Claude, needs an API key) unattended, or
     `commit_labels.py` by hand.
   - Labels accumulate in `data/pool_labeled.jsonl` → `train.py` retrains → re-evaluate on gold.
5. **guardrail**: the loop only means something if the teacher sees more than the student's cue
   features: the whole abstract and the numbers. gold never leaks into training.

## Evolution log (measured; gold = frozen eval set)
| round | train | gold | accuracy | macro F1 | notes |
|------|-------|-----|-------|---------|------|
| r0 | 41 | 24 | 0.833 | 0.799 | baseline |
| r1 | 55 | 24 | 0.833 | 0.799 | data only, no change (the lesson) |
| r2 | 55 | 24 | 0.875 | 0.878 | added NEUTRAL cue features |
| — | 55 | 40 | 0.900 | 0.905 | gold 24 → 40, more reliable measurement |
| r3 | 73 | 40 | 0.925 | 0.928 | 18 Fable teacher labels, OPPOSE recall up (deployed) |
| r4 | 91 | 40 | 0.900 | 0.902 | SUPPORT-heavy batch, slight drop (not deployed) |

Two lessons:
1. Pouring in more data is not enough (r1). The weaknesses active learning exposed —
   off-topic abstracts, guidelines, observational studies read as trials — had to be fixed
   in the feature design (r2).
2. Not every round improves (r4). A mining batch skewed toward one class can drag gold down.
   Hence (a) only the best-on-gold checkpoint is deployed (train.py, `best.json`) and (b) an
   early-stop guard in auto_loop. The r4 data is kept and gets reused once gold grows.

gold = 40 is still small: 2 items are 5% of it, so single examples are noise. Expanding gold
is the next step.

Where the labels come from: the numbers above measure how well the student imitates the LLM
teacher's verdicts, not how medically correct it is. The r3 and r4 training labels were
assigned by Claude (`commit_labels.py`).

## Reproducibility — the deployed model cannot be rebuilt from the current data
`model.joblib` is the r3 checkpoint (73 training rows, macro F1 0.9282), but the data in the
repo is now 91 rows, so running `train.py` produces r4 (0.9024). The pool snapshot at 73 rows
is not in the repo. `train.py` only replaces the deployed model on a new best gold score, so
`model.joblib` will not be overwritten, but the advertised 0.9282 does not reproduce from a
clean clone.

## Running it
### 0) Rehydrate the abstracts (once, required)
The repo ships pmids only, no abstract text (copyright).
```bash
cd backend/stance
python rehydrate.py            # fetch abstracts from PubMed → data/_texts.jsonl (about a minute)
```
Skip it and `train.py` will not fail quietly: it stops and lists the pmids it could not find
(`No abstract text for N record(s): ...`). Details in [`data/README.md`](data/README.md).

### 1) One round with a human labeler
```bash
cd backend/stance
python train.py --round r0     # train + eval on gold + deploy the best checkpoint
python mine.py                 # mine uncertain examples from PubMed live → to_label.jsonl
# read to_label.jsonl, fill in LABELS (pmid → stance) in commit_labels.py, then:
python commit_labels.py        # commit to pool_labeled.jsonl
python train.py --round r1     # retrain (deploys only on a new best)
```
### 2) Unattended loop (LLM teacher, API key required)
```bash
ANTHROPIC_API_KEY=... python auto_loop.py --rounds 5 --batch 18
```
Repeats mine → teacher → train for N rounds, stopping early when macro F1 plateaus.
Per-round metrics go to `runs.jsonl`; the deployed model is `model.joblib` (per `best.json`).

> Cost warning. The default teacher model (`HEALTHLENS_TEACHER_MODEL`) is an expensive one,
> and there is no per-round token or spend cap and no dry-run guard. Early stopping keys off
> macro F1, so it is unrelated to cost. Each item sends 1,500 characters of abstract, batched.
> Try something small like `--rounds 1 --batch 4` first, and drop to a cheaper model if needed.
