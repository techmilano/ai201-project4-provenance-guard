"""Detection Signal 1 — Groq LLM classification (LLM-as-judge).

A single Groq chat completion, no tools, no history. The response is parsed
and validated; any failure falls back to a safe, neutral result so the API
never crashes (fail closed, not open — see planning.md).
"""

import json

from groq import Groq

from config import GROQ_API_KEY, LLM_MODEL

SYSTEM_PROMPT = (
    "You are a text-provenance classifier for a creative-writing platform. "
    "Assess whether the submitted text reads as AI-generated or human-written, "
    "judging holistically: semantic coherence, register consistency, templated "
    "phrasing, and the over-smooth tone typical of AI text.\n\n"
    "Respond with ONLY a JSON object in exactly this form:\n"
    '{"ai_probability": <float 0.0-1.0>, "reasoning": "<one short sentence>"}\n\n'
    "ai_probability is the probability the text was AI-generated: 1.0 = almost "
    "certainly AI, 0.0 = almost certainly human. Do not output anything else."
)

# Lazy client init so a missing/invalid key triggers the safe fallback at call
# time rather than crashing on import.
_client = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=GROQ_API_KEY)
    return _client


def detect_ai(text: str) -> dict:
    """Classify `text` with the Groq LLM.

    Returns:
        {"ai_probability": float, "reasoning": str, "status": "available"} on
        success, or a safe degraded fallback with status "unavailable" if the
        request or parsing fails.
    """
    try:
        response = _get_client().chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        probability = max(0.0, min(1.0, float(data["ai_probability"])))
        reasoning = str(data.get("reasoning", "")).strip() or "No reasoning provided."
        return {
            "ai_probability": probability,
            "reasoning": reasoning,
            "status": "available",
        }
    except Exception as exc:  # network, parse, missing key, or bad value
        print(f"[detector] Groq signal unavailable: {exc}")
        return {
            "ai_probability": 0.5,
            "reasoning": "Groq signal unavailable; classification degraded.",
            "status": "unavailable",
        }
