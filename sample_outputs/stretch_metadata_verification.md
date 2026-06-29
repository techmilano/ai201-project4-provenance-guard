# Stretch Feature 4 — Multi-Modal Support (metadata): verification record

Evidence for the **second content type**: structured creation metadata via
`POST /submit-metadata`. The free-text fields are normalized into one
`analysis_text` and run through the **existing 3-signal ensemble unchanged**; a
contextual metadata heuristic ([metadata_signal.py](../metadata_signal.py)) is
blended in `0.5 / 0.5`. Same thresholds as text (`>= 0.70` likely_ai, `<= 0.25`
likely_human). Every result is flagged as **contextual, not proof of
authorship.**

```
confidence = 0.5 * text_ensemble_confidence + 0.5 * metadata_context_score
```

---

## A. No AI assistance + detailed creation notes → `likely_human`

Request:

```json
{
  "creator_id": "alice",
  "title": "Autumn Walk",
  "description": "A short reflective essay about walking through the park as the leaves turn and the air gets colder.",
  "creation_notes": "Wrote this by hand in my notebook over two evenings, then typed it up and lightly edited for flow. Based on a real walk I took last week.",
  "tools_used": ["notebook", "Google Docs"],
  "declared_ai_assistance": false
}
```

Result:

```json
{
  "attribution": "likely_human",
  "confidence": 0.2423,
  "metadata_signals": {
    "metadata_context": { "score": 0.35,
      "breakdown": [{"factor":"base","delta":0.5},{"factor":"creation_notes_detailed","delta":-0.15}] },
    "text_analysis": { "confidence": 0.1346 }
  },
  "notes": ["metadata analysis is contextual and not proof of authorship"]
}
```

Detailed notes (`> 80` chars) subtract `0.15`; no declared AI, no AI tools. Both
the metadata context (`0.35`) and the human-sounding text (`0.13`) point low.

## B. Declared AI assistance (+ ChatGPT in tools) → `likely_ai`

Request (excerpt):

```json
{
  "creator_id": "bob",
  "title": "The Future of Work",
  "description": "In today's rapidly evolving landscape, this piece explores the transformative paradigm shift in remote work and its ethical implications for stakeholders.",
  "creation_notes": "Drafted with help from an assistant then revised.",
  "tools_used": ["ChatGPT", "Notion"],
  "declared_ai_assistance": true
}
```

Result:

```json
{
  "attribution": "likely_ai",
  "confidence": 0.8821,
  "metadata_signals": {
    "metadata_context": { "score": 1.0,
      "breakdown": [
        {"factor":"base","delta":0.5},
        {"factor":"declared_ai_assistance","delta":0.35},
        {"factor":"ai_tools_used:ChatGPT","delta":0.25}
      ],
      "declared_ai_assistance": true, "tools_used": ["ChatGPT","Notion"] },
    "text_analysis": { "confidence": 0.7643, "llm_ai_probability": 0.7, "phrase_ai_probability": 1.0 }
  },
  "notes": ["stylometric_unavailable","short_text_forced_uncertain","metadata analysis is contextual and not proof of authorship"]
}
```

Self-declared AI (`+0.35`) plus an AI tool (`+0.25`) cap the metadata context at
`1.0`; the AI-style description also scores high on the text side. Blended →
`0.8821` → `likely_ai`.

## C. Missing creation notes → `uncertain`

Request:

```json
{
  "creator_id": "cara",
  "title": "Untitled",
  "description": "A poem about the sea and memory and time passing slowly.",
  "tools_used": []
}
```

Result:

```json
{
  "attribution": "uncertain",
  "confidence": 0.3785,
  "metadata_signals": {
    "metadata_context": { "score": 0.6,
      "breakdown": [{"factor":"base","delta":0.5},{"factor":"creation_notes_missing_or_short","delta":0.10}] },
    "text_analysis": { "confidence": 0.1571 }
  },
  "notes": ["stylometric_unavailable","short_text_forced_uncertain","metadata analysis is contextual and not proof of authorship"]
}
```

Missing notes raise the metadata context (`+0.10` → `0.6`), but the human-ish
text pulls the blend down to `0.38` → `uncertain`. Lack of documentation is a
mild flag, not an accusation.

## Validation

```text
missing title             -> 400  {"error": "Field 'title' is required."}
tools_used not a list     -> 400  {"error": "Field 'tools_used' must be a list."}
declared_ai_assistance="yes" -> 400  {"error": "Field 'declared_ai_assistance' must be a boolean."}
```

## Audit log

Metadata submissions are logged with `event_type: "metadata_submission"` and
`content_type: "metadata"`, carrying the full `metadata_signals` (metadata
context breakdown + text ensemble scores + blend weight), attribution,
confidence, label, notes, and `status: "classified"` — distinct from text
`submission` entries but in the same `logs/audit.jsonl`.

---

## Design notes

- **Reuse, don't specialize.** The metadata free text runs through the *same*
  LLM + stylometric + phrase ensemble as `/submit`; no modality-specific markers
  were added (they would be normal description language, not authorship signals,
  and would raise false positives). One scoring model across content types.
- **Contextual, not proof.** Metadata describes *how a work was made*, not the
  work itself, so it is weaker evidence. Every result carries the contextual
  disclaimer, and the metadata heuristic can never reach `likely_human` on its
  own (its floor is `0.35`) — it can raise suspicion but not clear someone.
- **Blend weight** (`METADATA_TEXT_WEIGHT = 0.5`) is a single config constant,
  easy to retune.
