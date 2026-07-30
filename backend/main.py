"""
HealthLens backend (FastAPI).

POST /analyze  { videoId, transcript?, title? }
  -> detects health claims and returns supporting/opposing evidence cards
     (fixed schema, reproducible)

Run:  uvicorn main:app --reload --port 8000
"""
import os
import re
import sys
from itertools import zip_longest

# Keep printing non-ASCII from blowing up on cp949 consoles (Windows)
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

# Load backend/.env if it exists (ANTHROPIC_API_KEY etc.); skip quietly if not.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:  # noqa: BLE001
    pass

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import cache
import claims
import llm
import pubmed
import transcript
from taxonomy import (
    classify_journal_tier,
    evidence_hierarchy,
    evidence_level_obj,
    journal_tier_list,
    journal_tier_obj,
    prompts_for_category,
)

try:
    from stance import classify as stance_classify
    _STANCE_OK = stance_classify.is_available()
except Exception as _e:  # noqa: BLE001
    stance_classify = None
    _STANCE_OK = False
    print(f"[stance] 분류기 비활성: {_e}")

STANCE_CONF_MIN = 0.45  # threshold on the max probability across the 3 classes

# Pipeline version. Bump it when code, prompts, or the model change so stale cache
# entries are invalidated automatically.
PIPELINE_REV = "2026-07-08-frozen"

# Full taxonomy for the badge hover tooltip (strongest → weakest). Static, so it
# rides along on every response.
REFERENCE = {
    "evidenceLevels": evidence_hierarchy(),
    "journalTiers": journal_tier_list(),
}

app = FastAPI(title="HealthLens", version="0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev only; restrict to the extension ID before shipping
    allow_methods=["*"],
    allow_headers=["*"],
)

DISCLAIMER = (
    "이 도구는 의학적 조언이 아니라 '스스로 판단하기 위한 재료'를 정리해줍니다. "
    "근거의 방향이 갈릴 수 있으며, 개인의 상황은 다릅니다. 치료·복약 결정은 의사·약사와 상의하세요."
)

EVIDENCE_GUIDE = (
    "위쪽일수록 인과관계를 더 강하게 뒷받침하는 연구 유형입니다(메타분석 > RCT > 관찰연구 > 동물/시험관). "
    "다만 '연구 유형이 강하다'가 '이 주장이 옳다'를 뜻하진 않습니다."
)


class AnalyzeReq(BaseModel):
    videoId: str
    transcript: str | None = None
    title: str | None = None


def _authors_of(raw: dict) -> str:
    """Short author line for the card. Live results carry authors; curated ones are
    inferred from the head of the citation."""
    a = raw.get("authors")
    if a:
        return a
    head = re.split(r"\.\s", raw.get("citation", ""), 1)[0].strip()
    if not head or len(head) > 45:
        return ""
    return head.replace(", et al", " 외").replace(" et al", " 외")


def _card(raw: dict, ko_summary: str | None = None, level: str | None = None) -> dict:
    """Evidence card. summary is Korean; cite is author · journal · year (no title).

    Evidence level precedence: a specific design tag from PubMed (SR_MA, RCT, ...)
    beats the LLM's abstract-based classification (level), which beats EXPERT.
    When PubMed only says 'Journal Article' and leaves it None, the LLM fills in
    observational, preclinical, and so on."""
    tier_code = raw.get("journalTier") or classify_journal_tier(raw.get("journal", ""))
    journal = raw.get("journal", "")
    year = raw.get("year")
    cite = " · ".join(p for p in [_authors_of(raw), journal, (str(year) if year else "")] if p)
    ev_code = raw.get("evidenceLevel") or level or "EXPERT"
    return {
        "summary": ko_summary or raw.get("summary", ""),
        "evidenceLevel": evidence_level_obj(ev_code),
        "journalTier": journal_tier_obj(tier_code),
        "cite": cite,
        "url": raw.get("url", ""),
    }


def _video_evidence(c: dict) -> dict:
    """Level and journal tier of the evidence the video cites for itself, kept
    separate from the research evidence we look up."""
    lvl = c.get("videoEvidenceLevel") or "EXPERT"
    src = c.get("videoCitedSource", "") or ""
    obj = {
        "level": evidence_level_obj(lvl),
        "note": c.get("videoEvidenceNote", ""),
        "citedSource": src,
    }
    if src:
        tier = classify_journal_tier(src)
        if tier in ("T1", "T2", "T3"):   # show a tier when it looks like a journal
            obj["journalTier"] = journal_tier_obj(tier)
    return obj


def _curated_claim(entry: dict, c: dict | None = None, transcript_ok: bool = True) -> dict:
    c = c or {}
    return {
        "id": entry["id"],
        "statement": c.get("statement") or entry["statement"],
        "videoStance": c.get("videoStance", "ASSERTS") if transcript_ok else "UNKNOWN",
        "rationale": c.get("rationale", "") if transcript_ok else "",
        "videoEvidence": _video_evidence(c) if (c and transcript_ok) else None,
        "transcriptMissing": not transcript_ok,
        "category": entry["category"],
        "categoryLabel": claims.category_label(entry["category"]),
        "source": "curated",
        "supporting": [_card(x) for x in entry.get("supporting", [])],
        "opposing": [_card(x) for x in entry.get("opposing", [])],
        "thinkingPrompts": prompts_for_category(entry["category"]),
        "evidenceGuide": EVIDENCE_GUIDE,
    }


def _live_claim(c: dict, transcript_ok: bool = True) -> dict:
    """Live path: search -> LLM judging (stance + Korean summary), falling back to
    the trained classifier."""
    term = c.get("searchTerm") or c.get("searchTermSupport") or c["statement"]
    ncbi = os.environ.get("NCBI_API_KEY")
    # Interleave a general search (observational work, usually positively biased)
    # with an RCT search (far more null and negative results) to keep the mix
    # balanced. The RCT terms are ANDed on, so we stay on topic while still
    # picking up opposing evidence.
    gen = pubmed.search(term, retmax=10, api_key=ncbi)
    rct = pubmed.search(f"{term} randomized controlled trial", retmax=8, api_key=ncbi)
    seen, merged = set(), []
    for a, b in zip_longest(gen, rct):
        for x in (a, b):
            if x and x.get("pmid") and x["pmid"] not in seen:
                seen.add(x["pmid"])
                merged.append(x)
    statement = c["statement"]
    cand = [x for x in merged if len(x.get("abstract") or x.get("summary") or "") >= 60][:12]
    support, oppose = [], []

    judged = llm.judge_evidence(statement, [(x.get("abstract") or x.get("summary") or "") for x in cand])
    if judged:  # LLM judging: accurate, Korean summary, design read off the abstract
        for x, j in zip(cand, judged):
            if j["stance"] == "SUPPORT" and len(support) < 3:
                support.append(_card(x, j["ko"], j.get("level")))
            elif j["stance"] == "OPPOSE" and len(oppose) < 3:
                oppose.append(_card(x, j["ko"], j.get("level")))
    elif _STANCE_OK:  # fallback: trained classifier (English summary)
        scored = [(x, stance_classify.classify(statement, x.get("abstract") or x.get("summary") or ""))
                  for x in cand]
        scored.sort(key=lambda sr: sr[1]["confidence"], reverse=True)
        for x, res in scored:
            if res["confidence"] < STANCE_CONF_MIN:
                continue
            if res["stance"] == "SUPPORT" and len(support) < 3:
                support.append(_card(x))
            elif res["stance"] == "OPPOSE" and len(oppose) < 3:
                oppose.append(_card(x))
    else:
        support = [_card(x) for x in cand[:3]]

    return {
        "id": cache.claim_key(statement),
        "statement": statement,
        "videoStance": c.get("videoStance", "ASSERTS") if transcript_ok else "UNKNOWN",
        "rationale": c.get("rationale", "") if transcript_ok else "",
        "videoEvidence": _video_evidence(c) if transcript_ok else None,
        "transcriptMissing": not transcript_ok,
        "category": c.get("category", "OTHER"),
        "categoryLabel": claims.category_label(c.get("category", "OTHER")),
        "source": "live",
        "supporting": support,
        "opposing": oppose,
        "thinkingPrompts": prompts_for_category(c.get("category", "OTHER")),
        "evidenceGuide": EVIDENCE_GUIDE,
    }


@app.get("/health")
def health():
    return {"ok": True, "rev": "llm-first-v2", "stanceModel": _STANCE_OK, "llm": llm.status()}


@app.post("/analyze")
def analyze(req: AnalyzeReq, fresh: bool = False):
    cache_key = f"{PIPELINE_REV}:{llm.OLLAMA_MODEL}:video:{req.videoId}"
    if not fresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    # Transcript: use what the extension sent if it's long enough, else fetch it
    # server-side (works well locally, where we go out on a residential IP).
    provided = (req.transcript or "").strip()
    text = provided if len(provided) >= 80 else (transcript.fetch(req.videoId) or provided)
    # Do we actually have a transcript? Without one we won't invent the video's
    # reasoning from the title alone.
    transcript_ok = len(text) >= 80
    haystack = f"{req.title or ''} {text}"

    resp = {
        "videoId": req.videoId,
        "analyzedAt": datetime.now(timezone.utc).isoformat(),
        "hasHealthClaim": False,
        "claims": [],
        "disclaimer": DISCLAIMER,
        "reference": REFERENCE,
    }

    if not claims.has_health_content(haystack):
        cache.put(cache_key, resp)
        return resp

    # 1) Extract the actual claims with the LLM first, then match curated entries
    #    against those normalized statements. Keyword-matching the whole transcript
    #    would let a cancer video hit the common-cold card just for saying
    #    "immunity", so we match on the extracted statements only.
    extracted = llm.extract_claims(haystack)
    print(f"[analyze] {req.videoId} transcriptChars={len(text)} "
          f"extracted={bool(extracted and extracted.get('claims'))}")
    if extracted and extracted.get("hasHealthClaim") and extracted.get("claims"):
        out, seen = [], set()
        for c in extracted["claims"][:2]:
            matched = claims.match_curated(c["statement"])  # statement-level, precise
            if matched:
                if matched[0]["id"] in seen:      # never emit the same card twice
                    continue
                seen.add(matched[0]["id"])
                out.append(_curated_claim(matched[0], c, transcript_ok))
            else:
                out.append(_live_claim(c, transcript_ok))
        resp["hasHealthClaim"] = True
        resp["claims"] = out
        cache.put(cache_key, resp)
        return resp

    # 2) Keyword fallback over title + transcript, but only when the LLM is fully
    #    down. If the LLM is up and extraction merely came back empty we skip this,
    #    to avoid coincidental transcript matches.
    if not llm.status().get("available"):
        curated = claims.match_curated(haystack)
        if curated:
            resp["hasHealthClaim"] = True
            resp["claims"] = [_curated_claim(e) for e in curated]
            cache.put(cache_key, resp)
            return resp

    # 3) Failure: name the cause and attach diagnostics. Failures aren't cached, so
    #    the next request retries.
    st = llm.status()
    resp["hasHealthClaim"] = True
    if not st.get("available"):
        resp["note"] = (f"실시간 분석 엔진(LLM: {st.get('backend')})에 연결하지 못했습니다. "
                        f"로컬 모델이 켜져 있는지 확인하세요.")
    elif len(text) < 80:
        resp["note"] = ("자막을 가져오지 못해 제목만으로는 주장을 정리하지 못했습니다. "
                        "자막(CC)이 있는 영상에서 더 잘 동작합니다.")
    else:
        resp["note"] = "건강 관련 내용이 감지됐지만, 아직 정규화된 주장으로 정리하지 못했습니다."
    resp["debug"] = {"transcriptChars": len(text), "titleChars": len(req.title or ""), "llm": st}
    return resp  # deliberately not cached
