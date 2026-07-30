"""
Cue lexicon for stance classification.
Oriented around "beneficial" claims (X is good for Y / X prevents Y):
- POS_CUES:   an effect was found -> usually points to SUPPORT
- NEG_CUES:   no effect / not significant -> usually points to OPPOSE
- HEDGE_CUES: uncertain, more research needed -> leans NEUTRAL
These are only features. The classifier learns the actual decision from data;
nothing here is a hard-coded rule.
"""

POS_CUES = [
    "reduced", "reduction", "decreased", "lower risk", "lowered", "improved",
    "improvement", "benefit", "beneficial", "effective", "efficacy", "protective",
    "prevented", "prevention", "associated with lower", "significantly reduced",
    "was associated with a lower", "inverse association", "greater weight loss",
    "shorten", "shortened", "alleviated", "significant improvement",
]

NEG_CUES = [
    "no significant", "not significant", "no association", "no difference",
    "did not", "no effect", "no benefit", "not associated", "failed to",
    "ineffective", "no reduction", "was not associated", "did not reduce",
    "did not prevent", "no evidence", "not superior", "no better than placebo",
    "did not differ", "null", "no clinically", "not effective",
]

HEDGE_CUES = [
    "may", "might", "could", "suggests", "suggest", "further research",
    "more research", "low-quality", "low quality", "heterogeneity",
    "inconclusive", "uncertain", "limited evidence", "well-designed",
    "should be interpreted with caution", "warrants",
]

# NEUTRAL signals: background, study design, mechanism, or off-topic rather than
# an actual efficacy result
NEUTRAL_CUES = [
    "protocol", "study design", "recruitment", "narrative review",
    "this review summarizes", "this review discusses", "guideline",
    "guidelines", "editorial", "cross-sectional survey", "mechanism",
    "mechanisms", "pharmacokinetics", "still unclear", "remains unclear",
    "remains uncertain", "cannot establish", "observational design",
    "no specific", "design of", "rationale", "overview", "we describe",
    "precludes", "cannot infer", "mendelian randomization",
]


def count_cues(text_lower: str, cues: list[str]) -> int:
    return sum(text_lower.count(c) for c in cues)
