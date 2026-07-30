# HealthLens

A Chrome extension that pulls the central health claim out of a YouTube video and lays out
the evidence for it next to the evidence against it, with equal weight given to both sides.

It deliberately does not produce a verdict or a confidence score. Instead it shows what kind
of study each piece of evidence comes from (meta-analysis, RCT, cohort, and so on), what tier
the journal sits in, and a few questions worth asking before you believe the video.

The interface and all generated summaries are in Korean, since the tool targets Korean-language
health content on YouTube.

Four rules the code is built around, and which should not be relaxed:

- No numeric confidence field. Ever.
- Supporting and opposing evidence share one schema and one visual weight.
- Offer questions, not conclusions.
- The same video always produces the same cards.

## Medical disclaimer

This is not medical advice. It is not a diagnostic device, and it does not replace a
consultation with a physician or a pharmacist.

Most of the evidence summaries are written by a small local language model (8B parameters).
It mistranslates, overstates, and drops qualifiers. The PubMed search only skims the top
relevance hits and each side is truncated to three cards, so what you see is a sample, not a
systematic review. The seed database in `backend/curated_db.json` has not been reviewed by a
clinician yet — `_meta.reviewed_by` is still `null`, and expert review is a planned next step.

Talk to a doctor or pharmacist before making any treatment or medication decision.

## Requirements

| | |
|---|---|
| Python | 3.10 or newer (the code uses PEP 604 `str \| None`; developed on 3.14.5) |
| Chrome | any version with MV3 support |
| Disk | 5–10 GB for the model, roughly 500 MB for packages |
| GPU | optional, but it is very slow without one |

The local model handles the live path, where a video has no match in the seed database:

| Model | Size | VRAM | |
|---|---|---|---|
| `qwen3:8b` | 5.2 GB | 8 GB | Recommended. Fits in 8 GB. |
| `qwen3:14b` | 9.3 GB | 12 GB+ | The code default when no `.env` exists. On 8 GB it spills to CPU and becomes unusably slow. |
| `qwen2.5:7b` | 4.7 GB | 8 GB | Faster, somewhat lower quality. |

Measured on an RTX 4060 (8 GB) with `qwen3:8b`: about 100 seconds for a short transcript,
longer for a full video. A repeat request for the same video is served from cache in 0.2 seconds.

## Setup

### Local LLM

```bash
winget install Ollama.Ollama
ollama pull qwen3:8b
```

Ollama needs to be serving on `localhost:11434`. If it is not running, `start_backend.bat`
will start it for you.

### Backend

```bash
cd health-lens/backend
python -m venv .venv
```

Activate it — `.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on macOS and Linux.

```bash
pip install -r requirements.txt
```

Create the `.env` file. Without it the code falls back to `qwen3:14b`, which will not match
the model you just pulled, and the live path dies entirely.

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

You are still in `health-lens/backend` from the step above. Make sure
`HEALTHLENS_OLLAMA_MODEL` in `.env` names the model you actually pulled.

```bash
uvicorn main:app --reload --port 8000
```

Port 8000 is effectively fixed. The extension hardcodes the backend URL in
`extension/content.js`, and `manifest.json` only grants `host_permissions` for
`http://localhost:8000/*`. Changing the port means editing both.

On Windows, `start_backend.bat` does all of this in one step: it starts Ollama if port 11434
is closed, waits up to 30 seconds for it, then launches the backend. Two things to know about
it. It kills whatever is listening on port 8000 with `taskkill /F`, including processes that
have nothing to do with HealthLens, and it runs uvicorn without `--reload`. The file also has
to stay CRLF-terminated; with LF-only line endings the cmd parser mangles it and you get
errors about commands like `'okens'`.

### Chrome extension

1. Go to `chrome://extensions` and turn on developer mode.
2. Choose "Load unpacked" and select the `health-lens/extension` folder.
3. Open a Korean health video on YouTube. The panel appears in the top right.

### Check that it works

```bash
curl http://localhost:8000/health
```

`llm.available` should be `true` and `llm.model` should match the model you pulled.

## Environment variables

These go in `backend/.env`. All of them are optional, but as noted above the model name has
to line up with what Ollama actually has.

| Variable | Default without `.env` | |
|---|---|---|
| `HEALTHLENS_LLM_BACKEND` | `ollama` | `ollama`, `anthropic`, or `none` |
| `HEALTHLENS_OLLAMA_MODEL` | `qwen3:14b` | Local model. `.env.example` sets `qwen3:8b`. |
| `OLLAMA_URL` | `http://localhost:11434` | |
| `HEALTHLENS_MODEL` | `claude-haiku-4-5` | Used only with the `anthropic` backend |
| `ANTHROPIC_API_KEY` | none | Required for the `anthropic` backend |
| `NCBI_API_KEY` | none | Raises the PubMed rate limit above 3 requests/second |
| `HEALTHLENS_TEACHER_MODEL` | `claude-fable-5` | Teacher for the stance loop. See the cost note below. |
| `HEALTHLENS_VERIFIER_MODEL` | `qwen3:8b` | Grader used by `eval_quality.py` |

Setting `HEALTHLENS_LLM_BACKEND=none` disables the live path and runs on the seed database alone.

## Layout

```
health-lens/
├─ LICENSE
├─ start_backend.bat            Windows launcher (starts Ollama, frees port 8000)
├─ docs/
│  ├─ evidence-standard.md      Evidence classification standard (awaiting expert review)
│  └─ sample_analyze_response.json   Example /analyze response (fictional video)
├─ backend/                     FastAPI
│  ├─ main.py            API (/analyze, /health)
│  ├─ taxonomy.py        Evidence levels, journal tiers, categories, prompts
│  ├─ curated_db.json    Seed database (3 claims, awaiting expert review)
│  ├─ claims.py          Health gate and seed matching
│  ├─ pubmed.py          PubMed search via NCBI E-utilities
│  ├─ llm.py             Claim extraction and evidence judging
│  ├─ transcript.py      Server-side transcript fallback
│  ├─ cache.py           Per-video response cache
│  ├─ eval_quality.py    Evidence quality regression harness
│  ├─ requirements.txt
│  ├─ .env.example
│  └─ stance/            Support/oppose classifier and active-learning loop
└─ extension/            Chrome MV3 extension (content script, shadow DOM panel)
```

Running the project generates `backend/cache_store.json`,
`backend/stance/data/_texts.jsonl`, `backend/stance/model_latest.joblib` and `__pycache__/`.
All four are gitignored.

## How it works

A request goes through three stages. First a gate checks whether the title and transcript
contain anything health-related. Then the LLM extracts the claim, and only that normalized
claim sentence is matched against the seed database — matching the raw transcript by keyword
made a cancer video trip the common-cold card just because it mentioned immunity. If nothing
matches, the backend searches PubMed and sorts each abstract into supporting or opposing.

That last sort has three tiers, and the order matters:

```
llm.judge_evidence()      primary; reads the abstract, returns stance and a Korean summary
      |  LLM off or failed
trained stance classifier fallback; English summary
      |  neither available
unclassified search hits  the symmetry guarantee breaks here — see Known limitations
```

The classifier under `stance/` is the fallback, not the primary path.

### Transcripts

The extension tries several routes in order, and some of them use YouTube's private API.

1. Parse `ytInitialPlayerResponse` → `captionTracks` from the page.
2. If that fails, scrape `INNERTUBE_API_KEY` out of the page and call the undocumented
   `/youtubei/v1/player` endpoint directly, with `credentials: "include"` so the request
   carries the user's YouTube login cookies.
3. If that also fails, re-fetch `/watch?v=` and parse the HTML, then fall back to reading the
   caption panel out of the DOM.
4. If the extension hands the backend fewer than 80 characters, the server tries
   `youtube-transcript-api` on its own.

Step 2 hits an endpoint YouTube does not document. It may violate YouTube's terms of service
and it can break without warning. Step 4 goes out over the server's IP, so a datacenter
deployment will get blocked; even locally it can fail on rate limits.

When no transcript can be had, the tool does not invent the video's reasoning from the title.
It sets `transcriptMissing` and shows only topic-level evidence.

## API

`GET /health`

```json
{"ok": true, "rev": "llm-first-v2", "stanceModel": true,
 "llm": {"backend": "ollama", "available": true, "model": "qwen3:8b",
         "installed_models": ["qwen3:8b", "..."]}}
```

`POST /analyze`

```bash
curl -X POST "http://localhost:8000/analyze" \
  -H "Content-Type: application/json" \
  -d "{\"videoId\":\"demo\",\"title\":\"간헐적 단식으로 살 빼는 법\"}"
```

| Field | | |
|---|---|---|
| `videoId` | required | Also used as the cache key |
| `transcript` | optional | Collected by the extension; under 80 characters the server tries on its own |
| `title` | optional | |

Add `?fresh=true` to bypass the cache. The cache key is
`{PIPELINE_REV}:{llm.OLLAMA_MODEL}:video:{videoId}`, so bumping the pipeline revision or
changing `HEALTHLENS_OLLAMA_MODEL` invalidates it automatically.

The model name in that key is always `OLLAMA_MODEL`, whatever backend is active. Switching
`HEALTHLENS_LLM_BACKEND` between ollama and anthropic, or changing `HEALTHLENS_MODEL`, does
not invalidate anything — you will keep getting results produced by the previous backend
until you pass `?fresh=true`.

The response carries `hasHealthClaim`, `claims[]` (each with `statement`, `videoStance`,
`rationale`, `videoEvidence`, `supporting[]`, `opposing[]`, `thinkingPrompts`), `disclaimer`
and `reference`. There is a full example in
[`docs/sample_analyze_response.json`](docs/sample_analyze_response.json).

The curl above will not necessarily return a seed-database card. With the LLM running, the
extracted claim may route to a live PubMed card instead. Only with
`HEALTHLENS_LLM_BACKEND=none` does keyword matching reliably produce the seed card.

## Stance classifier and training data

A small supporting classifier for the support/oppose decision. The design and the
active-learning loop are described in [`backend/stance/README.md`](backend/stance/README.md).

The repository does not contain PubMed abstract text. Copyright on abstracts belongs to the
individual publishers, so only the pmid is stored and you fetch the bodies yourself.

```bash
cd backend/stance
python rehydrate.py     # fetch abstracts into data/_texts.jsonl, about a minute, once
python train.py         # train and evaluate against gold
```

Running `train.py` without rehydrating first does not fail silently; it stops and tells you
what to do. Provenance, copyright and label sourcing are documented in
[`backend/stance/data/README.md`](backend/stance/data/README.md).

### On reproducibility

The shipped `model.joblib` is a checkpoint from when the training set had 73 rows, scoring
0.9282 macro F1. The repository now carries 91 rows, so `train.py` produces 0.9024 and the
advertised 0.9282 cannot be reproduced — the 73-row snapshot is not in the repository.
Since `train.py` only replaces the deployed model when gold performance meets or beats the
previous best, `model.joblib` is never overwritten by that lower score.

### Evaluation harness

```bash
cd backend && python eval_quality.py
```

Runs search, judging and LLM grading over eight claims. The automated grader misjudges
accurate summaries often enough that its scores are indicative only; the real quality signal
has always been reading the output by hand.

## Security: this is a local-only tool

Do not expose the backend.

CORS is wide open with `allow_origins=["*"]`, there is no authentication and no rate limiting;
the code comment says as much. The consequence is that any website the user visits can call
`fetch('http://localhost:8000/health')` and read back the list of Ollama models installed on
their machine. `/analyze` returns cached results as-is, which turns it into an oracle: a
malicious page can guess videoIds and learn which ones this user has analyzed.

Deploying this anywhere real means restricting CORS to the extension ID and adding auth.

### The model file is a pickle

`backend/stance/model.joblib` is loaded with `joblib.load()`, and pickle deserialization can
execute arbitrary code. Do not drop a `.joblib` from an untrusted source into that folder.

Rebuilding it yourself takes one more step than you would expect. `train.py` only writes
`model.joblib` when gold performance meets the record in `best.json` (0.9282), and the current
data scores 0.9024, so the output lands in `model_latest.joblib` instead. To actually rebuild:

```bash
python rehydrate.py
rm best.json          # drops the reference checkpoint; the deployed model becomes 0.9024
python train.py --round rebuild
```

Copying `model_latest.joblib` over `model.joblib` works too.

### Cost of the training loop

The default teacher model in `auto_loop.py` is `claude-fable-5`, which is expensive, and there
is no per-round token or cost ceiling and no dry-run guard. Point
`HEALTHLENS_TEACHER_MODEL` at something cheaper or keep `--rounds` small before you run it.

## Where your data goes

The extension runs automatically on every YouTube `/watch` page; there is no opt-in toggle.
It sends the full transcript, the title and the videoId to `http://localhost:8000`. On the
default backend (`HEALTHLENS_LLM_BACKEND=ollama`) the transcript never leaves the machine,
because the model is local. Switch to `HEALTHLENS_LLM_BACKEND=anthropic` and the transcript
body is sent to the Anthropic API.

Collecting the transcript uses the user's YouTube login cookies against YouTube's own API.
Analysis results are stored in plaintext in `backend/cache_store.json` and kept indefinitely;
delete that file to clear them and it will be recreated. PubMed search terms go to NCBI.

## Known limitations

1. When neither judging path is available the symmetry breaks. The top three search hits all
   land in supporting and opposing is left empty, but the UI still says no notable opposing
   evidence was found — when in fact nothing was ever judged.
2. The 8B local model does not fully digest long transcripts, and detail-level errors persist,
   including confusing one disease for another. The judging is unstable enough that the code
   corrects it after the fact with regexes.
3. The predatory-journal warning never fires. `taxonomy.py` defines a T4 tier for suspected
   predatory journals, but `classify_journal_tier()` has no branch that returns it, so an
   unrecognized journal is presented as T3, "ordinary peer-reviewed".
4. The evaluation set is 40 rows. Two of them, 5%, move the number visibly. The labels were
   also assigned by an LLM, so the score measures agreement with an LLM teacher, not medical
   accuracy.
5. The standard and the code have drifted apart. `docs/evidence-standard.md` and `taxonomy.py`
   disagree on the EXPERT/PRECLINICAL ordering, on the number of levels (7 versus 8), and on
   the fields a card emits.
6. Seed-database cards carry no source badge. They have not been reviewed by a clinician, so
   no review label is attached. Only live search results are labeled.

## Planned

- Clinical review of `curated_db.json` and `evidence-standard.md` by a pharmacist and an EBM specialist
- Implement the T4 branch so the predatory-journal tier can actually be returned
- Fill in `_meta.reviewed_by` once review happens, and only then display a review label
- Flag degraded responses when the symmetry guarantee cannot be met
- Grow the stance gold set and introduce human labels
- Speech-to-text for videos without captions, and a review queue UI

## License

[MIT](LICENSE), covering the source code only. It does not extend to third-party material:
PubMed abstracts, YouTube videos and captions, or the text of any cited paper.

This project is not affiliated with, endorsed by, or connected to NLM/NCBI or YouTube.
