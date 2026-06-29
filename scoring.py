"""Confidence scoring — combine the detection signals into one calibrated result.

Implements the planning.md rules (stretch feature 3 — three-signal ensemble):
  - weighted combine: 0.55*LLM + 0.30*stylometric + 0.15*phrase_pattern
    (weights renormalized over whichever signals are available)
  - thresholds: >= 0.70 likely_ai, <= 0.25 likely_human, else uncertain
  - false-positive-averse overrides (all can only move a verdict toward
    uncertain, never toward likely_ai):
      * short / insufficient stylometric text -> uncertain
      * ensemble voting rule: likely_ai requires combined >= AI_THRESHOLD AND
        at least VOTE_MIN_SIGNALS signals individually >= VOTE_THRESHOLD;
        otherwise force uncertain

The voting rule replaces the two-signal version's pairwise LLM/stylometric
disagreement override: requiring two of the three signals to corroborate is a
stronger, more general guard, and — unlike the pairwise rule — it does not veto a
verdict that two independent signals actually agree on.
"""

from config import (
    AI_THRESHOLD,
    HUMAN_THRESHOLD,
    LLM_WEIGHT,
    PHRASE_WEIGHT,
    STYLO_WEIGHT,
    VOTE_MIN_SIGNALS,
    VOTE_THRESHOLD,
)


def _attribution(score: float) -> str:
    if score >= AI_THRESHOLD:
        return "likely_ai"
    if score <= HUMAN_THRESHOLD:
        return "likely_human"
    return "uncertain"


def combine(llm: dict, stylo: dict, phrase: dict) -> dict:
    """Combine the three signal results into {confidence, attribution, notes}."""
    llm_p, stylo_p, phrase_p = (
        llm["ai_probability"],
        stylo["ai_probability"],
        phrase["ai_probability"],
    )
    llm_ok = llm["status"] == "available"
    stylo_ok = stylo["status"] == "available"
    phrase_ok = phrase["status"] == "available"  # phrase signal is always available
    notes = []

    # --- weighted combined score over available signals (renormalized) ---
    parts = []
    if llm_ok:
        parts.append((llm_p, LLM_WEIGHT))
    else:
        notes.append("llm_unavailable")
    if stylo_ok:
        parts.append((stylo_p, STYLO_WEIGHT))
    else:
        notes.append("stylometric_unavailable")
    if phrase_ok:
        parts.append((phrase_p, PHRASE_WEIGHT))

    total_w = sum(w for _, w in parts)
    combined = sum(p * w for p, w in parts) / total_w if total_w else 0.5
    combined = round(combined, 4)
    attribution = _attribution(combined)

    # --- overrides (only ever push toward uncertain) ---
    if stylo["status"] == "insufficient_text":
        if attribution != "uncertain":
            notes.append("short_text_forced_uncertain")
        attribution = "uncertain"

    # ensemble voting rule: likely_ai needs corroboration from >= 2 signals
    votes = sum(
        1
        for p, ok in ((llm_p, llm_ok), (stylo_p, stylo_ok), (phrase_p, phrase_ok))
        if ok and p >= VOTE_THRESHOLD
    )
    if attribution == "likely_ai" and votes < VOTE_MIN_SIGNALS:
        notes.append("ensemble_insufficient_votes_forced_uncertain")
        attribution = "uncertain"

    return {"confidence": combined, "attribution": attribution, "notes": notes}
