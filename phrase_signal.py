"""Detection Signal 3 — phrase-pattern signal (stretch: ensemble detection).

A cheap, fully independent lexical check: it scans for common AI-style filler
phrases / markers. Independent of the LLM's semantic read and the stylometric
structural metrics, so it adds genuine ensemble value.

Conservative by design: the score is the density of *distinct* matched phrases
relative to text length (matches per ~100 words), and a single match is capped
low — one incidental phrase can never, on its own, push the ensemble toward
`likely_ai`. The voting rule in scoring.py provides the second layer of caution.

Always reports status "available" (pure Python, no external dependency).
"""

import re

# Common AI-style phrases / markers (lowercased, matched as substrings).
AI_PHRASES = [
    "it is important to note",
    "rapidly evolving",
    "in today's",
    "transformative",
    "paradigm shift",
    "furthermore",
    "moreover",
    "stakeholders",
    "ethical implications",
    "responsible deployment",
    "delve into",
    "robust",
    "seamless",
    "leverage",
    "unlock",
]

_WORD = re.compile(r"\b\w+\b")

# matches-per-100-words that corresponds to a maximal score. Several markers are
# needed before the signal reads strongly AI.
_DENSITY_FOR_MAX = 4.0
# a lone phrase is weak evidence — cap its standalone contribution below the
# voting threshold (0.60) so it can never count as an AI "vote" by itself.
_SINGLE_MATCH_CAP = 0.30


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def detect_phrases(text: str) -> dict:
    """Score `text` on AI-style phrase density.

    Returns:
        {"ai_probability": float, "status": "available",
         "matched_phrases": [...], "reasoning": str}
    """
    lowered = text.lower()
    matched = [p for p in AI_PHRASES if p in lowered]
    n = len(matched)
    word_count = len(_WORD.findall(text)) or 1

    if n == 0:
        return {
            "ai_probability": 0.0,
            "status": "available",
            "matched_phrases": [],
            "reasoning": "No common AI-style phrases detected.",
        }

    density_per_100 = n / word_count * 100.0
    ai_probability = _clamp(density_per_100 / _DENSITY_FOR_MAX)
    if n == 1:
        ai_probability = min(ai_probability, _SINGLE_MATCH_CAP)
    ai_probability = round(ai_probability, 4)

    return {
        "ai_probability": ai_probability,
        "status": "available",
        "matched_phrases": matched,
        "reasoning": (
            f"Matched {n} common AI-style phrase(s) "
            f"({density_per_100:.1f} per 100 words): {', '.join(matched)}."
        ),
    }
