from flask import (
    render_template, request, jsonify, redirect, url_for, abort, flash, current_app
)
from flask_login import login_required, current_user
from extensions import db
from models import Question, Attempt, User
from . import quiz_bp
import random, json
from datetime import datetime
import importlib

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
    # legacy route kept for compatibility
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

    # Initialize details with metadata about the run (e.g., time limit)
    initial_log = [{
        "action": "start",
        "params": params,
        "timestamp": datetime.utcnow().isoformat()
    }]

    attempt = Attempt(
        user_id=current_user.id,
        mode=mode,
        score=0,
        details=json.dumps(initial_log)
    )
    db.session.add(attempt)
    db.session.commit()

    return jsonify({"attempt_id": attempt.id})

# -------------------------------
# API: Get Next Question
# -------------------------------
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

    # Normalize current_diff
    try:
        current_diff = int(state.get("current_diff", 3))
    except Exception:
        current_diff = 3

    # Normalize seen_qids -> list of ints
    seen_raw = state.get("seen_qids", []) or []
    seen = []
    try:
        for v in seen_raw:
            if v is not None:
                seen.append(int(v))
    except Exception:
        # fallback: best-effort conversion
        seen = [int(x) for x in seen_raw if isinstance(x, (int, str)) and str(x).isdigit()]

    # Incorporate last_outcome into seen immediately
    if last_outcome and last_outcome.get("qid") is not None:
        try:
            qid_val = int(last_outcome.get("qid"))
            if qid_val not in seen:
                seen.append(qid_val)
        except Exception:
            pass

    # Quick sanity: if we've seen all questions -> finished
    total_q_count = Question.query.count()
    if total_q_count == 0:
        return jsonify({"finished": True, "message": "No questions in database.", "attempt_id": attempt.id if attempt else None})

    if len(seen) >= total_q_count:
        return jsonify({"finished": True, "message": "No unseen questions left.", "attempt_id": attempt.id if attempt else None})

    # --- MODE DISPATCHER ---
    # Try to load quiz/modes/<mode>.py -> get_question(diff, seen)
    # If not found, fallback to random strict exclusion
    q = None
    try:
        module_name = f"quiz.modes.{mode}"
        mod = importlib.import_module(module_name)
        if hasattr(mod, "get_question"):
            q = mod.get_question(current_diff, seen)
    except ImportError:
        pass # Mode module not found, use fallback
    except Exception as e:
        current_app.logger.error(f"Error in mode {mode} get_question: {e}")

    # Fallback: strict pool excluding seen
    if (not q) or (getattr(q, "id", None) in seen):
        pool = [qq for qq in Question.query.all() if qq.id not in seen]
        if not pool:
            return jsonify({"finished": True, "message": "No unseen questions left.", "attempt_id": attempt.id if attempt else None})
        q = random.choice(pool)

    # Final guard
    if not q:
        return jsonify({"finished": True, "message": "No unseen questions left.", "attempt_id": attempt.id if attempt else None})

    # Return payload
    return jsonify({
        "id": q.id,
        "prompt": q.prompt,
        "options": json.loads(q.options_json),
        "difficulty": q.difficulty,
        "qtype": q.qtype,
        "state": {"current_diff": current_diff, "seen_qids": seen}
    })


# -------------------------------
# API: Submit Answer (Robust Logic)
# -------------------------------
@quiz_bp.route("/api/submit_answer", methods=["POST"])
@login_required
def submit_answer():
    body = request.get_json() or {}
    attempt_id = body.get("attempt_id")
    qid = body.get("question_id")
    selected = body.get("selected")
    mode = (body.get("mode") or "").lower()
    time_used = body.get("time_used")
    
    attempt = Attempt.query.get(attempt_id)
    if not attempt:
        return jsonify({"error": "invalid attempt_id"}), 400

    q = Question.query.get(qid)
    if not q:
        return jsonify({"error": "question not found"}), 404

    # 1. Normalize selection to list of strings
    try:
        if isinstance(selected, list):
            sel = [str(x).strip() for x in selected if x is not None]
        else:
            sel = [str(selected).strip()] if selected is not None else []
    except Exception:
        sel = []

    # 2. Build Maps from Option ID <-> Text
    try:
        opts = json.loads(q.options_json) if q.options_json else []
    except: opts = []
    
    opt_id_to_text = {}
    opt_text_to_id = {}
    for o in opts:
        oid = str(o.get("id")).strip()
        text = str(o.get("text") or "").strip()
        opt_id_to_text[oid] = text
        opt_text_to_id[text.lower()] = oid

    # 3. Normalize Correct Answer from DB
    raw_correct = []
    if q.correct_answers:
        try:
            raw_correct = [str(x).strip() for x in q.correct_answers.split(",") if x]
        except:
            raw_correct = [str(q.correct_answers).strip()]

    # 4. Map raw_correct to Canonical Option IDs (Smart Match)
    mapped_correct_ids = set()
    for entry in raw_correct:
        e = entry.strip()
        # Direct ID match?
        if e in opt_id_to_text:
            mapped_correct_ids.add(e)
            continue
        # Text match?
        lookup = e.lower()
        if lookup in opt_text_to_id:
            mapped_correct_ids.add(opt_text_to_id[lookup])
            continue
        # Numeric fallback?
        try:
            if str(int(e)) in opt_id_to_text:
                mapped_correct_ids.add(str(int(e)))
                continue
        except: pass
        # Fallback: treat as raw text
        mapped_correct_ids.add(e)

    # 5. Normalize User Selection to Canonical IDs
    selected_ids = set()
    selected_texts = set()
    for s in sel:
        if s in opt_id_to_text:
            selected_ids.add(s)
        else:
            s_lookup = s.strip().lower()
            if s_lookup in opt_text_to_id:
                selected_ids.add(opt_text_to_id[s_lookup])
            else:
                selected_texts.add(s_lookup)

    # 6. Determine Correctness
    correct = False
    if q.qtype == "multiple":
        # Multiple: Set equality on IDs (strict)
        ids_in_mapped = {m for m in mapped_correct_ids if m in opt_id_to_text}
        if ids_in_mapped:
            correct = (ids_in_mapped == selected_ids)
        else:
            # Fallback: compare text sets
            mapped_texts = {str(x).strip().lower() for x in raw_correct if x}
            correct = (mapped_texts == selected_texts)
    else:
        # Single: If ANY selected ID matches ANY correct ID
        if len(selected_ids) == 1:
            sel_id = next(iter(selected_ids))
            ids_in_mapped = {m for m in mapped_correct_ids if m in opt_id_to_text}
            if ids_in_mapped:
                correct = (sel_id in ids_in_mapped)
            else:
                # Fallback text check
                sel_text = opt_id_to_text.get(sel_id, "").strip().lower()
                mapped_texts = {str(x).strip().lower() for x in raw_correct if x}
                correct = (sel_text in mapped_texts)
        elif len(selected_texts) == 1:
            st = next(iter(selected_texts))
            mapped_texts = {str(x).strip().lower() for x in raw_correct if x}
            correct = (st in mapped_texts)
        else:
            correct = False

    # 7. Scoring & Mode Handling
    points = 1 if correct else 0
    adjustment = {}

    if mode:
        module_name = f"quiz.modes.{mode}"
        try:
            mod = importlib.import_module(module_name)
            if hasattr(mod, "handle_result"):
                res = mod.handle_result(attempt, q, bool(correct), time_used=time_used)
                if isinstance(res, tuple) and len(res) >= 1:
                    points = int(res[0]) if res[0] is not None else points
                    if len(res) > 1 and isinstance(res[1], dict):
                        adjustment = res[1]
        except ModuleNotFoundError:
            pass # Default scoring
        except Exception as e:
            current_app.logger.error(f"Mode {mode} error: {e}")

    # Update Attempt
    try:
        attempt.score = (attempt.score or 0) + int(points)
    except:
        attempt.score = (attempt.score or 0) + (1 if correct else 0)

    # 8. Log Event
    try:
        # Load existing details to append
        details_list = json.loads(attempt.details) if attempt.details else []
    except:
        details_list = []

    event = {
        "qid": q.id,
        "selected": sel,
        "correct": bool(correct),
        "time_used": time_used,
        "difficulty": q.difficulty,
        "timestamp": datetime.utcnow().isoformat()
    }
    details_list.append(event)
    attempt.details = json.dumps(details_list)
    attempt.ended_at = datetime.utcnow() # update timestamp on every move

    db.session.commit()

    # Fallback adjustment for Adaptive if mode module missing
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
# RESULTS PAGE
# -------------------------------
@quiz_bp.route("/results/<int:attempt_id>")
@login_required
def results(attempt_id):
    a = Attempt.query.get_or_404(attempt_id)

    if a.user_id != current_user.id and getattr(current_user.role, "value", None) != "teacher":
        abort(403)

    try:
        details = json.loads(a.details) if a.details else []
        # Filter out metadata events (like "start") that don't have QIDs
        game_events = [d for d in details if d.get("qid")]
    except Exception:
        details = []
        game_events = []

    total_questions = len(game_events)
    correct_count = a.score or 0
    
    percentage = None
    if total_questions > 0:
        # Calculate purely based on correct/total for simple display
        # (This might differ from 'score' if score includes bonus points)
        raw_correct = sum(1 for d in game_events if d.get("correct"))
        percentage = round((raw_correct / total_questions) * 100, 1)

    return render_template("results.html", 
                           attempt=a, 
                           details=game_events,
                           total_questions=total_questions, 
                           percentage=percentage, 
                           correct_count=correct_count)


# -------------------------------
# VIEWS: Student Profile & Attempts
# -------------------------------
@quiz_bp.route("/my_attempts")
@login_required
def my_attempts():
    # If teacher, show all? Or just their own? Usually teachers have their own profile too.
    # If they want to see student attempts, they use the dashboard.
    attempts = Attempt.query.filter_by(user_id=current_user.id).order_by(Attempt.started_at.desc()).all()
    return render_template("my_attempts.html", attempts=attempts, user_cache={})

@quiz_bp.route("/profile")
@login_required
def profile():
    user_id = current_user.id
    attempts = Attempt.query.filter_by(user_id=user_id).order_by(Attempt.started_at.desc()).all()

    total_attempts = len(attempts)
    scores = [a.score or 0 for a in attempts]
    
    avg_score = sum(scores) / len(scores) if scores else 0
    best_score = max(scores) if scores else 0

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