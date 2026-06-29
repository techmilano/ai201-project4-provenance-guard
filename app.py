"""Provenance Guard — Flask API.

Routes:
    GET  /health    liveness check
    POST /submit    classify text (Groq + stylometric), score, log  [rate limited]
    GET  /log       most recent audit-log entries
    POST /appeal    contest a classification; flips status to under_review
    GET  /appeals   reviewer queue of under_review items
    GET  /analytics aggregated metrics (stretch feature 1)
    GET  /dashboard HTML analytics view (stretch feature 1)
"""

import uuid

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import LABELS, RATE_LIMIT
from detector import detect_ai
from stylometric import detect_stylometric
from scoring import combine
from analytics import compute, render_dashboard
from auditor import (
    find_submission,
    log_appeal,
    log_submission,
    read_all,
    read_appeals,
    read_log,
)

app = Flask(__name__)

# Rate limiting — applied per-route below (only /submit), so no default limits.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


@app.errorhandler(429)
def ratelimit_exceeded(e):
    return jsonify({"error": f"Rate limit exceeded: {e.description}"}), 429


def label_for(attribution: str) -> str:
    """Return the verbatim transparency label text for an attribution category."""
    cfg = LABELS[attribution]
    return f"{cfg['icon']} {cfg['text']}"


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/submit", methods=["POST"])
@limiter.limit(RATE_LIMIT)
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
        label=label,
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


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    creator_id = data.get("creator_id")
    creator_reasoning = data.get("creator_reasoning")

    # --- validation ---
    if not isinstance(content_id, str) or not content_id.strip():
        return jsonify({"error": "Field 'content_id' is required."}), 400
    if not isinstance(creator_id, str) or not creator_id.strip():
        return jsonify({"error": "Field 'creator_id' is required."}), 400
    if not isinstance(creator_reasoning, str) or not creator_reasoning.strip():
        return jsonify({"error": "Field 'creator_reasoning' is required."}), 400

    # --- ownership checks against the original submission ---
    original = find_submission(content_id)
    if original is None:
        return jsonify({"error": f"No submission found for content_id '{content_id}'."}), 404
    if original["creator_id"] != creator_id:
        return jsonify(
            {"error": "creator_id does not match the original submission."}
        ), 403

    # --- record the appeal (status -> under_review) ---
    log_appeal(content_id, creator_id, creator_reasoning, original)

    return jsonify(
        {
            "content_id": content_id,
            "status": "under_review",
            "message": "Appeal received. Content is now under review.",
        }
    )


@app.route("/appeals", methods=["GET"])
def appeals():
    return jsonify({"entries": read_appeals()})


@app.route("/analytics", methods=["GET"])
def analytics():
    return jsonify(compute(read_all()))


@app.route("/dashboard", methods=["GET"])
def dashboard():
    return render_dashboard(compute(read_all()))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
