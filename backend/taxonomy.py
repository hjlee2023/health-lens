"""
HealthLens fixed classification constants.

Kept in 1:1 sync with docs/evidence-standard.md.
The code values here are cache/DB keys, so don't change them. (Labels and
descriptions are free to improve.)
"""

# =============================================================================
# §1. Evidence level hierarchy (rank is ordering only, not a score)
#     Bottom = personal anecdote, one step above = expert opinion.
#     why = the "why is it ranked here" explainer shown in the badge tooltip.
# =============================================================================
EVIDENCE_LEVELS = {
    "SR_MA":        {"rank": 1, "label": "체계적 문헌고찰 / 메타분석", "desc": "여러 연구를 체계적으로 종합",
                     "why": "같은 질문의 여러 연구를 체계적으로 모아 통합합니다. 개별 연구의 우연·치우침이 상쇄돼 현재 가장 신뢰도 높은 근거입니다(단, 재료가 된 연구들이 부실하면 결론도 부실합니다)."},
    "RCT":          {"rank": 2, "label": "무작위 대조 시험",          "desc": "무작위 배정 + 대조군",
                     "why": "참가자를 무작위로 나눠 한쪽만 개입하고 비교합니다. 두 집단이 비슷해져 '이 물질 때문'이라는 인과를 가장 깔끔하게 규명합니다."},
    "COHORT":       {"rank": 3, "label": "코호트(관찰) 연구",         "desc": "노출군을 추적하는 관찰연구",
                     "why": "집단을 추적 관찰합니다. 개입하지 않으니 '함께 나타남(상관)'은 보여줘도 '원인'은 단정하기 어렵습니다. 숨은 요인(교란)에 주의하세요."},
    "CASE_CONTROL": {"rank": 4, "label": "환자-대조군 연구",          "desc": "결과 기준으로 과거 노출 비교",
                     "why": "병에 걸린 사람과 안 걸린 사람의 과거 노출을 거꾸로 비교합니다. 기억에 의존하는 부분이 있어 회상 편향이 끼기 쉽습니다."},
    "CROSS_CASE":   {"rank": 5, "label": "단면연구 / 증례",           "desc": "단면조사 또는 증례 보고",
                     "why": "한 시점에 조사하거나 소수 사례를 보고합니다. 시간 순서가 불명확하고 일반화하기 어렵습니다."},
    "PRECLINICAL":  {"rank": 6, "label": "동물 / 시험관 연구",        "desc": "비인간 in vivo / in vitro",
                     "why": "세포·동물에서의 결과입니다. 기전을 이해하는 출발점이지만 사람에게 같은 효과가 보장되지 않습니다(동물 성공→사람 실패가 흔합니다)."},
    "EXPERT":       {"rank": 7, "label": "전문가 의견 / 기전 추론",   "desc": "리뷰·사설·기전 기반 추정",
                     "why": "검증 데이터가 아니라 전문가의 해석·'원리상 될 것'이라는 추론입니다. 권위가 있어도 실험으로 확인된 게 아니라 틀릴 수 있습니다(유튜브 건강영상 대부분이 여기입니다)."},
    "ANECDOTE":     {"rank": 8, "label": "개인적 경험 / 후기",        "desc": "개인의 체험·간증",
                     "why": "\"나는 이걸로 나았다\"는 이야기입니다. 정말 그 물질 덕인지, 저절로 나았는지(자연경과), 믿어서 그런지(플라시보) 구분할 수 없습니다. 생생하지만 가장 약한 근거입니다."},
}

# PubMed publication type -> evidence level code (used on the live fallback path).
# Careful: PubMed tags a lot of papers with only 'Journal Article' and never labels
# the design (cohort, animal, ...), so pubtype alone misses observational and
# preclinical work and leaks it into EXPERT.
# -> On the live path llm.judge_evidence reads the abstract, classifies the design,
# and overrides this value (see main._card).
PUBTYPE_TO_LEVEL = {
    "Meta-Analysis": "SR_MA",
    "Systematic Review": "SR_MA",
    "Randomized Controlled Trial": "RCT",
    "Controlled Clinical Trial": "RCT",
    "Clinical Trial": "RCT",
    "Clinical Trial, Phase I": "RCT",
    "Clinical Trial, Phase II": "RCT",
    "Clinical Trial, Phase III": "RCT",
    "Clinical Trial, Phase IV": "RCT",
    "Pragmatic Clinical Trial": "RCT",
    "Observational Study": "COHORT",
    "Comparative Study": "COHORT",
    "Case Reports": "CROSS_CASE",
    "Review": "EXPERT",
    "Editorial": "EXPERT",
    "Comment": "EXPERT",
    "Letter": "EXPERT",
    "Guideline": "EXPERT",
    "Practice Guideline": "EXPERT",
}

# =============================================================================
# §2. Journal credibility tiers
#     A tier says how strict the review was, not that the paper is right.
#     why = the explainer shown in the badge tooltip.
# =============================================================================
JOURNAL_TIERS = {
    "T1": {"label": "최상위", "desc": "주요 종합의학지 / Cochrane / 분야 Q1 상위",
           "why": "NEJM·Lancet·JAMA·BMJ 같은 주요 종합의학지입니다. 심사가 매우 엄격해 실리기 어렵습니다. 다만 '실렸다'가 '결론이 참이다'를 보장하진 않습니다."},
    "T2": {"label": "상위",   "desc": "확립된 전문 학회지 / 분야 Q1~Q2",
           "why": "해당 분야에서 확립된 전문 학회지입니다. 동료심사가 탄탄하지만, 최상위지보다는 다뤄지는 범위가 좁습니다."},
    "T3": {"label": "표준",   "desc": "정상 동료심사 저널 / 분야 Q3~Q4",
           "why": "정상적인 동료심사를 거치는 일반 저널입니다. 대부분의 연구가 여기 실립니다. 심사는 있었지만 파급력·엄격성은 상위지보다 낮습니다."},
    "T4": {"label": "주의",   "desc": "동료심사 불명확 / 포식성 의심 / 비심사",
           "why": "동료심사가 불명확하거나 '포식성(predatory)' 저널일 수 있습니다. 포식성 저널은 돈만 내면 제대로 된 검증 없이 실어줍니다. 실렸다는 사실 자체를 신뢰의 근거로 삼지 마세요."},
    "NA": {"label": "저널 아님", "desc": "프리프린트 / 블로그 / 기사",
           "why": "동료심사를 거치지 않은 프리프린트·블로그·기사입니다. 아직 학계 검증 절차를 통과하지 않았다는 뜻입니다."},
}

# Top-tier general journals (lowercase substring match). Extend here only.
JOURNAL_T1 = [
    "n engl j med", "new england journal", "lancet", "jama", "bmj",
    "cochrane", "nature medicine", "nature", "science", "cell",
]
JOURNAL_T2 = [
    "circulation", "diabetes care", "gut", "gastroenterology", "european heart",
    "annals of internal medicine", "plos medicine", "american journal of clinical nutrition",
]


def classify_journal_tier(journal_name: str) -> str:
    """Map a journal name to a tier code. Unknown names fall back to T3 (standard)."""
    if not journal_name:
        return "NA"
    j = journal_name.lower()
    if any(k in j for k in JOURNAL_T1):
        return "T1"
    if any(k in j for k in JOURNAL_T2):
        return "T2"
    if "medrxiv" in j or "biorxiv" in j or "preprint" in j:
        return "NA"
    return "T3"


# =============================================================================
# §3. Health claim categories
# =============================================================================
CLAIM_CATEGORIES = {
    "NUTRITION": "영양 / 보충제",
    "DIET":      "식이요법",
    "EXERCISE":  "운동 / 신체활동",
    "SLEEP":     "수면",
    "MENTAL":    "정신건강",
    "CHRONIC":   "만성질환 관리",
    "IMMUNE":    "감염 / 면역",
    "DRUG":      "의약품 / 상호작용",
    "ALT":       "대체 / 전통요법",
    "WEIGHT":    "다이어트 / 체중",
    "LONGEVITY": "노화 / 장수",
    "OTHER":     "기타",
}

# =============================================================================
# §4. Critical-thinking prompt pool
# =============================================================================
THINKING_PROMPTS = {
    "population": "이 연구 대상자는 나와 비슷한가요? (나이·성별·건강상태·기간)",
    "effect_size": "효과가 '있다/없다'가 아니라, 실생활에서 체감할 만한 크기인가요?",
    "causation": "이건 '원인'을 보여주나요, 아니면 '함께 나타남'(상관)을 보여주나요?",
    "conflict": "누가 이 연구에 자금을 댔나요? 영상 제작자는 무엇을 파나요?",
    "replication": "이 결과를 독립된 다른 연구팀도 확인했나요?",
    "absolute_risk": "'위험 2배'가 1%→2%인가요, 20%→40%인가요?",
    "duration": "단기 지표(체중·수치)인가요, 실제 건강 결과(질병·사망)인가요?",
}

# Prompt set per category (falls back to DEFAULT_PROMPTS)
CATEGORY_PROMPTS = {
    "NUTRITION": ["population", "effect_size", "conflict", "replication"],
    "DIET":      ["population", "duration", "effect_size", "causation"],
    "WEIGHT":    ["duration", "effect_size", "population", "conflict"],
    "IMMUNE":    ["population", "absolute_risk", "replication"],
    "DRUG":      ["population", "conflict", "absolute_risk"],
    "CHRONIC":   ["duration", "absolute_risk", "population"],
    "ALT":       ["causation", "conflict", "replication", "effect_size"],
}
DEFAULT_PROMPTS = ["population", "effect_size", "causation", "conflict"]


def prompts_for_category(category: str) -> list[str]:
    keys = CATEGORY_PROMPTS.get(category, DEFAULT_PROMPTS)
    return [THINKING_PROMPTS[k] for k in keys]


def evidence_level_obj(code: str) -> dict:
    """Evidence level object for a card (rank is not exposed)."""
    lv = EVIDENCE_LEVELS.get(code) or EVIDENCE_LEVELS["EXPERT"]
    if code not in EVIDENCE_LEVELS:
        code = "EXPERT"
    return {"code": code, "label": lv["label"], "desc": lv["desc"]}


def journal_tier_obj(code: str) -> dict:
    t = JOURNAL_TIERS.get(code) or JOURNAL_TIERS["T3"]
    if code not in JOURNAL_TIERS:
        code = "T3"
    return {"code": code, "label": t["label"], "desc": t["desc"]}


# Hierarchy list for the tooltip, ascending rank (strongest → weakest evidence).
def evidence_hierarchy() -> list[dict]:
    """Every evidence level in rank order: [{code, label, rank, desc, why}]."""
    items = sorted(EVIDENCE_LEVELS.items(), key=lambda kv: kv[1]["rank"])
    return [{"code": code, "label": lv["label"], "rank": lv["rank"],
             "desc": lv["desc"], "why": lv.get("why", "")} for code, lv in items]


# Every journal tier from T1 to NA: [{code, label, desc, why}].
_TIER_ORDER = ["T1", "T2", "T3", "T4", "NA"]


def journal_tier_list() -> list[dict]:
    return [{"code": code, "label": JOURNAL_TIERS[code]["label"],
             "desc": JOURNAL_TIERS[code]["desc"], "why": JOURNAL_TIERS[code].get("why", "")}
            for code in _TIER_ORDER]
