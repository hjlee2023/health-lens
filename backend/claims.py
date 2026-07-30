"""
Claim detection, normalization, and curated matching.

Pipeline:
  1) has_health_content(): cheap keyword gate for whether the text is about health
  2) match_curated(): overlap with a seed DB entry's keywords pins the text to a
     curated claim (deterministic)
  3) no match, and the LLM is available -> live path via llm.extract_claim()
"""
import json
import os

from taxonomy import CLAIM_CATEGORIES

DB_FILE = os.path.join(os.path.dirname(__file__), "curated_db.json")

# Signal words for the health-content gate (KO/EN). Recall over precision.
HEALTH_SIGNALS = [
    "건강", "질병", "질환", "면역", "다이어트", "체중", "감량", "혈압", "혈당",
    "콜레스테롤", "비타민", "영양제", "보충제", "단백질", "오메가", "단식", "식단",
    "운동", "수면", "약", "복용", "부작용", "예방", "치료", "효능", "효과",
    "항산화", "염증", "장수", "노화", "대사",
    "health", "disease", "immune", "diet", "weight", "vitamin", "supplement",
    "protein", "fasting", "cholesterol", "blood pressure", "cancer", "prevent",
]


def _load_db() -> dict:
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def has_health_content(text: str) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(sig in low for sig in HEALTH_SIGNALS)


def _norm(s: str) -> str:
    return "".join(s.lower().split())


def match_curated(text: str) -> list[dict]:
    """Match curated claims. Deterministic.

    keyword_groups (preferred): [[substance synonyms], [context synonyms], ...] ->
      every group needs at least one hit. Keeps a cancer video that mentions
      vitamin C but never colds or immunity from matching the common-cold card.
    keywords (legacy): a single hit anywhere is enough.
    """
    if not text:
        return []
    low_norm = _norm(text.lower())
    db = _load_db()
    hits = []
    for claim in db["claims"]:
        groups = claim.get("keyword_groups")
        if groups:
            ok = all(any(_norm(kw) in low_norm for kw in group) for group in groups)
        else:
            ok = any(_norm(kw) in low_norm for kw in claim.get("keywords", []))
        if ok:
            hits.append(claim)
    # Keep the DB's definition order so results stay reproducible
    return hits


def category_label(code: str) -> str:
    return CLAIM_CATEGORIES.get(code, CLAIM_CATEGORIES["OTHER"])
