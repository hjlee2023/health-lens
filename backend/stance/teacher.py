"""
Teacher: (claim, abstract) -> stance label. Sees more than the student does:
the whole abstract, not just cue features.

- LLM teacher: Claude labels in batches (HEALTHLENS_TEACHER_MODEL). Needs ANTHROPIC_API_KEY.
  * This is evidence-direction classification, not deep biology, so a small model is enough.
- Human teacher: read to_label.jsonl yourself and fill in LABELS in commit_labels.py.

auto_loop.py calls label_batch() to run the unattended closed loop.

Warning: the training labels in this repo were assigned by an LLM, not by a
medical expert (see data/README.md).
"""
import json
import os
import sys

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)
MODEL = os.environ.get("HEALTHLENS_TEACHER_MODEL", "claude-fable-5")
VALID = {"SUPPORT", "OPPOSE", "NEUTRAL"}

_SYS = """너는 근거 stance 라벨러다. 각 (주장, 초록)에 대해 초록이 주장을
SUPPORT(뒷받침) / OPPOSE(반박·무효·유의차없음) / NEUTRAL(배경·기전·프로토콜·주제이탈) 중
무엇으로 판정하는지 정한다. 규칙:
- 효과 있음/위험 낮춤/유의한 개선 = SUPPORT
- 효과 없음/유의차 없음/위약과 차이 없음/무관 = OPPOSE
- 기전·리뷰개요·가이드라인·설계/프로토콜·설문, 또는 주장과 다른 물질/결과를 다룸 = NEUTRAL
입력 각 항목은 [번호] 주장 / 초록 형식이다.
출력은 JSON 배열만: [{"i": 0, "stance": "SUPPORT"}, ...]. 설명 금지."""


def label_batch(items: list[dict], max_chars: int = 1500) -> list[str | None]:
    """items: [{claim, text, ...}] -> stances in the same order. None where labeling failed.

    Each item must already carry the abstract body in `text` (see texts.hydrate).
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        print("[teacher] No ANTHROPIC_API_KEY - cannot label with the LLM")
        return [None] * len(items)
    import anthropic

    client = anthropic.Anthropic(api_key=key)
    lines = []
    for i, it in enumerate(items):
        lines.append(f"[{i}] 주장: {it['claim']}\n초록: {it['text'][:max_chars]}")
    user = "\n\n".join(lines)

    out: list[str | None] = [None] * len(items)
    try:
        msg = client.messages.create(
            model=MODEL, max_tokens=1200, temperature=0,
            system=_SYS, messages=[{"role": "user", "content": user}],
        )
        raw = "".join(b.text for b in msg.content if b.type == "text")
        raw = raw[raw.find("["): raw.rfind("]") + 1]
        for rec in json.loads(raw):
            i, st = rec.get("i"), rec.get("stance")
            if isinstance(i, int) and 0 <= i < len(items) and st in VALID:
                out[i] = st
    except Exception as e:  # noqa: BLE001
        print(f"[teacher] Batch labeling failed: {e}")
    return out


if __name__ == "__main__":
    from texts import hydrate

    src = os.path.join(DATA, "to_label.jsonl")
    with open(src, "r", encoding="utf-8") as f:
        items = [json.loads(ln) for ln in f if ln.strip()]
    items = hydrate(items)  # repo only keeps pmids, so pull the bodies from the cache
    for it, st in zip(items, label_batch(items)):
        print(st, "|", it["claim"], "|", it["pmid"])
