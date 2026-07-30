"""
Closed-loop evaluation harness for evidence quality.

Runs the pipeline (search + judging) over a set of claims, then has a verifier LLM
score the resulting cards on relevance, stance accuracy, and summary faithfulness
-> a quality score plus the list of failures. Re-run after changing prompts or code
to see whether the score moves.

  python eval_quality.py
"""
import json
import os
import sys
import time
from collections import Counter

import llm
import pubmed

# Verifier model. Weak models flunk correct output, so use one you trust.
VERIFIER_MODEL = os.environ.get("HEALTHLENS_VERIFIER_MODEL", "qwen3:8b")

CLAIMS = [
    ("비타민C가 대장암 예방에 도움이 된다", "vitamin C colorectal cancer"),
    ("크레아틴이 근력 향상에 도움이 된다", "creatine muscle strength"),
    ("오메가3가 심혈관 질환을 예방한다", "omega-3 cardiovascular disease"),
    ("커큐민이 염증을 줄인다", "curcumin inflammation"),
    ("프로바이오틱스가 과민성대장증후군을 개선한다", "probiotics irritable bowel syndrome"),
    ("비타민D가 우울증을 개선한다", "vitamin D depression"),
    ("마그네슘이 수면을 개선한다", "magnesium sleep"),
    ("간헐적 단식이 체중 감량에 효과적이다", "intermittent fasting weight loss"),
]

_VERIFY_SYSTEM = """너는 근거 품질 검수관이다. 각 항목은 (주장, 논문 초록, 우리가 매긴 stance, 우리 한국어 요약)이다.
초록만 근거로 삼아 판정하라. 기준:
- relevant: 초록이 주장의 '물질'과 '질환/대상'을 다루는가. 예방·치료·위험도·기전(세포/동물)
  어느 각도든 같은 물질·같은 질환이면 relevant=true. 물질이 다르거나(주장의 물질이 안 나옴)
  질환이 전혀 다르면 false.
- stanceOk: 우리 stance(SUPPORT=물질에 우호적 결과/OPPOSE=불리한 결과)가 초록이 실제
  보고한 결과 방향과 맞는가. 예방이냐 치료냐의 각도 차이는 문제삼지 마라(결과 방향만 본다).
- faithful: 우리 한국어 요약이 (a)초록에 실제로 있는 내용이고 (b)한국어만이며(한자·중국어·영어
  혼입 없음) (c)주장을 그대로 복붙하지 않고 이 연구의 발견을 담았는가. 하나라도 어기면 false.
  특히 초록에 없는 결론을 지어냈으면 false.
출력 JSON만: {"results":[{"i":0,"relevant":true,"stanceOk":true,"faithful":true,"reason":"짧은 이유"}]}"""

_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "relevant": {"type": "boolean"},
                    "stanceOk": {"type": "boolean"},
                    "faithful": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["i", "relevant", "stanceOk", "faithful", "reason"],
            },
        }
    },
    "required": ["results"],
}


def collect_cards(statement, term, ncbi=None):
    pool = pubmed.search(term, retmax=14, api_key=ncbi) + \
        pubmed.search(f"{term} randomized controlled trial OR meta-analysis OR cohort",
                      retmax=8, api_key=ncbi)
    seen, merged = set(), []
    for x in pool:
        if x.get("pmid") and x["pmid"] not in seen:
            seen.add(x["pmid"]); merged.append(x)
    cand = [x for x in merged if len(x.get("abstract") or "") >= 60][:12]
    judged = llm.judge_evidence(statement, [x.get("abstract", "") for x in cand]) or []
    out = []
    for x, j in zip(cand, judged):
        if j["stance"] in ("SUPPORT", "OPPOSE"):
            out.append({"abstract": x["abstract"], "title": x.get("title", ""),
                        "stance": j["stance"], "ko": j["ko"], "cite": x.get("authors", "")})
    return out[:6]  # verify at most 6 cards per claim


def verify(statement, cards):
    # Render each card as "abstract + our stance/summary" and send the batch to the
    # verifier (missing items are retried).
    texts = [f"초록: {c['abstract'][:850]}\n우리 stance: {c['stance']} / 우리 요약: {c['ko']}"
             for c in cards]
    saved = llm.OLLAMA_MODEL
    llm.OLLAMA_MODEL = VERIFIER_MODEL   # independent verifier
    try:
        items = llm.batch_items(_VERIFY_SYSTEM, _VERIFY_SCHEMA, f"주장: {statement}", texts, "results")
    finally:
        llm.OLLAMA_MODEL = saved
    res = []
    for it in items:
        if "relevant" in it:
            res.append(it)
        else:
            res.append({"relevant": None, "stanceOk": None, "faithful": None, "reason": "검증불가(제외)"})
    return res


def main():
    t0 = time.time()
    ncbi = None
    total, good = 0, 0
    fails = []
    for statement, term in CLAIMS:
        cards = collect_cards(statement, term, ncbi)
        vers = verify(statement, cards)
        stc = Counter(c["stance"] for c in cards)
        ok_here = 0
        for c, v in zip(cards, vers):
            if v.get("relevant") is None:   # unverifiable -> excluded
                continue
            total += 1
            ok = v["relevant"] and v["stanceOk"] and v["faithful"]
            if ok:
                good += 1; ok_here += 1
            else:
                fails.append((statement, c, v))
        print(f"· {statement[:22]:24s} 카드 {len(cards)}({stc.get('SUPPORT',0)}S/{stc.get('OPPOSE',0)}O) "
              f"통과 {ok_here}/{len(cards)}")
    score = good / total if total else 0
    print(f"\n=== 품질 점수: {good}/{total} = {score:.1%}  ({time.time()-t0:.0f}s) ===")
    print(f"실패 {len(fails)}건:")
    for statement, c, v in fails[:16]:
        flags = "".join(k[0] for k, val in
                        [("Rel", v["relevant"]), ("Stance", v["stanceOk"]), ("Faith", v["faithful"])] if not val)
        print(f"  [{c['stance']}] {statement[:16]} | 문제:{flags} | {c['title'][:45]}")
        print(f"      우리요약: {c['ko'][:70]}")
        print(f"      검수사유: {v['reason'][:80]}")
    return score


if __name__ == "__main__":
    main()
