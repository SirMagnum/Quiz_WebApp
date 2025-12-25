from flask import (
    render_template, request, jsonify, redirect, url_for, abort, flash, current_app
)
from flask_login import login_required, current_user
from extensions import db
from models import Question, Attempt, User
from . import quiz_bp
import random
import json
from datetime import datetime
import importlib

# -------------------------------
# VIEWS
# -------------------------------
@quiz_bp.route("/start")
@login_required
def start():
    return render_template("quiz_start.html")

@quiz_bp.route("/start/<mode>")
@login_required
def start_mode(mode):
    valid = ["adaptive", "challenger", "minuterush", "firststrike", "levelinfinity"]
    if mode not in valid:
        flash("Invalid mode.", "danger")
        return redirect(url_for("quiz.start"))
    return render_template("quiz.html", mode=mode)

@quiz_bp.route("/run/<mode>")
@login_required
def run_quiz(mode):
    return render_template("quiz.html", mode=mode)

# -------------------------------
# API: START ATTEMPT
# -------------------------------
@quiz_bp.route("/api/start_attempt", methods=["POST"])
@login_required
def start_attempt_api():
    data = request.get_json() or {}
    mode = data.get("mode", "adaptive")
    params = data.get("params", {})

    # Create Attempt Record
    attempt = Attempt(
        user_id=current_user.id,
        mode=mode,
        score=0,
        details=json.dumps([{
            "action": "start",
            "params": params,
            "timestamp": datetime.utcnow().isoformat()
        }])
    )
    db.session.add(attempt)
    db.session.commit()

    # Special Init for First Strike
    if mode == "firststrike":
        try:
            from quiz.modes.firststrike import start_attempt as fs_start
            fs_start(attempt)
            db.session.commit()
        except ImportError:
            return jsonify({"error": "Mode error. Please restart server."}), 500
        except Exception as e:
            current_app.logger.error(f"FS Init Error: {e}")
            return jsonify({"error": "Initialization failed"}), 500

    return jsonify({"attempt_id": attempt.id})

# -------------------------------
# API: GET QUESTION
# -------------------------------
@quiz_bp.route("/api/get_question", methods=["POST"])
@login_required
def get_question_api():
    data = request.get_json() or {}
    mode = (data.get("mode") or "adaptive").lower()
    attempt_id = data.get("attempt_id")
    state = data.get("state", {}) or {}

    attempt = Attempt.query.get(attempt_id)
    if not attempt:
        return jsonify({"error": "Invalid attempt"}), 400

    # 1. First Strike Override
    if mode == "firststrike":
        try:
            from quiz.modes.firststrike import get_question as fs_get
            return jsonify(fs_get(attempt))
        except ImportError:
            return jsonify({"error": "Mode module missing"}), 500

    # 2. Standard Logic (Stateless)
    try:
        current_diff = int(state.get("current_diff", 3))
    except: current_diff = 3
    
    seen = []
    for x in (state.get("seen_qids") or []):
        try: seen.append(int(x))
        except: pass

    # Check database status
    total = Question.query.count()
    if total == 0: return jsonify({"finished": True, "message": "No questions"})
    
    # --- FIX: Skip completion check for levelinfinity ---
    if mode != "levelinfinity":
        if len(seen) >= total:
            return jsonify({"finished": True, "message": "All done"})

    # Dispatcher
    q = None
    try:
        mod = importlib.import_module(f"quiz.modes.{mode}")
        if hasattr(mod, "get_question"):
            q = mod.get_question(current_diff, seen)
    except:
        pass # Fallback

    # Fallback if specific mode failed
    if not q:
        # For Level Infinity, we should force a pick even if seen=total
        if mode == "levelinfinity":
             pool = Question.query.all()
             if pool: q = random.choice(pool)
        else:
             pool = [x for x in Question.query.all() if x.id not in seen]
             if pool: q = random.choice(pool)

    if not q:
        return jsonify({"finished": True})

    return jsonify({
        "id": q.id,
        "prompt": q.prompt,
        "options": json.loads(q.options_json or "[]"),
        "difficulty": q.difficulty,
        "qtype": q.qtype,
        "state": {"current_diff": current_diff, "seen_qids": seen}
    })


# -------------------------------
# API: SUBMIT ANSWER
# -------------------------------
@quiz_bp.route("/api/submit_answer", methods=["POST"])
@login_required
def submit_answer_api():
    data = request.get_json() or {}
    attempt_id = data.get("attempt_id")
    qid = data.get("question_id")
    selected = data.get("selected")
    mode = (data.get("mode") or "").lower()
    time_used = data.get("time_used")

    attempt = Attempt.query.get(attempt_id)
    if not attempt: return jsonify({"error": "Invalid attempt"}), 400
    
    # Normalize Selection
    sel_list = []
    if isinstance(selected, list):
        sel_list = [str(x).strip() for x in selected if x is not None]
    elif selected is not None:
        sel_list = [str(selected).strip()]

    # 1. First Strike Override
    if mode == "firststrike":
        from quiz.modes.firststrike import submit_answer as fs_submit
        res = fs_submit(attempt, qid, sel_list, time_used)
        db.session.commit()
        return jsonify(res)

    # 2. Standard Scoring
    q = Question.query.get(qid)
    if not q: return jsonify({"error": "Question not found"}), 404

    # Check Correctness (Simplified logic for brevity, robust enough for standard usage)
    try: opts = json.loads(q.options_json or "[]")
    except: opts = []
    id_map = {str(o['id']): str(o.get('text','')).lower() for o in opts}
    
    raw = [str(x).strip() for x in (q.correct_answers or "").split(",") if x.strip()]
    correct_set = set()
    for r in raw:
        if r in id_map: correct_set.add(id_map[r])
        else: correct_set.add(r.lower())
        
    user_set = set()
    for u in sel_list:
        if u in id_map: user_set.add(id_map[u])
        else: user_set.add(u.lower())
        
    correct = (user_set == correct_set)

    # Mode Adjustments (e.g. Adaptive)
    points = 1 if correct else 0
    adj = {}
    
    if mode and mode != "firststrike":
        try:
            mod = importlib.import_module(f"quiz.modes.{mode}")
            if hasattr(mod, "handle_result"):
                res = mod.handle_result(attempt, q, correct, time_used)
                if isinstance(res, tuple):
                    points = res[0]
                    if len(res) > 1: adj = res[1]
        except: pass

    # Update Attempt
    attempt.score = (attempt.score or 0) + points
    
    # Log
    try: details = json.loads(attempt.details) if attempt.details else []
    except: details = []
    details.append({
        "qid": qid, "selected": sel_list, "correct": correct,
        "time_used": time_used, "difficulty": q.difficulty,
        "timestamp": datetime.utcnow().isoformat()
    })
    attempt.details = json.dumps(details)
    attempt.ended_at = datetime.utcnow()
    db.session.commit()
    
    # Adaptive Default
    if not adj and mode == "adaptive":
        adj = {
            "next_diff": min(10, q.difficulty + 1) if correct else max(1, q.difficulty - 1),
            "rule": "default"
        }

    return jsonify({
        "correct": correct,
        "attempt_score": attempt.score,
        "adjustment": adj,
        "correct_answers": raw
    })

# -------------------------------
# API: END ATTEMPT
# -------------------------------
@quiz_bp.route("/api/end_attempt", methods=["POST"])
@login_required
def end_attempt_api():
    data = request.get_json() or {}
    attempt = Attempt.query.get(data.get("attempt_id"))
    if attempt:
        attempt.ended_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"ok": True, "attempt_id": attempt.id})
    return jsonify({"error": "Invalid"}), 400

# -------------------------------
# PAGES
# -------------------------------
@quiz_bp.route("/results/<int:attempt_id>")
@login_required
def results(attempt_id):
    a = Attempt.query.get_or_404(attempt_id)
    if a.user_id != current_user.id and getattr(current_user, "role", None) != "teacher":
        abort(403)
        
    try:
        details = json.loads(a.details) if a.details else []
        events = [d for d in details if d.get("qid")]
    except: events = []

    total = Question.query.count() if a.mode == "firststrike" else len(events)
    correct_c = a.score or 0
    pct = round((correct_c / total * 100), 1) if total else 0
    
    return render_template("results.html", attempt=a, details=events, 
                           total_questions=total, percentage=pct, correct_count=correct_c)

@quiz_bp.route("/my_attempts")
@login_required
def my_attempts():
    attempts = Attempt.query.filter_by(user_id=current_user.id).order_by(Attempt.started_at.desc()).all()
    return render_template("my_attempts.html", attempts=attempts)

@quiz_bp.route("/profile")
@login_required
def profile():
    attempts = Attempt.query.filter_by(user_id=current_user.id).order_by(Attempt.started_at.desc()).all()
    scores = [a.score or 0 for a in attempts]
    avg = sum(scores)/len(scores) if scores else 0
    
    stats = {}
    for a in attempts:
        m = a.mode or "unknown"
        stats.setdefault(m, {"count":0, "total":0})
        stats[m]["count"] += 1
        stats[m]["total"] += (a.score or 0)
        
    return render_template("student_profile.html", attempts=attempts, 
                           total_attempts=len(attempts), avg_score=avg, 
                           best_score=max(scores) if scores else 0,
                           mode_stats=stats, recent=attempts[:10])