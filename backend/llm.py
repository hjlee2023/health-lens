"""
Claim extractor (live path). Only used for claims that aren't in the curated DB.

Provider selection (HEALTHLENS_LLM_BACKEND):
  - "ollama"    : local LLM (default, free). Needs an Ollama server on localhost:11434.
  - "anthropic" : Claude API (paid). Needs ANTHROPIC_API_KEY.
  - "none"      : disabled -> curated DB only.

Scope is limited to classification: normalize the claim, assign a category, build a PubMed
query. Evidence level and journal tier come from PubMed metadata, not from the LLM, so no
numbers get invented. Output is a fixed JSON schema, made deterministic with temperature 0
plus a pinned ollama seed.
"""
import json
import os
import re

import requests

from taxonomy import EVIDENCE_LEVELS

# Characters that must never appear in a Korean summary: kana, CJK ideographs, Arabic,
# Cyrillic. Hangul syllables (U+AC00-U+D7A3) are deliberately excluded.
_FOREIGN = re.compile(r"[぀-ヿ㐀-䶿一-鿿؀-ۿЀ-ӿ]")


def _has_foreign(s: str) -> bool:
    return bool(_FOREIGN.search(s or ""))


# Strips stance verdicts and meta commentary that leak into the ko summary. The prompt is
# the first line of defense; this is the backstop.
_KO_STANCE = re.compile(r"(SUPPORT|OPPOSE|NEUTRAL)", re.IGNORECASE)

# Detects animal / in-vitro abstracts so level can be corrected to PRECLINICAL. Skipped when
# the abstract shows human-trial signals.
_animal_sig = re.compile(r"\b(rats?|mice|mouse|murine|rodents?|zebrafish|drosophila|"
                         r"in vitro|cell lines?|cultured cells?|xenograft)\b", re.IGNORECASE)
_human_sig = re.compile(r"\b(patients?|adults?|humans?|participants?|men and women|"
                        r"individuals|subjects|women|children|volunteers)\b", re.IGNORECASE)

# For negative claims ("X is harmful / a burden / risky"), an abstract that confirms the harm
# often comes back as OPPOSE; flip it to SUPPORT. Small models routinely invert the direction
# on negative claims. Left alone when harm_deny matches (safe, no difference).
_neg_claim = re.compile(r"해롭|해로운|위험|부담|나쁘|악화|손상|증가시킨|유발|안 ?좋|부작용")
_harm_confirm = re.compile(r"부담(을)?\s*(줄|준|증가|늘|가중)|위험(을|이)?\s*(증가|높|커)|악화|손상|"
                           r"해롭|나쁘|증가시킨|유발한|더 ?생긴")
_harm_deny = re.compile(r"(차이|영향|효과|손상|부담)(가|이|을|는)?\s*(없|않|미미|주지 않)|안전|"
                        r"해롭지\s*않|영향을?\s*(주지\s*않|미치지\s*않)|개선|감소시킨")


def _clean_ko(ko: str) -> str:
    if not ko:
        return ko
    # 1) Drop a meta verdict clause tacked on after a comma inside a single sentence,
    #    trailing period and whitespace included.
    ko = re.sub(r"\s*[,，]\s*(주장[과의에]|주장의 주제|이는 주장|따라서|그러므로|이므로|판단하면|"
                r"직접적으로 관련|관련된 결과는 없|관련성이 부족)[^.。!?！？]*[.。!?！？]?\s*$",
                "", ko).strip()
    # 2) Drop whole sentences that carry a verdict or meta commentary
    parts = re.split(r"(?<=[.。!?])\s+", ko)
    kept = [p for p in parts if not re.search(
        r"(SUPPORT|OPPOSE|NEUTRAL|주장[과의에]\s*(직접|무관|관련)|주장의 주제|관련된 결과는 없|"
        r"(이|으)므로\s*(OPPOSE|SUPPORT|반박|지지)|(로|라고)\s*(분류|판단)(된다|한다|됨|함)?)",
        p, re.IGNORECASE)]
    ko = " ".join(kept) if kept else ko
    ko = _KO_STANCE.sub("", ko)
    # 3) If trimming left the clause ending on a connective, close it off cleanly
    ko = re.sub(r"(했|였|었|있|없|았|웠)(으나|나|며|고|지만)\s*$", r"\1다", ko.strip())
    return ko.strip(" ,.·-")

CATEGORIES = ["NUTRITION", "DIET", "EXERCISE", "SLEEP", "MENTAL", "CHRONIC",
              "IMMUNE", "DRUG", "ALT", "WEIGHT", "LONGEVITY", "OTHER"]

BACKEND = os.environ.get("HEALTHLENS_LLM_BACKEND", "ollama").lower()
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
# On a local GPU (RTX 4060 8GB or better) qwen3:14b judges clearly better than 8b: relevance
# gating, stance on negative claims. CPU-only or short on VRAM, drop to
# HEALTHLENS_OLLAMA_MODEL=qwen3:8b in .env.
OLLAMA_MODEL = os.environ.get("HEALTHLENS_OLLAMA_MODEL", "qwen3:14b")
ANTHROPIC_MODEL = os.environ.get("HEALTHLENS_MODEL", "claude-haiku-4-5")

_SYSTEM = """너는 건강정보 문해력 도구의 '분류기'다. 정답을 내리지 않는다.
입력(자막 또는 제목)에서 검증 가능한 '건강 주장'을 최대 2개까지 뽑아 정규화한다.
신뢰도 점수 같은 수치를 절대 만들지 않는다.
제목이 낚시성·조언형('~하려면 이것', '~에 좋은', '~ 없애는 법')이라도 함축된
건강 주장이 있으면 표준 형태로 정규화해 뽑아라.
예: '대장암 없애려면 비타민C 이렇게 드세요' -> '비타민C가 대장암 예방에 도움이 된다'.
단, 특정 물질/개입과 건강 결과의 관계가 전혀 없으면(단순 브이로그·후기 등) hasHealthClaim=false.
- statement: 정규화된 한국어 한 문장 주장 (영상 표현이 아니라 표준화된 형태).
  이건 '영상의 단정'이 아니라 '우리가 근거로 따져볼 핵심 쟁점(관계)'이다. 균형 잡힌 영상이어도
  중립 명제로 적으면 된다(예: '저탄고지 식단이 체중 감량에 효과적이다').
  ★영상이 든 자극적 수치(예: '노화를 75% 줄인다', 'DASH보다 2배')를 그대로 주장으로 삼지 마라.
   검증 가능한 '관계'로 표준화하라(예: '저속노화(마인드) 식단이 노화 지연·치매 예방에 도움이 된다').
   구체 수치는 rationale/videoEvidenceNote에만 담고 statement에는 넣지 마라.
  ★영상이 '중심으로' 다루는 대표적·검증가능한 주장을 골라라(지엽적·부차적 언급 말고).
  ★★방향을 뒤집지 마라. 영상이 어떤 개입·물질·식품을 '반대·유해·불필요·위험·먹지 마라'라고
   주장하면 statement도 그 '부정' 방향으로 적어라(예: 영상이 '단백질 보충제를 먹으면 안 된다'
   → statement는 '단백질 보충제(과다 단백질 섭취)가 건강에 해롭다'이지, '단백질 보충제가 근육에
   도움이 된다'가 아니다). 영상이 '해롭다/반대'인데 '유익하다/도움된다'로 뒤집으면 절대 안 된다.
  ★★★핵심 주장만 뽑아라. 영상 대부분이 '한 주제'(예: 마그네슘과 수면)를 다루면 그 1개만 뽑고,
   곁가지로 잠깐 언급된 것(예: 그 와중에 '근육 이완'을 곁들여 언급)을 억지로 두 번째 주장으로
   만들지 마라. 채울 2개가 없으면 1개만 내라(억지로 2개 채우기 금지).
  ★★★★주장을 '지나치게 포괄적'으로 만들지 마라. '건강한 식단', '좋은 생활습관', '건강한 음식'
   같은 넓은 범주는 근거 검색이 오염되니 금지. 영상이 강조한 '구체적 개입·물질'로 좁혀라.
   예: '건강한 식단이 고혈압에 좋다'(X) → '저염 식이가 혈압을 낮춘다' 또는 'DASH 식단이 혈압을
   낮춘다'(O). 단 이 '구체화'는 넓은 범주를 좁히는 것일 뿐, 위 ★★ '방향' 규칙이 항상 우선한다
   — 구체화한다고 영상이 '반대·유해'라던 것을 '유익·필요'로 절대 뒤집지 마라.
- videoStance: 영상이 이 쟁점을 다루는 태도. 제목이 아니라 '영상이 실제로 한 말'로 판정.
  * 영상에 반대·유보 신호가 하나라도 비중 있게 나오면 → MIXED.
    (신호 예: '하지만/반면/단점/한계/주의/부작용/논란/경우에 따라 다르다/사람마다 다르다/
    차이가 크지 않다/장기적으로는/과장됐다/필요 없다는 견해도').
  * ★단, 화자가 '반박·비판하려고 인용하는 상대편 통념'은 영상 자신의 유보가 아니다. 화자가
    끝까지 한쪽을 강하게 단정하면(예: '보충제를 먹어야 한다지만 사실 해로우니 절대 먹지 마라'
    — 앞부분은 반박 대상일 뿐) → ASSERTS. '화자가 자기 입으로 인정하는' 한계·예외만 MIXED 신호.
  * 처음부터 끝까지 한 방향으로 밀며 반론·한계를 거의 말하지 않으면 → ASSERTS.
  ★장점과 한계를 모두 말하는 균형 잡힌 설명(예: 의사의 '총정리')을 절대 ASSERTS로 몰지 마라.
   애매하면 MIXED.
- rationale: '영상이 실제로 말한 내용'을 한국어 2~3문장으로 중립 요약(없으면 '영상은 구체적
  근거를 제시하지 않음'). 판단하지 말고 영상의 논리를 그대로.
  ★긍정만 발췌하지 마라. 영상이 말한 '한계·반론·주의점'이 있으면 반드시 함께 담아라.
   MIXED면 장점과 한계 양면을 모두 드러내야 한다.
- videoEvidenceLevel: 영상이 실제로 제시·논의한 '가장 강한 근거'의 유형 코드.
  ★영상이 특정 메타분석/체계적고찰을 인용·논의하면 SR_MA, 무작위대조시험이면 RCT,
   코호트·관찰연구면 COHORT, 동물·세포 실험이면 PRECLINICAL로 정확히 올려라.
   (videoEvidenceNote에 '메타분석/RCT를 인용'이라 적었으면 level도 반드시 그 유형이어야 한다.
    note엔 '메타분석 인용'이라 쓰고 level은 EXPERT로 두는 모순은 금지.)
  특정 연구유형을 들지 않고 기전·원리 설명이나 전문가 견해만 있을 때만 EXPERT.
  '제가 먹어보니 나았다'·시청자 후기 등 개인경험 위주면 ANECDOTE.
  다음 중 하나: SR_MA / RCT / COHORT / CASE_CONTROL / CROSS_CASE / PRECLINICAL / EXPERT / ANECDOTE
- videoEvidenceNote: '이 영상이 실제로 든 근거'를 한국어 한 문장으로 직접 묘사.
  ★아래 형식 예시의 '단어'를 그대로 베끼지 마라. 특히 영상에 나오지도 않은 '항산화' 같은 말을
   넣지 마라 — 반드시 이 영상이 근거로 든 것만 써라.
  형식 예: '<영상이 든 근거 요지>, <특정 연구 인용 여부>'.
  (예: '탄수화물 절제의 개인 임상경험과 기전 설명 위주, 특정 연구 인용은 없음' /
   '2015년 개인화영양 연구를 인용하며 기전을 설명').
- videoCitedSource: 영상이 특정 연구·학술지·기관을 명시하면 그 이름, 없으면 빈 문자열.
- category: 이 주장(statement)의 '결과/대상'에 맞춰 아래 코드 중 하나.
  NUTRITION(영양/보충제) DIET(식이) EXERCISE(운동) SLEEP(수면) MENTAL(정신건강)
  CHRONIC(만성질환) IMMUNE(감염/면역) DRUG(의약품) ALT(대체요법) WEIGHT(체중)
  LONGEVITY(노화/장수) OTHER(기타)
  ★결과가 고혈압·당뇨·심혈관·콜레스테롤·혈압 등 만성질환/대사지표면 CHRONIC.
   체중감량이면 WEIGHT, 식단 자체가 주제면 DIET. 우울·불안·인지 등 정신 영역일 때만 MENTAL.
   (음식·식단 얘기가 나온다고 MENTAL로 새지 마라 — 주장의 실제 결과가 무엇인지로 판단.)
  ★비타민·미네랄·오메가3·아스타잔틴·루테인·프로바이오틱스 등 '영양소·건강기능식품'은 NUTRITION.
   ALT(대체요법)는 한방·침·약초·민간요법 같은 '비영양 대체의학'일 때만 쓴다.
- searchTerm: PubMed 영어 검색어. 핵심 물질 하나 + 주요 질환/결과 하나만, 2~4단어.
  여러 질환을 나열하지 말고 가장 중심인 것 하나로(예: 'vitamin C colorectal cancer').
  'prevention'이나 연구유형 단어는 넣지 마라(범위가 좁아짐).
건강 주장이 없으면 hasHealthClaim=false, claims=[]."""

# Output JSON schema enforced on both backends (structured output)
_SCHEMA = {
    "type": "object",
    "properties": {
        "hasHealthClaim": {"type": "boolean"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "statement": {"type": "string"},
                    "videoStance": {"type": "string", "enum": ["ASSERTS", "MIXED"]},
                    "rationale": {"type": "string"},
                    "videoEvidenceLevel": {"type": "string", "enum": list(EVIDENCE_LEVELS)},
                    "videoEvidenceNote": {"type": "string"},
                    "videoCitedSource": {"type": "string"},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "searchTerm": {"type": "string"},
                },
                "required": ["statement", "videoStance", "rationale", "videoEvidenceLevel",
                             "videoEvidenceNote", "category", "searchTerm"],
            },
        },
    },
    "required": ["hasHealthClaim", "claims"],
}


def _ollama_post(messages: list[dict], schema: dict, num_ctx: int = 8192, seed: int = 42) -> dict:
    """Shared Ollama /api/chat call with structured output. Qwen3 runs with thinking off so
    the JSON comes back clean."""
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "format": schema,
        "stream": False,
        "options": {"temperature": 0, "seed": seed, "num_ctx": num_ctx},
    }
    if "qwen3" in OLLAMA_MODEL:
        payload["think"] = False
    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"])


def _extract_ollama(transcript: str) -> dict | None:
    try:
        # Long roundup videos bury claims near the end, so reading only the opening misses
        # them. But on 8GB VRAM a big context pushes 14b into CPU offload and slows to a
        # crawl, so a 9000-char window with num_ctx 12288 keeps most of it on the GPU.
        return _ollama_post(
            [{"role": "system", "content": _SYSTEM},
             {"role": "user", "content": transcript[:9000]}], _SCHEMA, num_ctx=12288)
    except Exception as e:  # noqa: BLE001
        print(f"[llm/ollama] 실패: {e}")
        return None


def _extract_anthropic(transcript: str) -> dict | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=ANTHROPIC_MODEL, max_tokens=1024, temperature=0,
            system=_SYSTEM + '\n반드시 위 스키마의 JSON만 출력.',
            messages=[{"role": "user", "content": transcript[:6000]}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text").strip()
        text = text[text.find("{"): text.rfind("}") + 1]
        return json.loads(text)
    except Exception as e:  # noqa: BLE001
        print(f"[llm/anthropic] 실패: {e}")
        return None


def extract_claims(transcript: str) -> dict | None:
    if not transcript:
        return None
    if BACKEND == "ollama":
        return _extract_ollama(transcript)
    if BACKEND == "anthropic":
        return _extract_anthropic(transcript)
    return None  # "none"


# =============================================================================
# Evidence review: per-abstract stance (support / oppose / neutral) plus a one-sentence
# Korean summary, in one batched call. More accurate than the trained classifier on the
# live path; the classifier is the fallback for when the LLM is off.
# =============================================================================
_JUDGE_SYSTEM = """너는 의학 근거 심사관이다. 아래 초록들은 이미 '주장'과 관련해 검색된 것이다.
각 초록에 대해 세 가지를 낸다.

[level] 이 초록이 보고한 '연구 설계'를 초록의 방법 서술 기준으로 아래 코드 중 하나로 분류:
- SR_MA: 메타분석·체계적 문헌고찰(여러 연구를 모아 통합).
- RCT: 참가자를 무작위 배정해 개입군과 대조군을 비교한 시험.
- COHORT: 사람을 추적·관찰(전향/후향 코호트, 추적연구). 개입 없이 위험도·발생률·상관을 보고.
- CASE_CONTROL: 환자군과 대조군의 과거 노출을 비교.
- CROSS_CASE: 한 시점 단면조사, 또는 소수 증례 보고.
- PRECLINICAL: 세포·동물·시험관(in vitro / in vivo) 실험. 사람 대상이 아님.
- EXPERT: 새 데이터 없이 리뷰·사설·기전 설명·해석만 하는 글.
규칙: 사람 대상 관찰·역학(위험도·상관 보고)이면 COHORT, 동물·세포 실험이면 PRECLINICAL,
'Journal Article'처럼 유형이 모호해도 초록에 드러난 실제 방법으로 판단하라. 새 결과 데이터가
있으면 절대 EXPERT로 분류하지 마라(EXPERT는 리뷰·사설·의견처럼 원자료가 없을 때만).

[stance] 먼저 '관련성'을 판정하고, 관련될 때만 SUPPORT/OPPOSE를 정하라.
1) 관련성 게이트(최우선): 초록이 '주장의 핵심 물질'과 '주장의 결과/질환'을 둘 다 실제로
   다루지 않으면 무조건 NEUTRAL. 설령 '효과 없음/차이 없음'을 보고해도 그렇다.
   - 물질이 다르면 NEUTRAL. 예: 주장은 '저탄고지'인데 초록은 '비타민D' 연구 → NEUTRAL.
     (또 예: 주장은 '식이 단백질'인데 초록은 apoB·스타틴·특정 약물만 다루면, 결과가 '심혈관'으로
      같아도 물질이 다르므로 NEUTRAL. 주장의 물질 이름이 초록에 실제로 나와야 SUPPORT/OPPOSE.)
   - 결과/질환이 다르면 NEUTRAL. 예: 주장은 '고혈압'인데 초록은 '혈중 요산'만 봄 → NEUTRAL.
     (비타민C '감기' 시험이 '위암' 주장에 NEUTRAL인 것과 같다.)
   - 주장의 물질이 '연구가 실제로 시험한 개입·노출'이 아니라 부수적으로만 나오면 NEUTRAL.
     예: 주장은 '과일이 혈당에 영향'인데 초록의 개입은 '그룹진료 등 관리방식 비교'이고 과일은
     결과지표로만 측정 → NEUTRAL. 또 주장과 다른 개입을 시험하면(과일 주장인데 초록은
     '저탄수화물 식단'을 시험) NEUTRAL.
   - 결과 없이 배경·검토만이면 NEUTRAL.
   ★'효과 없음'을 봤다고 반사적으로 OPPOSE 하지 마라 — 그 '효과 없음'이 '주장의 바로 그
    결과/질환'에 대한 것일 때만 OPPOSE다. 다른 결과에 대한 '효과 없음'은 NEUTRAL이다.
2) 관련되면(물질·결과를 둘 다 다룸) 방향을 정한다. 기준은 언제나 '주장이 옳은가'다:
   - 주장이 '유익함'을 말할 때: 초록이 유리(위험↓·개선·억제)면 SUPPORT, 불리(효과없음·유의차
     없음·위험↑)면 OPPOSE.
   - ★주장이 '부정적 효과'(해롭다·위험·부담·나쁘다)를 말할 때는 방향을 뒤집는다: 초록이 그
     해로움을 확인하면(부담↑·위험↑·악화·손상) SUPPORT(주장 지지), 해롭지 않다고 하면
     (안전·차이없음·영향없음·개선) OPPOSE(주장 반박). 예: 주장 '단백질 보충제가 신장에 부담'
     → 초록 '신장 기능 악화' = SUPPORT, 초록 '신장 기능에 차이 없음' = OPPOSE.
주의: '섭취량↑일수록 질환위험↓'(역상관)은 물질이 유익하다는 뜻이므로 SUPPORT다.
★비교의 핵심(관련성 게이트를 통과한 경우에만 적용): 판정은 도입부의 '흔히 ~라고 홍보된다'가
  아니라 '초록이 보고한 결과·결론'으로 하라. 비교 연구(RCT·메타분석)에서 결과가 '비교대상과
  차이가 거의/전혀 없음'(little/no difference, no significant difference, comparable,
  similar, not superior)이면, 그 개입이 '(특별히) 효과적/우수하다'는 주장에는 SUPPORT가 아니라
  OPPOSE다. 개입군 내부에서 좋아졌다는 사실만으로 SUPPORT 하지 마라 — 비교대상도 똑같이
  좋아졌을 수 있다.
  ★★단, 이 '차이없음→OPPOSE' 규칙은 비교대상이 '무개입·표준식단·위약(플라시보)'일 때만 적용한다.
   비교가 '같은 개입의 두 변형·조합끼리'(예: 단식A vs 단식B, 단식+운동 vs 단식만, 저용량 vs
   고용량, 1일 vs 2일)면 그건 주장 자체의 효과가 아니라 '세부 최적화'다 — 두 변형 다 효과를
   보이면 SUPPORT(주장 지지), 주장과 직접 관련 없으면 NEUTRAL. 변형끼리의 우열·동등 비교를
   절대 OPPOSE로 분류하지 마라(그건 '이 개입이 효과 없다'는 뜻이 아니다).

[ko] 이 초록이 '무엇을 했고 무엇을 발견했는지' 한국어 한 문장으로. 규칙(엄수):
- 한국어만 써라. 한자·영어·중국어를 섞지 마라.
- ko는 '연구가 발견한 사실'만 담는 중립 요약이다. stance 판단이나 그 근거를 절대 넣지 마라:
  'SUPPORT/OPPOSE/NEUTRAL', '주장과 관련/무관', '이므로/따라서 ~로 분류·판단', '~므로 OPPOSE'
  같은 메타 서술 금지. ko만 읽어서는 네가 어떤 stance를 골랐는지 몰라야 한다.
- 스스로 모순된 문장 금지. '효과적임을 보여주었으나 효과적이지 않다'처럼 상반되게 쓰지 마라.
  결과가 엇갈리면 '주장과 직접 관련된 핵심 결과' 하나만 골라 명료한 한 문장으로.
- 초록에 실제로 있는 내용만. 초록에 없는 결론(예: '효과가 없다')을 절대 지어내지 마라.
- 주장 문장을 그대로 반복하지 마라. 이 연구가 발견한 구체적 사실을 써라.
- 반드시 '주장과 직접 관련된 결과'를 중심으로 요약하라. 초록이 여러 결과(예: 감기와 위암)를
  다루면, 주장에 해당하는 결과(위암)를 요약하고 무관한 결과(감기)는 넣지 마라.
- 가능하면 핵심 결과·수치를 담아라(예: '위험 12% 감소', 'HbA1c 유의하게 낮아짐',
  '대조군과 유의차 없음'). 막연히 '효과가 있다/없다'로만 쓰지 마라.
- 예방 연구인지, 치료 연구인지, 세포·동물 기전 연구인지, 관찰(위험도) 연구인지 드러내라.
  (예: '전이성 대장암 치료에서 고용량 비타민C가 내성 극복에 도움될 수 있다는 리뷰')
- 비교 연구면 '비교 결과'를 반드시 담아라. 개입군 내부 변화만 쓰지 말고 비교대상과의 차이를 써라.
  (예: '저탄수화물 식단은 체중을 줄였으나 균형 잡힌 탄수화물 식단과 비교해 체중·심혈관 위험에
  유의한 차이가 없었다')

출력 JSON만: {"items":[{"i":0,"level":"COHORT","stance":"SUPPORT|OPPOSE|NEUTRAL","ko":"한국어 한 문장"}]}"""

# Evidence levels for papers (ANECDOTE dropped — it never applies to a journal article)
JUDGE_LEVELS = [c for c in EVIDENCE_LEVELS if c != "ANECDOTE"]

_JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "level": {"type": "string", "enum": JUDGE_LEVELS},
                    "stance": {"type": "string", "enum": ["SUPPORT", "OPPOSE", "NEUTRAL"]},
                    "ko": {"type": "string"},
                },
                "required": ["i", "level", "stance", "ko"],
            },
        }
    },
    "required": ["items"],
}


def _fit(text: str, budget: int = 2200) -> str:
    """Trim a long abstract, keeping both the head (topic, aim) and the tail (results,
    conclusions). Structured abstracts (Cochrane, RCTs) put the conclusion last, so a
    head-only cut hides the Results/Conclusions the verdict depends on. Only the middle —
    search and selection boilerplate — gets dropped."""
    if len(text) <= budget:
        return text
    head = int(budget * 0.4)
    tail = budget - head - 5
    return text[:head] + " … " + text[-tail:]


def batch_items(system: str, schema: dict, header: str, texts: list[str],
                key: str, chunk: int = 3, tries: int = 3, valid=None) -> list[dict]:
    """Send texts to the LLM in small chunks and get one dict back per item.
    Retries with a different seed when items come back missing or malformed (foreign script
    and the like). Returns a list as long as texts, with {} for anything still missing."""
    res: list[dict] = [{} for _ in texts]
    for start in range(0, len(texts), chunk):
        idxs = list(range(start, min(start + chunk, len(texts))))
        sub = [texts[i] for i in idxs]
        best: dict = {}
        for attempt in range(tries):
            user = header + "\n\n" + "\n\n".join(f"[{k}] {_fit(t)}" for k, t in enumerate(sub))
            out = _chat_json_ollama(system, user, schema, seed=42 + attempt) if BACKEND == "ollama" \
                else _chat_json_anthropic(system, user)
            m = {it.get("i"): it for it in (out or {}).get(key, []) if isinstance(it, dict)}
            if len(m) >= len(best):
                best = m
            complete = all(k in m for k in range(len(sub)))
            if valid:
                complete = complete and all(valid(m.get(k, {})) for k in range(len(sub)))
            if complete:
                best = m
                break
        for k, i in enumerate(idxs):
            res[i] = best.get(k, {})
    return res


def judge_evidence(claim: str, texts: list[str]) -> list[dict] | None:
    """Returns [{level, stance, ko}] as long as texts, or None when no LLM is configured.
    Chunks of 3 plus retries keep it robust. level is the study design read off the abstract
    itself, which corrects the EXPERT misclassifications in PubMed's tags."""
    if not texts:
        return []
    if BACKEND not in ("ollama", "anthropic"):
        return None
    def _ok(it):
        return (bool(it.get("stance")) and it.get("level") in JUDGE_LEVELS
                and it.get("ko") and not _has_foreign(it["ko"]))

    # If the summary itself says the abstract is unrelated to the claim, demote SUPPORT/OPPOSE
    # to NEUTRAL so the two don't contradict each other.
    # Match negative phrasings only. Catching "is directly related" (positive) would demote
    # legitimate SUPPORT, so this list holds only the "not / insufficiently related" wording.
    offtopic = ("관련이 없", "관련된 결과는 제시", "관련된 결과는 없", "직접적인 관련이 없",
                "관련성이 부족", "관련이 부족", "관련이 부족", "주장과 무관", "주제와 관련이 없",
                "주장과 직접 관련된 결과는 없", "다루지 않", "제시되지 않았", "보고되지 않")
    # Deterministic guard against scoring a variant-vs-variant comparison as OPPOSE (fasting A
    # vs B, fasting+exercise vs fasting alone, low vs high dose). Small models can't filter
    # these out from the prompt alone. One variant beating another says nothing about whether
    # the intervention works, so a clear variant-comparison signal in ko turns OPPOSE into
    # NEUTRAL, which drops the item.
    variant_cmp = re.compile(
        r"병행한? ?(그룹|군)|조합.{0,6}(그룹|군|식단|요법)|(단독|만)한? ?(그룹|군).{0,20}(비교|비해)|"
        r"(에 비해|보다|과 비교해|대비) 더 (큰|높|나은|우수|많|강|감소)|"
        r"저용량.{0,14}고용량|고용량.{0,14}저용량|1일.{0,16}2일|2일.{0,16}1일")
    items = batch_items(_JUDGE_SYSTEM, _JUDGE_SCHEMA, f"주장: {claim}", texts, "items", valid=_ok)
    res, any_ok = [], False
    for i, it in enumerate(items):
        stance, ko = it.get("stance"), it.get("ko") or ""
        level = it.get("level") if it.get("level") in JUDGE_LEVELS else None
        if stance and any(p in ko for p in offtopic):
            stance = "NEUTRAL"
        if stance == "OPPOSE" and variant_cmp.search(ko):
            stance = "NEUTRAL"
        # Negative claim, abstract confirms the harm: undo the flipped OPPOSE
        if stance == "OPPOSE" and _neg_claim.search(claim) \
                and _harm_confirm.search(ko) and not _harm_deny.search(ko):
            stance = "SUPPORT"
        # Animal / in-vitro abstract misread as a human trial: force level to PRECLINICAL
        if level and level != "PRECLINICAL" and _animal_sig.search(texts[i]) \
                and not _human_sig.search(texts[i]):
            level = "PRECLINICAL"
        if stance:
            any_ok = True
            ko = _clean_ko(ko)
            if not ko or _has_foreign(ko):
                ko = "이 연구 결과를 한국어로 정확히 요약하지 못했습니다."
            res.append({"level": level, "stance": stance, "ko": ko})
        else:
            res.append({"level": level, "stance": "NEUTRAL", "ko": ""})
    return res if any_ok else None


def _chat_json_ollama(system: str, user: str, schema: dict, seed: int = 42) -> dict | None:
    try:
        return _ollama_post([{"role": "system", "content": system},
                             {"role": "user", "content": user}], schema, seed=seed)
    except Exception as e:  # noqa: BLE001
        print(f"[llm/chat-ollama] 실패: {e}")
        return None


def _chat_json_anthropic(system: str, user: str) -> dict | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=ANTHROPIC_MODEL, max_tokens=1500, temperature=0,
            system=system + "\n반드시 JSON만 출력.",
            messages=[{"role": "user", "content": user}])
        text = "".join(b.text for b in msg.content if b.type == "text")
        return json.loads(text[text.find("{"): text.rfind("}") + 1])
    except Exception as e:  # noqa: BLE001
        print(f"[llm/summarize-anthropic] 실패: {e}")
        return None


def status() -> dict:
    """Current backend and whether it's reachable, for the /health display."""
    info = {"backend": BACKEND, "available": False, "model": None}
    if BACKEND == "ollama":
        info["model"] = OLLAMA_MODEL
        try:
            tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).json()
            names = [m.get("name", "") for m in tags.get("models", [])]
            info["available"] = any(OLLAMA_MODEL.split(":")[0] in n for n in names)
            info["installed_models"] = names
        except Exception:  # noqa: BLE001
            info["available"] = False
    elif BACKEND == "anthropic":
        info["model"] = ANTHROPIC_MODEL
        info["available"] = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return info
