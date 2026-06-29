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

import re
import uuid

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config import LABELS, RATE_LIMIT, VERIFY_MAX_AI_PROBABILITY, VERIFY_MIN_WORDS
from detector import detect_ai
from stylometric import detect_stylometric
from phrase_signal import detect_phrases
from scoring import combine
from analytics import compute, render_dashboard
from auditor import (
    find_submission,
    log_appeal,
    log_submission,
    log_verification_attempt,
    read_all,
    read_appeals,
    read_log,
)
from verification import (
    certificate_for,
    consume_challenge,
    create_challenge,
    get_creator_status,
    grant,
    is_verified,
    validate_challenge,
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

    # --- detection signals (three-signal ensemble) ---
    llm = detect_ai(text)                  # Signal 1: Groq LLM (semantic)
    stylo = detect_stylometric(text)       # Signal 2: stylometric (structural)
    phrase = detect_phrases(text)          # Signal 3: phrase-pattern (lexical)

    # --- combined confidence scoring ---
    decision = combine(llm, stylo, phrase)
    confidence = decision["confidence"]
    attribution = decision["attribution"]
    label = label_for(attribution)

    # --- creator-level credential (does NOT affect attribution/confidence) ---
    certificate = certificate_for(creator_id)

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
        phrase_ai_probability=phrase["ai_probability"],
        phrase_status=phrase["status"],
        matched_phrases=phrase["matched_phrases"],
        notes=decision["notes"],
        provenance_certificate=certificate,
    )

    return jsonify(
        {
            "content_id": content_id,
            "attribution": attribution,
            "confidence": confidence,
            "label": label,
            "notes": decision["notes"],
            "provenance_certificate": certificate,
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
                "phrase": {
                    "ai_probability": phrase["ai_probability"],
                    "status": phrase["status"],
                    "matched_phrases": phrase["matched_phrases"],
                    "reasoning": phrase["reasoning"],
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


# --------------------------------------------------------------------------- #
# Provenance Certificate (stretch feature 2) — verified-human credential
# --------------------------------------------------------------------------- #

@app.route("/verification-challenge", methods=["POST"])
def verification_challenge():
    data = request.get_json(silent=True) or {}
    creator_id = data.get("creator_id")

    if not isinstance(creator_id, str) or not creator_id.strip():
        return jsonify({"error": "Field 'creator_id' is required."}), 400

    # Already verified: return current status, don't issue a new challenge.
    if is_verified(creator_id):
        return jsonify(
            {"message": "Creator is already verified.", **get_creator_status(creator_id)}
        )

    return jsonify(create_challenge(creator_id))


@app.route("/verify", methods=["POST"])
def verify():
    data = request.get_json(silent=True) or {}
    creator_id = data.get("creator_id")
    challenge_id = data.get("challenge_id")
    response_text = data.get("response_text")

    # --- required fields ---
    for name, value in (
        ("creator_id", creator_id),
        ("challenge_id", challenge_id),
        ("response_text", response_text),
    ):
        if not isinstance(value, str) or not value.strip():
            return jsonify({"error": f"Field '{name}' is required."}), 400

    # --- challenge must exist, belong to creator, be unused and unexpired ---
    challenge, err = validate_challenge(creator_id, challenge_id)
    if err:
        status = 404 if err == "challenge not found" else 403
        log_verification_attempt(creator_id, challenge_id, "rejected", None, None, err)
        return jsonify({"error": err}), status

    # --- minimum length ---
    word_count = len(re.findall(r"\b\w+\b", response_text))
    if word_count < VERIFY_MIN_WORDS:
        reason = f"response_text must be at least {VERIFY_MIN_WORDS} words"
        log_verification_attempt(
            creator_id, challenge_id, "rejected", None, word_count, reason
        )
        return jsonify({"error": reason, "word_count": word_count}), 403

    # --- score the response through the SAME detection pipeline ---
    llm = detect_ai(response_text)
    stylo = detect_stylometric(response_text)
    phrase = detect_phrases(response_text)
    decision = combine(llm, stylo, phrase)
    ai_probability = decision["confidence"]

    # One scored attempt per challenge (anti-gaming): consume it now.
    consume_challenge(challenge_id)

    if ai_probability > VERIFY_MAX_AI_PROBABILITY:
        reason = (
            f"response scored too AI-like "
            f"(ai_probability {ai_probability} > {VERIFY_MAX_AI_PROBABILITY})"
        )
        log_verification_attempt(
            creator_id, challenge_id, "rejected", ai_probability, word_count, reason
        )
        return jsonify({"error": reason, "ai_probability": ai_probability}), 403

    record = grant(creator_id, challenge_id, ai_probability)
    log_verification_attempt(
        creator_id, challenge_id, "granted", ai_probability, word_count, "passed"
    )
    return jsonify(
        {
            "creator_id": creator_id,
            "verified_human": True,
            "badge": record["badge"],
            "verified_at": record["verified_at"],
            "method": record["method"],
            "challenge_score": ai_probability,
        }
    )


@app.route("/creators/<creator_id>", methods=["GET"])
def creator_status(creator_id):
    return jsonify(get_creator_status(creator_id))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
