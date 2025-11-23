# teacher/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from extensions import db
from models import Question, User, Role, Attempt
import json
from functools import wraps

teacher_bp = Blueprint("teacher", __name__)


# --- ROLE CHECK ---
def teacher_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # ensure current_user has a role attribute and is teacher
        if not hasattr(current_user, "role") or getattr(current_user.role, "value", None) != "teacher":
            flash("Unauthorized access.", "danger")
            return redirect(url_for("auth.index"))
        return func(*args, **kwargs)
    return wrapper


# --- DASHBOARD ---
@teacher_bp.route("/dashboard")
@login_required
@teacher_required
def dashboard():
    """
    Teacher dashboard: shows counts, students table, average scores and links to view attempts.
    """
    qcount = Question.query.count()
    ucount = User.query.count()

    # list students
    students = User.query.filter(User.role == Role.STUDENT).order_by(User.id.desc()).all()

    # prepare attempts per student (id -> list of Attempt)
    attempts = Attempt.query.all()
    s_attempts = {}
    for a in attempts:
        s_attempts.setdefault(a.user_id, []).append(a)

    # compute average score per student (None or float)
    s_avg = {}
    for s in students:
        al = s_attempts.get(s.id, [])
        if not al:
            s_avg[s.id] = None
        else:
            total = sum((a.score or 0) for a in al)
            s_avg[s.id] = total / len(al)

    return render_template("dashboard.html",
                           qcount=qcount,
                           ucount=ucount,
                           students=students,
                           s_avg=s_avg)


# --- LIST QUESTIONS ---
@teacher_bp.route("/questions")
@login_required
@teacher_required
def questions():
    qs = Question.query.order_by(Question.created_at.desc()).all()
    return render_template("teacher_questions.html", questions=qs)


# --- ADD QUESTION ---
@teacher_bp.route("/questions/add", methods=["POST"])
@login_required
@teacher_required
def add_question():
    prompt = request.form.get("prompt")
    opt1 = request.form.get("opt1")
    opt2 = request.form.get("opt2")
    opt3 = request.form.get("opt3")
    opt4 = request.form.get("opt4")
    correct = request.form.get("correct")
    difficulty = request.form.get("difficulty") or 3
    qtype = request.form.get("qtype") or "single"

    if not prompt or not opt1 or not opt2 or not correct:
        flash("Please fill required fields (question, at least two options, and correct option).", "danger")
        return redirect(url_for("teacher.questions"))

    # normalize difficulty
    try:
        diff = int(difficulty)
    except:
        diff = 1
    if diff <= 0:
        diff = 1
    if diff > 10:
        diff = 10

    options = []
    for idx, val in enumerate([opt1, opt2, opt3, opt4], start=1):
        if val:
            options.append({"id": str(idx), "text": val})

    q = Question(
        prompt=prompt,
        options_json=json.dumps(options, ensure_ascii=False),
        correct_answers=str(correct),
        qtype=qtype,
        difficulty=diff
    )
    db.session.add(q)
    db.session.commit()

    flash("Question added!", "success")
    return redirect(url_for("teacher.questions"))


# --- EDIT PAGE ---
@teacher_bp.route("/questions/<int:qid>/edit")
@login_required
@teacher_required
def edit_question(qid):
    q = Question.query.get_or_404(qid)
    try:
        opt_list = json.loads(q.options_json)
    except Exception:
        opt_list = []
    opt_texts = [o.get("text", "") for o in opt_list]
    while len(opt_texts) < 4:
        opt_texts.append("")
    return render_template("edit_question.html", q=q, opt_texts=opt_texts)


# --- SAVE EDIT ---
@teacher_bp.route("/questions/<int:qid>/edit", methods=["POST"])
@login_required
@teacher_required
def update_question(qid):
    q = Question.query.get_or_404(qid)

    prompt = request.form.get("prompt")
    opt1 = request.form.get("opt1")
    opt2 = request.form.get("opt2")
    opt3 = request.form.get("opt3")
    opt4 = request.form.get("opt4")
    correct = request.form.get("correct")
    diff = request.form.get("difficulty") or 3
    qtype = request.form.get("qtype") or "single"

    # normalize difficulty
    try:
        diff_i = int(diff)
    except:
        diff_i = 1
    if diff_i <= 0:
        diff_i = 1
    if diff_i > 10:
        diff_i = 10

    options = []
    for idx, val in enumerate([opt1, opt2, opt3, opt4], start=1):
        if val:
            options.append({"id": str(idx), "text": val})

    q.prompt = prompt
    q.options_json = json.dumps(options, ensure_ascii=False)
    q.correct_answers = str(correct)
    q.difficulty = diff_i
    q.qtype = qtype

    db.session.commit()

    flash("Question updated!", "success")
    return redirect(url_for("teacher.questions"))


# --- DELETE SINGLE QUESTION ---
@teacher_bp.route("/questions/<int:qid>/delete", methods=["POST"])
@login_required
@teacher_required
def delete_question(qid):
    q = Question.query.get_or_404(qid)
    db.session.delete(q)
    db.session.commit()
    flash("Question deleted.", "success")
    return redirect(url_for("teacher.questions"))


# --- MASS DELETE ---
@teacher_bp.route("/mass_delete", methods=["POST"])
@login_required
@teacher_required
def mass_delete():
    qids = request.form.getlist("qids")

    if not qids:
        flash("No questions selected.", "danger")
        return redirect(url_for("teacher.questions"))

    deleted = 0
    for qid in qids:
        q = Question.query.get(qid)
        if q:
            db.session.delete(q)
            deleted += 1

    db.session.commit()

    flash(f"Deleted {deleted} questions.", "success")
    return redirect(url_for("teacher.questions"))


# --- BULK UPLOAD (XLSX WITH DIFFICULTY RANGE: 1–10) ---
@teacher_bp.route("/upload_excel", methods=["POST"])
@login_required
@teacher_required
def upload_excel():
    # import here to avoid requiring openpyxl unless route is used
    try:
        import openpyxl
    except Exception:
        flash("openpyxl is required for Excel upload. Install it in your venv.", "danger")
        return redirect(url_for("teacher.questions"))

    file = request.files.get("file")
    if not file:
        flash("No file selected.", "danger")
        return redirect(url_for("teacher.questions"))

    if not (file.filename and file.filename.lower().endswith(".xlsx")):
        flash("Only .xlsx files supported.", "danger")
        return redirect(url_for("teacher.questions"))

    try:
        wb = openpyxl.load_workbook(file)
        sheet = wb.active

        added, updated = 0, 0

        for i, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            if i == 1:
                # header row expected. tolerant: we just skip header.
                continue

            # Unpack safely - allow shorter rows
            # Expect: Question, Op1, Op2, Op3, Op4, CorrectOp, Difficulty (Difficulty optional)
            qvals = list(row) + [None] * 7
            qtxt, op1, op2, op3, op4, correct, difficulty = qvals[:7]

            if not qtxt or not op1 or not op2 or not correct:
                # skip invalid rows
                continue

            # --- DIFFICULTY FIX ---
            try:
                diff_i = int(difficulty) if difficulty is not None else 1
            except:
                diff_i = 1
            if diff_i <= 0:
                diff_i = 1
            if diff_i > 10:
                diff_i = 10

            options = []
            for idx, val in enumerate([op1, op2, op3, op4], start=1):
                if val:
                    options.append({"id": str(idx), "text": str(val)})

            q = Question.query.filter_by(prompt=str(qtxt)).first()

            if q:
                q.options_json = json.dumps(options, ensure_ascii=False)
                q.correct_answers = str(correct)
                q.difficulty = diff_i
                updated += 1
            else:
                new = Question(
                    prompt=str(qtxt),
                    options_json=json.dumps(options, ensure_ascii=False),
                    correct_answers=str(correct),
                    qtype="single",
                    difficulty=diff_i
                )
                db.session.add(new)
                added += 1

        db.session.commit()

        flash(f"Upload complete! Added: {added} · Updated: {updated}", "success")

    except Exception as e:
        flash(f"Import failed: {str(e)}", "danger")

    return redirect(url_for("teacher.questions"))


# --- CREATE STUDENT ---
@teacher_bp.route("/students/add", methods=["POST"])
@login_required
@teacher_required
def add_student():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not password:
        flash("Username and password are required.", "danger")
        return redirect(url_for("teacher.dashboard"))

    if User.query.filter_by(username=username).first():
        flash("A user with that username already exists.", "danger")
        return redirect(url_for("teacher.dashboard"))

    student = User(username=username, role=Role.STUDENT)
    student.set_password(password)
    db.session.add(student)
    db.session.commit()
    flash(f"Student '{username}' created.", "success")
    return redirect(url_for("teacher.dashboard"))


# --- DELETE STUDENT ---
@teacher_bp.route("/students/<int:uid>/delete", methods=["POST"])
@login_required
@teacher_required
def delete_student(uid):
    u = User.query.get_or_404(uid)

    if u.role != Role.STUDENT:
        flash("Cannot delete a non-student user.", "danger")
        return redirect(url_for("teacher.dashboard"))

    # Delete related attempts to avoid orphaned rows / id reuse issues
    try:
        # Bulk delete attempts for the user
        Attempt.query.filter_by(user_id=u.id).delete()
        db.session.commit()
    except Exception:
        # If bulk-delete fails for some DB types, fallback to iterative delete
        db.session.rollback()
        for a in Attempt.query.filter_by(user_id=u.id).all():
            db.session.delete(a)
        db.session.commit()

    # Now delete the user
    db.session.delete(u)
    db.session.commit()
    flash(f"Student '{u.username}' deleted.", "success")
    return redirect(url_for("teacher.dashboard"))


# --- VIEW STUDENT ATTEMPTS ---
@teacher_bp.route("/students/<int:uid>/attempts")
@login_required
@teacher_required
def view_student_attempts(uid):
    student = User.query.get_or_404(uid)
    if student.role != Role.STUDENT:
        flash("Not a student.", "danger")
        return redirect(url_for("teacher.dashboard"))

    attempts = Attempt.query.filter_by(user_id=student.id).order_by(Attempt.started_at.desc()).all()
    return render_template("student_attempts.html", student=student, attempts=attempts)

# Teacher analytics (teacher-only)
import collections
from sqlalchemy import func

@teacher_bp.route("/analytics")
@login_required
@teacher_required
def analytics():
    """
    Teacher analytics dashboard:
     - overall attempts, avg score
     - per-mode averages
     - question-level accuracy
     - difficulty distribution
    """
    # totals & averages
    total_attempts = Attempt.query.count()
    avg_score_row = db.session.query(func.avg(Attempt.score)).scalar() or 0
    avg_score = round(float(avg_score_row), 2)

    # per-mode averages
    modes = db.session.query(Attempt.mode, func.count(Attempt.id).label("cnt"), func.avg(Attempt.score).label("avg")).group_by(Attempt.mode).all()
    per_mode = [{"mode": m[0] or "unknown", "count": int(m[1]), "avg": round(float(m[2] or 0), 2)} for m in modes]

    # question-level accuracy: parse Attempt.details (JSON list of events)
    # We'll build a map: qid -> {seen, correct}
    q_stats = {}
    all_attempts = Attempt.query.filter(Attempt.details.isnot(None)).all()
    for a in all_attempts:
        try:
            events = json.loads(a.details)
        except Exception:
            continue
        for ev in events:
            qid = ev.get("qid")
            if not qid:
                continue
            rec = q_stats.setdefault(qid, {"seen": 0, "correct": 0})
            rec["seen"] += 1
            if ev.get("correct"):
                rec["correct"] += 1

    # attach question text and difficulty
    question_info = []
    if q_stats:
        qids = list(q_stats.keys())
        qs = Question.query.filter(Question.id.in_(qids)).all()
        qmap = {q.id: q for q in qs}
        for qid, rec in q_stats.items():
            q = qmap.get(qid)
            prompt = q.prompt if q else f"Q {qid}"
            diff = q.difficulty if q else None
            accuracy = round((rec["correct"] / rec["seen"])*100, 2) if rec["seen"] else 0.0
            question_info.append({
                "qid": qid,
                "prompt": (prompt[:120] + "...") if prompt and len(prompt) > 120 else prompt,
                "difficulty": diff,
                "seen": rec["seen"],
                "correct": rec["correct"],
                "accuracy": accuracy
            })

    # difficulty distribution: for difficulties 1..10 compute total seen and accuracy
    diff_buckets = {i: {"seen": 0, "correct": 0} for i in range(1, 11)}
    for item in question_info:
        d = item.get("difficulty") or 1
        if d < 1: d = 1
        if d > 10: d = 10
        diff_buckets[d]["seen"] += item["seen"]
        diff_buckets[d]["correct"] += item["correct"]

    diff_list = []
    for d in range(1, 11):
        seen = diff_buckets[d]["seen"]
        correct = diff_buckets[d]["correct"]
        acc = round((correct / seen)*100, 2) if seen else None
        diff_list.append({"difficulty": d, "seen": seen, "correct": correct, "accuracy": acc})

    # Top/bottom questions
    top_questions = sorted(question_info, key=lambda x: (-x["accuracy"], -x["seen"]))[:10]
    bottom_questions = sorted(question_info, key=lambda x: (x["accuracy"], -x["seen"]))[:10]

    return render_template("teacher_analytics.html",
                           total_attempts=total_attempts,
                           avg_score=avg_score,
                           per_mode=per_mode,
                           question_info=question_info,
                           diff_list=diff_list,
                           top_questions=top_questions,
                           bottom_questions=bottom_questions)

# teacher/routes.py  (append or place near your other teacher routes)

from flask import jsonify, current_app

# --- MANAGE ATTEMPTS PAGE ---
@teacher_bp.route("/attempts/manage")
@login_required
@teacher_required
def manage_attempts():
    """
    Teacher page: list attempts. If ?uid=<student_id> is provided, show only that student's attempts.
    Otherwise show a condensed student list (with counts) and an option to view that student's attempts.
    """
    # optional filter by student id
    uid = request.args.get("uid", type=int)

    users = {u.id: u.username for u in User.query.order_by(User.username).all()}

    if uid:
        # show only this student's attempts
        student = User.query.get_or_404(uid)
        attempts = Attempt.query.filter_by(user_id=uid).order_by(Attempt.started_at.desc()).all()
        return render_template("teacher_manage_attempts.html",
                               attempts=attempts,
                               user_cache=users,
                               filtered_student=student)
    else:
        # show student summary (counts) to avoid showing "all attempts" at once
        # gather attempt counts per user
        counts = db.session.query(Attempt.user_id, db.func.count(Attempt.id)).group_by(Attempt.user_id).all()
        counts_map = {row[0]: row[1] for row in counts}
        # prepare student list (only users that have attempts or all students as you prefer)
        students = User.query.order_by(User.username).all()
        return render_template("teacher_manage_attempts.html",
                               attempts=[],
                               user_cache=users,
                               students=students,
                               counts_map=counts_map,
                               filtered_student=None)


@teacher_bp.route("/attempts/student/<int:uid>/delete_all", methods=["POST"])
@login_required
@teacher_required
def delete_student_attempts(uid):
    """
    Delete all attempts belonging to a student (teacher-only).
    Safety: requires confirmation via form (checked client-side).
    """
    student = User.query.get_or_404(uid)
    try:
        deleted = Attempt.query.filter_by(user_id=uid).delete(synchronize_session=False)
        db.session.commit()
        current_app.logger.info("Teacher %s deleted all attempts for student %s (deleted=%s)",
                                current_user.id, uid, deleted)
        flash(f"Deleted {deleted} attempts for {student.username}.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Failed to delete attempts for student %s: %s", uid, e)
        flash("Failed to delete student attempts.", "danger")
    return redirect(url_for("teacher.manage_attempts"))



# --- MASS DELETE ATTEMPTS ---
@teacher_bp.route("/attempts/mass_delete", methods=["POST"])
@login_required
@teacher_required
def mass_delete_attempts():
    """
    Accepts form field 'aids' (list of attempt ids).
    Safety: refuse > MAX_SAFE_DELETE unless confirm_bulk=yes provided.
    """
    aids_raw = request.form.getlist("aids")
    if not aids_raw:
        flash("No attempts selected.", "danger")
        return redirect(url_for("teacher.manage_attempts"))

    # sanitize ids
    aids = []
    for x in aids_raw:
        try:
            aids.append(int(x))
        except Exception:
            continue

    if not aids:
        flash("No valid attempt ids provided.", "danger")
        return redirect(url_for("teacher.manage_attempts"))

    MAX_SAFE_DELETE = 20
    confirm_flag = request.form.get("confirm_bulk", "").lower() == "yes"
    if len(aids) > MAX_SAFE_DELETE and not confirm_flag:
        flash(f"You attempted to delete {len(aids)} attempts. For safety, confirm bulk delete.", "danger")
        return redirect(url_for("teacher.manage_attempts"))

    try:
        # bulk delete in single DB call
        deleted = Attempt.query.filter(Attempt.id.in_(aids)).delete(synchronize_session=False)
        db.session.commit()
        current_app.logger.info("Teacher %s deleted attempts: %s", current_user.id, aids)
        flash(f"Deleted {deleted} attempts.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Failed to delete attempts %s: %s", aids, e)
        flash("Failed to delete selected attempts.", "danger")

    return redirect(url_for("teacher.manage_attempts"))


# --- DELETE SINGLE ATTEMPT ---
@teacher_bp.route("/attempts/<int:aid>/delete", methods=["POST"])
@login_required
@teacher_required
def delete_attempt(aid):
    try:
        attempt = Attempt.query.get_or_404(int(aid))
    except Exception:
        flash("Invalid attempt id.", "danger")
        return redirect(url_for("teacher.manage_attempts"))

    try:
        db.session.delete(attempt)
        db.session.commit()
        current_app.logger.info("Teacher %s deleted attempt id=%s", current_user.id, aid)
        flash("Attempt deleted.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("Failed to delete attempt %s: %s", aid, e)
        flash("Could not delete attempt.", "danger")

    return redirect(url_for("teacher.manage_attempts"))
