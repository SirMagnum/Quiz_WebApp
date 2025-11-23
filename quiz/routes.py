# quiz/routes.py
from flask import (
    render_template, request, jsonify, redirect, url_for, abort, flash
)
from flask_login import login_required, current_user
from extensions import db
from models import Question, Attempt, User
from . import quiz_bp
import random, json
from datetime import datetime


# New modular mode import
from quiz.modes import get_question_for_mode

# -------------------------------
# STUDENT: Quiz Start Page (Modes Gallery)
# -------------------------------
@quiz_bp.route("/start")
@login_required
def start():
    return render_template("quiz_start.html")

@quiz_bp.route("/start/<mode>")
@login_required
def start_mode(mode):
    # canonical mode names expected by backend
    valid_modes = ["adaptive", "challenger", "minuterush", "firststrike", "levelinfinity"]

    if mode not in valid_modes:
        flash("Invalid mode selected.", "danger")
        return redirect(url_for("quiz.start"))

    # direct render of quiz.html with the selected mode so client auto-starts
    return render_template("quiz.html", mode=mode)

@quiz_bp.route("/run/<mode>")
@login_required
def run_quiz(mode):
    # legacy route kept for compatibility; render quiz page with mode
    return render_template("quiz.html", mode=mode)

# -------------------------------
# API: Start Attempt
# -------------------------------
@quiz_bp.route("/api/start_attempt", methods=["POST"])
@login_required
def start_attempt():
    data = request.get_json() or {}
    mode = data.get("mode", "adaptive")
    params = data.get("params", {})

    attempt = Attempt(
        user_id=current_user.id,
        mode=mode,
        score=0,
        details=json.dumps([])
    )
    db.session.add(attempt)
    db.session.commit()

    return jsonify({"attempt_id": attempt.id})

# -------------------------------
# API: Get Next Question (updated to signal finished)
# -------------------------------
# Replace the existing get_question route in quiz/routes.py with this:

@quiz_bp.route("/api/get_question", methods=["POST"])
@login_required
def get_question():
    body = request.get_json() or {}
    mode = (body.get("mode") or "adaptive").lower()
    attempt_id = body.get("attempt_id")
    last_outcome = body.get("last_outcome")
    state = body.get("state", {}) or {}

    attempt = Attempt.query.get(attempt_id) if attempt_id else None
    if attempt_id and not attempt:
        return jsonify({"error": "invalid attempt_id"}), 400

    # normalize current_diff
    try:
        current_diff = int(state.get("current_diff", 3))
    except Exception:
        current_diff = 3

    # normalize seen_qids -> list of ints
    seen_raw = state.get("seen_qids", []) or []
    seen = []
    try:
        for v in seen_raw:
            if v is None:
                continue
            seen.append(int(v))
    except Exception:
        # fallback: best-effort conversion
        seen = [int(x) for x in seen_raw if isinstance(x, (int, str)) and str(x).isdigit()]

    # incorporate last_outcome into seen immediately (so server-side decisions use it)
    if last_outcome and last_outcome.get("qid") is not None:
        try:
            qid_val = int(last_outcome.get("qid"))
            if qid_val not in seen:
                seen.append(qid_val)
        except Exception:
            pass

    # quick sanity: if we've seen all questions -> finished
    total_q_count = Question.query.count()
    if total_q_count == 0:
        return jsonify({"finished": True, "message": "No questions in the database.", "attempt_id": attempt.id if attempt else None})

    # if client reports seen covers all DB questions, finish
    if len(seen) >= total_q_count:
        return jsonify({"finished": True, "message": "No unseen questions left.", "attempt_id": attempt.id if attempt else None})

    # Ask the mode dispatcher for a question (modes should accept the seen list)
    # but ensure final result is not in seen; if it is, fall back to strict exclusion pool.
    q = None
    try:
        q = get_question_for_mode(mode, current_diff, seen)
    except Exception:
        q = None

    # If dispatcher returned a question already seen (or None), pick from a strict pool
    if (not q) or (getattr(q, "id", None) in seen):
        # build strict pool excluding seen
        pool = [qq for qq in Question.query.all() if qq.id not in seen]
        if not pool:
            # nothing left
            return jsonify({"finished": True, "message": "No unseen questions left.", "attempt_id": attempt.id if attempt else None})
        import random
        q = random.choice(pool)

    # final guard (shouldn't happen) — if q still None, report finished
    if not q:
        return jsonify({"finished": True, "message": "No unseen questions left.", "attempt_id": attempt.id if attempt else None})

    # Return question payload and server-side state (ensure seen_qids are ints)
    return jsonify({
        "id": q.id,
        "prompt": q.prompt,
        "options": json.loads(q.options_json),
        "difficulty": q.difficulty,
        "qtype": q.qtype,
        "state": {"current_diff": current_diff, "seen_qids": seen}
    })


# -------------------------------
# API: Submit Answer (robust)
# -------------------------------
@quiz_bp.route("/api/submit_answer", methods=["POST"])
@login_required
def submit_answer():
    import importlib
    import logging
    logger = logging.getLogger(__name__)

    body = request.get_json() or {}
    attempt_id = body.get("attempt_id")
    qid = body.get("question_id")
    selected = body.get("selected")
    mode = (body.get("mode") or "").lower()
    time_used = body.get("time_used")
    state = body.get("state", {}) or {}

    attempt = Attempt.query.get(attempt_id)
    if not attempt:
        return jsonify({"error": "invalid attempt_id"}), 400

    q = Question.query.get(qid)
    if not q:
        return jsonify({"error": "question not found"}), 404

    # Normalize selected -> list of strings (canonical: ids as strings)
    try:
        if isinstance(selected, list):
            sel = [str(x).strip() for x in selected if x is not None]
        else:
            sel = [str(selected).strip()] if selected is not None else []
    except Exception:
        sel = []

    # Build option map id -> text from q.options_json
    try:
        opts = json.loads(q.options_json) if q.options_json else []
    except Exception:
        opts = []
    opt_id_to_text = {}
    opt_text_to_id = {}
    for o in opts:
        oid = str(o.get("id")).strip()
        text = str(o.get("text") or "").strip()
        opt_id_to_text[oid] = text
        # for text lookup, use lowercase trimmed text
        opt_text_to_id[text.lower()] = oid

    # Normalise correct answers from DB (raw)
    raw_correct = []
    if q.correct_answers:
        try:
            raw_correct = [str(x).strip() for x in q.correct_answers.split(",") if x is not None]
        except Exception:
            raw_correct = [str(q.correct_answers).strip()]

    # Try to map raw_correct entries to canonical option IDs when possible.
    mapped_correct_ids = set()
    for entry in raw_correct:
        if not entry:
            continue
        e = entry.strip()
        # If entry is exactly an option id
        if e in opt_id_to_text:
            mapped_correct_ids.add(e)
            continue
        # If entry matches option text (case-insensitive)
        lookup = e.lower()
        if lookup in opt_text_to_id:
            mapped_correct_ids.add(opt_text_to_id[lookup])
            continue
        # If entry is numeric-looking, coerce and test
        try:
            if str(int(e)) in opt_id_to_text:
                mapped_correct_ids.add(str(int(e)))
                continue
        except Exception:
            pass
        # Fallback: if entry doesn't match an id/text, keep the raw entry in mapped_correct_ids
        # (so we can compare against selected text if client sent text)
        mapped_correct_ids.add(e)

    # Also try to coerce selected entries to canonical IDs if user sent texts
    selected_ids = set()
    selected_texts = set()
    for s in sel:
        if s in opt_id_to_text:
            selected_ids.add(s)
        else:
            # check if matches option text
            s_lookup = s.strip().lower()
            if s_lookup in opt_text_to_id:
                selected_ids.add(opt_text_to_id[s_lookup])
            else:
                # treat as raw text selection
                selected_texts.add(s_lookup)

    # Decide correctness robustly
    correct = False
    if q.qtype == "multiple":
        # For multiple, require exact set equality of canonical ids if possible.
        # If mapped_correct_ids contain ids (i.e., exist in opt_id_to_text), compare ids.
        ids_in_mapped = {m for m in mapped_correct_ids if m in opt_id_to_text}
        if ids_in_mapped:
            # require exact match between ids
            correct = (ids_in_mapped == selected_ids)
        else:
            # fallback: compare by text strings (lowercased)
            mapped_texts = {str(x).strip().lower() for x in raw_correct if x}
            correct = (mapped_texts == selected_texts)
    else:
        # single question: accept if any canonical id matches, or text matches
        if len(selected_ids) == 1:
            # single id selected
            sel_id = next(iter(selected_ids))
            # if mapped_correct_ids has ids, check membership
            ids_in_mapped = {m for m in mapped_correct_ids if m in opt_id_to_text}
            if ids_in_mapped:
                correct = (sel_id in ids_in_mapped)
            else:
                # fallback: compare text
                sel_text = opt_id_to_text.get(sel_id, "").strip().lower()
                mapped_texts = {str(x).strip().lower() for x in raw_correct if x}
                correct = (sel_text in mapped_texts)
        elif len(selected_texts) == 1:
            # no id selected but raw text present
            st = next(iter(selected_texts))
            mapped_texts = {str(x).strip().lower() for x in raw_correct if x}
            correct = (st in mapped_texts)
        else:
            correct = False

    # Log the comparison details for debugging
    try:
        logger.info(
            "submit_answer: user=%s attempt=%s qid=%s qtype=%s raw_correct=%s mapped_correct_ids=%s selected_ids=%s selected_texts=%s -> correct=%s",
            getattr(attempt, "user_id", None),
            getattr(attempt, "id", None),
            getattr(q, "id", None),
            getattr(q, "qtype", None),
            raw_correct,
            list(mapped_correct_ids),
            list(selected_ids),
            list(selected_texts),
            bool(correct)
        )
    except Exception:
        logger.exception("submit_answer logging failed")

    # Default points
    points = 1 if correct else 0
    adjustment = {}

    # Try to call mode-specific handler dynamically: quiz.modes.<mode>.handle_result
    if mode:
        module_name = f"quiz.modes.{mode}"
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "handle_result"):
                try:
                    res = mod.handle_result(attempt, q, bool(correct), time_used=time_used)
                    if isinstance(res, tuple) and len(res) >= 1:
                        points = int(res[0]) if res[0] is not None else points
                        if len(res) > 1 and isinstance(res[1], dict):
                            adjustment = res[1]
                except Exception:
                    logger.exception("mode.handle_result failed for mode=%s", mode)
            else:
                logger.debug("No handle_result in module %s — using default scoring", module_name)
        except ModuleNotFoundError:
            logger.debug("No mode module found for %s — using default scoring", module_name)
        except Exception:
            logger.exception("Unexpected error importing mode module %s", module_name)

    # Apply points to attempt
    try:
        attempt.score = (attempt.score or 0) + int(points)
    except Exception:
        attempt.score = (attempt.score or 0) + (1 if correct else 0)

    # Record event
    event = {
        "qid": q.id,
        "selected": sel,
        "correct": bool(correct),
        "time_used": time_used,
        "difficulty": q.difficulty,
        "timestamp": datetime.utcnow().isoformat()
    }
    attempt.add_event(event)
    attempt.ended_at = datetime.utcnow()

    db.session.commit()

    # Provide fallback adjustment for adaptive if handler didn't return one
    if not adjustment and mode == "adaptive":
        adjustment = {
            "next_diff": min(10, q.difficulty + 1) if correct else max(1, q.difficulty - 1),
            "time_factor": "decrease" if not correct else "increase"
        }

    return jsonify({
        "correct": bool(correct),
        "attempt_score": attempt.score,
        "adjustment": adjustment,
        "correct_answers": list(raw_correct)
    })


# -------------------------------
# API: End Attempt
# -------------------------------
@quiz_bp.route("/api/end_attempt", methods=["POST"])
@login_required
def end_attempt():
    body = request.get_json() or {}
    attempt_id = body.get("attempt_id")

    attempt = Attempt.query.get(attempt_id)
    if not attempt:
        return jsonify({"error": "invalid attempt_id"}), 400

    attempt.ended_at = datetime.utcnow()
    db.session.commit()

    return jsonify({"ok": True, "attempt_id": attempt.id})


# -------------------------------
# RESULTS PAGE (compute totals & percent)
# -------------------------------
@quiz_bp.route("/results/<int:attempt_id>")
@login_required
def results(attempt_id):
    a = Attempt.query.get_or_404(attempt_id)

    # Student can't see other students' results
    if a.user_id != current_user.id and current_user.role.value != "teacher":
        abort(403)

    try:
        details = json.loads(a.details) if a.details else []
    except Exception:
        details = []

    # compute totals (total questions = number of recorded events; use unique qids if you prefer dedup)
    total_questions = len(details)
    correct_count = a.score or 0

    # Protect against division by zero
    percentage = None
    if total_questions > 0:
        try:
            percentage = round((correct_count / total_questions) * 100, 2)
        except Exception:
            percentage = None

    return render_template("results.html", attempt=a, details=details,
                           total_questions=total_questions, percentage=percentage, correct_count=correct_count)


# -------------------------------
# STUDENT / TEACHER ATTEMPTS VIEW
# -------------------------------
@quiz_bp.route("/my_attempts")
@login_required
def my_attempts():
    if current_user.role.value == "teacher":
        attempts = Attempt.query.order_by(Attempt.started_at.desc()).all()
        users = {u.id: u.username for u in User.query.all()}
        return render_template("my_attempts.html", attempts=attempts, user_cache=users)

    attempts = Attempt.query.filter_by(user_id=current_user.id).order_by(Attempt.started_at.desc()).all()
    return render_template("my_attempts.html", attempts=attempts, user_cache={})

# -------------------------------
# STUDENT PROFILE PAGE
# -------------------------------
@quiz_bp.route("/profile")
@login_required
def profile():
    user_id = current_user.id
    attempts = Attempt.query.filter_by(user_id=user_id).order_by(Attempt.started_at.desc()).all()

    total_attempts = len(attempts)
    avg_score = None
    best_score = None

    if total_attempts:
        scores = [a.score or 0 for a in attempts]
        avg_score = sum(scores) / len(scores)
        best_score = max(scores)

    mode_stats = {}
    for a in attempts:
        mode = a.mode or "unknown"
        mode_stats.setdefault(mode, {"count": 0, "total": 0})
        mode_stats[mode]["count"] += 1
        mode_stats[mode]["total"] += (a.score or 0)

    recent = attempts[:10]

    return render_template(
        "student_profile.html",
        attempts=attempts,
        total_attempts=total_attempts,
        avg_score=avg_score,
        best_score=best_score,
        mode_stats=mode_stats,
        recent=recent
    )
