"""Provenance Guard — Flask API (Milestone 3).

Routes:
    GET  /health   liveness check
    POST /submit   classify text with Signal 1 (Groq) and log the decision
    GET  /log      most recent audit-log entries

Stylometric signal, confidence combination, appeals, and rate limiting arrive
in later milestones. For M3, confidence == the Groq ai_probability.
"""

import uuid

from flask import Flask, jsonify, request

from config import LABELS
from detector import detect_ai
from stylometric import detect_stylometric
from scoring import combine
from auditor import log_submission, read_log

app = Flask(__name__)


def label_for(attribution: str) -> str:
    """Return the verbatim transparency label text for an attribution category."""
    cfg = LABELS[attribution]
    return f"{cfg['icon']} {cfg['text']}"


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")

    # --- validation ---
    if not isinstance(text, str) or not text.strip():
        return jsonify({"error": "Field 'text' is required and cannot be empty."}), 400
    if not isinstance(creator_id, str) or not creator_id.strip():
        return jsonify({"error": "Field 'creator_id' is required."}), 400

    content_id = str(uuid.uuid4())

    # --- detection signals ---
    llm = detect_ai(text)                  # Signal 1: Groq LLM (semantic)
    stylo = detect_stylometric(text)       # Signal 2: stylometric (structural)

    # --- combined confidence scoring ---
    decision = combine(llm, stylo)
    confidence = decision["confidence"]
    attribution = decision["attribution"]
    label = label_for(attribution)

    # --- audit log ---
    log_submission(
        content_id=content_id,
        creator_id=creator_id,
        attribution=attribution,
        confidence=confidence,
        llm_ai_probability=llm["ai_probability"],
        llm_status=llm["status"],
        stylometric_ai_probability=stylo["ai_probability"],
        stylometric_status=stylo["status"],
        notes=decision["notes"],
    )

    return jsonify(
        {
            "content_id": content_id,
            "attribution": attribution,
            "confidence": confidence,
            "label": label,
            "notes": decision["notes"],
            "signals": {
                "llm": {
                    "ai_probability": llm["ai_probability"],
                    "reasoning": llm["reasoning"],
                    "status": llm["status"],
                },
                "stylometric": {
                    "ai_probability": stylo["ai_probability"],
                    "status": stylo["status"],
                    "metrics": stylo["metrics"],
                },
            },
        }
    )


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": read_log()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
