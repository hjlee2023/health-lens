# HealthLens 근거 분류 표준안 (v0.1 초안)

> **Note for English readers.** This document is the evidence classification standard for
> HealthLens: the fixed taxonomies (evidence hierarchy, journal tiers, claim categories) that the
> pipeline classifies into, instead of inventing scores at run time. It is written in Korean on
> purpose, because the people who review and edit it are Korean pharmacists and evidence-based
> medicine specialists. The Korean labels in the tables below map 1:1 onto the constants in
> `backend/taxonomy.py`, so the two must be changed together. For an English description of the
> code itself, see `README.md`.

> 이 문서는 서비스의 **결정론적 출력**을 보장하는 뼈대입니다.
> LLM/파이프라인은 새로운 점수를 "발명"하지 않고, 아래에 **미리 정의된 고정 항목**으로
> 주장·근거를 **분류(classify)만** 합니다. 여기에 서술만 덧붙입니다.
>
> **상태:** 초안(엔지니어 작성). 약사·근거중심의학(EBM) 전문가 검수 대기.
> 검수자는 코드가 아니라 이 문서와 `backend/curated_db.json`만 수정하면 됩니다.

---

## 0. 설계 철학 (변경 금지 원칙)

1. **정답을 주지 않는다.** AI가 "이 주장은 신뢰도 82%" 같은 수치를 내지 않는다.
   수용자를 수동적으로 만들기 때문. 신뢰도·적합성은 **범주형 라벨**로만 표현한다.
2. **완전 대칭.** 주장을 **지지하는** 근거와 **반대/상충하는** 근거를
   **동일한 스키마, 동일한 시각적 비중**으로 병렬 제시한다.
3. **사고를 유도한다.** 결론 대신 "스스로 판단하기 위한 질문"을 함께 제공한다.
4. **재현성.** 같은 주장 → 항상 같은 카드. (해시 캐시 + temperature 0 + 정렬)

---

## 1. 근거 레벨 위계 (Evidence Hierarchy)

Oxford CEBM / GRADE를 단순화한 **7단계 고정 위계**.
`rank`가 낮을수록 일반적으로 인과추론 강도가 높음. **단, rank는 순위 표시일 뿐 점수가 아니다.**

| code           | rank | 라벨(국문)                     | 정의 / 판별 힌트                                               |
|----------------|------|--------------------------------|---------------------------------------------------------------|
| `SR_MA`        | 1    | 체계적 문헌고찰 / 메타분석     | 여러 연구를 체계적으로 종합. "systematic review", "meta-analysis", Cochrane |
| `RCT`          | 2    | 무작위 대조 시험               | 무작위 배정 + 대조군. "randomized controlled trial", "double-blind" |
| `COHORT`       | 3    | 코호트(관찰) 연구              | 노출군을 추적하는 전향/후향 관찰. "cohort", "prospective", "longitudinal" |
| `CASE_CONTROL` | 4    | 환자-대조군 연구               | 결과 기준으로 과거 노출 비교. "case-control"                   |
| `CROSS_CASE`   | 5    | 단면연구 / 증례 시리즈         | "cross-sectional", "case series", "case report"               |
| `EXPERT`       | 6    | 전문가 의견 / 기전 추론        | 내러티브 리뷰, 사설, 기전(mechanism) 기반 추정. 임상 근거 아님 |
| `PRECLINICAL`  | 7    | 동물 / 시험관 연구             | in vitro, in vivo(비인간), 세포주. "mice", "in vitro"          |

**표기 규칙:** 카드에는 `rank` 숫자를 노출하지 않고 **라벨 + 짧은 설명 배지**로만 보여준다.
(예: `RCT · 무작위 대조 시험`)

---

## 2. 학술지 공신력 tier (Journal Credibility)

절대적 임팩트 수치 대신 **5단계 범주형 tier**. 분야별 상대성을 반영한다.

| code | 라벨            | 기준(가이드)                                                              |
|------|-----------------|---------------------------------------------------------------------------|
| `T1` | 최상위          | 주요 종합의학지(NEJM, Lancet, JAMA, BMJ), Cochrane Library, 분야 Q1 상위 |
| `T2` | 상위            | 확립된 전문 학회지, 분야 Q1~Q2                                             |
| `T3` | 표준            | 정상 동료심사 저널, 분야 Q3~Q4                                             |
| `T4` | 주의            | 동료심사 불명확 / 포식성(predatory) 의심 / 비심사                          |
| `NA` | 저널 아님       | 프리프린트(medRxiv 등), 블로그, 기사, 백서                                 |

**주의:** tier는 "그 논문이 옳다"가 아니라 "출판 경로의 검증 강도"를 뜻함.
카드 문구에 이 뉘앙스를 항상 유지한다.

---

## 3. 건강 주장 카테고리 (Claim Taxonomy)

주장을 아래 **고정 카테고리** 중 하나로 분류. (매칭·캐시·전문가 배정의 키)

| code           | 라벨              | 예시                                   |
|----------------|-------------------|----------------------------------------|
| `NUTRITION`    | 영양 / 보충제     | 비타민, 오메가-3, 프로바이오틱스       |
| `DIET`         | 식이요법          | 간헐적 단식, 저탄고지, 채식            |
| `EXERCISE`     | 운동 / 신체활동   | HIIT, 근력운동, 걷기                   |
| `SLEEP`        | 수면              | 수면시간, 멜라토닌                     |
| `MENTAL`       | 정신건강          | 명상, 스트레스, 우울                   |
| `CHRONIC`      | 만성질환 관리     | 당뇨, 고혈압, 콜레스테롤               |
| `IMMUNE`       | 감염 / 면역       | 감기 예방, 백신, 면역력                |
| `DRUG`         | 의약품 / 상호작용 | 진통제, 항생제, 약물-음식 상호작용     |
| `ALT`          | 대체 / 전통요법   | 한방, 아로마, 디톡스                   |
| `WEIGHT`       | 다이어트 / 체중   | 체중감량, 대사, 지방연소               |
| `LONGEVITY`    | 노화 / 장수       | 항산화, 텔로미어, NAD+                 |
| `OTHER`        | 기타              | 위에 없는 건강 주장                    |

---

## 4. 사고 유도 질문 세트 (Thinking Prompts)

카드마다 결론 대신 아래 풀에서 **주장 유형에 맞는 2~4개**를 고정 선택해 노출.

- **모집단 일치:** "이 연구 대상자는 나와 비슷한가요? (나이·성별·건강상태·기간)"
- **효과 크기:** "효과가 '있다/없다'가 아니라, 실생활에서 **체감할 만한 크기**인가요?"
- **인과 vs 상관:** "이건 '원인'을 보여주나요, 아니면 '함께 나타남'을 보여주나요?"
- **이해상충:** "누가 이 연구에 **자금을 댔나요?** 영상 제작자는 무엇을 파나요?"
- **재현성:** "이 결과를 **독립된 다른 연구팀**도 확인했나요?"
- **절대위험:** "'위험 2배'가 1%→2%인가요, 20%→40%인가요?"
- **기간:** "단기 지표(체중·수치)인가요, 실제 건강 결과(질병·사망)인가요?"

---

## 5. 출력 계약(Output Contract) 요약

`POST /analyze` 응답의 각 claim 객체는 아래를 만족해야 한다.

- `statement`: 정규화된 한 문장 (영상 표현이 아니라 표준화된 주장)
- `category`: §3 code 중 하나
- `supporting[]`, `opposing[]`: **같은 스키마**. 각 항목은
  `{ summary, evidenceLevel(code/label), journalTier(code/label), year, citation, url }`
- **수치 신뢰도 필드 금지.** (`confidence`, `score` 등 존재하면 계약 위반)
- `thinkingPrompts[]`: §4에서 선택된 문자열들
- `source`: `"curated"`(전문가 DB) | `"live"`(실시간 검색)

---

## 6. 변경 관리

- 위계(§1)·tier(§2)·카테고리(§3) 코드값은 **함부로 바꾸지 않는다**(캐시·DB 키).
  라벨/설명 문구는 자유롭게 개선 가능.
- 개별 주장의 근거 카드는 `curated_db.json`에서 관리. 전문가는 이 파일만 편집.
- 코드 변경 없이 표준을 확장하려면: 이 문서 + `taxonomy.py`의 상수만 동기화.
