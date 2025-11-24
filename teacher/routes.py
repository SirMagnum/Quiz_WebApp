from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from models import Question, User, Role, Attempt
import json
from functools import wraps
from sqlalchemy import func
import collections

teacher_bp = Blueprint("teacher", __name__)

# --- ROLE CHECK ---
def teacher_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Ensure current_user has a role attribute and is teacher
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
    Teacher dashboard: shows counts, students table, average scores.
    """
    qcount = Question.query.count()
    ucount = User.query.count()
    
    # List students
    students = User.query.filter(User.role == Role.STUDENT).order_by(User.id.desc()).all()
    
    # Prepare attempts per student (id -> list of Attempt)
    attempts = Attempt.query.all()
    s_attempts = {}
    for a in attempts:
        s_attempts.setdefault(a.user_id, []).append(a)
        
    # Compute average score per student (None or float)
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


# --- QUESTIONS MANAGEMENT ---
@teacher_bp.route("/questions")
@login_required
@teacher_required
def questions():
    qs = Question.query.order_by(Question.created_at.desc()).all()
    return render_template("teacher_questions.html", questions=qs)


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
        flash("Please fill required fields.", "danger")
        return redirect(url_for("teacher.questions"))

    # Normalize difficulty
    try:
        diff = int(difficulty)
    except:
        diff = 1
    diff = max(1, min(10, diff))

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


@teacher_bp.route("/questions/<int:qid>/edit", methods=["GET", "POST"])
@login_required
@teacher_required
def edit_question(qid):
    q = Question.query.get_or_404(qid)
    
    if request.method == "POST":
        prompt = request.form.get("prompt")
        opt1 = request.form.get("opt1")
        opt2 = request.form.get("opt2")
        opt3 = request.form.get("opt3")
        opt4 = request.form.get("opt4")
        correct = request.form.get("correct")
        diff = request.form.get("difficulty") or 3
        qtype = request.form.get("qtype") or "single"

        try:
            diff_i = int(diff)
        except:
            diff_i = 1
        diff_i = max(1, min(10, diff_i))

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

    # GET Request: Prepare data for form
    try:
        opt_list = json.loads(q.options_json)
    except Exception:
        opt_list = []
    opt_texts = [o.get("text", "") for o in opt_list]
    while len(opt_texts) < 4:
        opt_texts.append("")
        
    return render_template("edit_question.html", q=q, opt_texts=opt_texts)


@teacher_bp.route("/questions/<int:qid>/delete", methods=["POST"])
@login_required
@teacher_required
def delete_question(qid):
    q = Question.query.get_or_404(qid)
    db.session.delete(q)
    db.session.commit()
    flash("Question deleted.", "success")
    return redirect(url_for("teacher.questions"))


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


@teacher_bp.route("/upload_excel", methods=["POST"])
@login_required
@teacher_required
def upload_excel():
    try:
        import openpyxl
    except Exception:
        flash("openpyxl is required for Excel upload.", "danger")
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
            if i == 1: continue # skip header

            # Unpack row safely
            row_list = list(row) + [None] * 7
            qtxt, op1, op2, op3, op4, correct, difficulty = row_list[:7]

            if not qtxt or not op1 or not op2 or not correct:
                continue

            try:
                diff_i = int(difficulty) if difficulty is not None else 1
            except:
                diff_i = 1
            diff_i = max(1, min(10, diff_i))

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
                new_q = Question(
                    prompt=str(qtxt),
                    options_json=json.dumps(options, ensure_ascii=False),
                    correct_answers=str(correct),
                    qtype="single",
                    difficulty=diff_i
                )
                db.session.add(new_q)
                added += 1

        db.session.commit()
        flash(f"Upload complete! Added: {added} · Updated: {updated}", "success")

    except Exception as e:
        flash(f"Import failed: {str(e)}", "danger")

    return redirect(url_for("teacher.questions"))


# --- STUDENT MANAGEMENT ---
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


@teacher_bp.route("/students/<int:uid>/delete", methods=["POST"])
@login_required
@teacher_required
def delete_student(uid):
    u = User.query.get_or_404(uid)

    if u.role != Role.STUDENT:
        flash("Cannot delete a non-student user.", "danger")
        return redirect(url_for("teacher.dashboard"))

    # Delete related attempts to avoid integrity errors
    Attempt.query.filter_by(user_id=u.id).delete()
    db.session.delete(u)
    db.session.commit()
    flash(f"Student '{u.username}' deleted.", "success")
    return redirect(url_for("teacher.dashboard"))


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


# --- ANALYTICS LOGIC ---
def get_analytics_data():
    """Helper to gather analytics data for both view and JSON API."""
    total_attempts = Attempt.query.count()
    avg_score_row = db.session.query(func.avg(Attempt.score)).scalar() or 0
    avg_score = round(float(avg_score_row), 2)

    # Per-mode stats
    modes = db.session.query(Attempt.mode, func.count(Attempt.id), func.avg(Attempt.score)).group_by(Attempt.mode).all()
    per_mode = [{"mode": m[0] or "unknown", "count": int(m[1]), "avg": round(float(m[2] or 0), 2)} for m in modes]

    # Question-level accuracy
    q_stats = {}
    all_attempts = Attempt.query.filter(Attempt.details.isnot(None)).all()
    for a in all_attempts:
        try:
            events = json.loads(a.details)
        except Exception:
            continue
        for ev in events:
            qid = ev.get("qid")
            if not qid: continue
            rec = q_stats.setdefault(qid, {"seen": 0, "correct": 0})
            rec["seen"] += 1
            if ev.get("correct"):
                rec["correct"] += 1

    question_info = []
    if q_stats:
        qids = list(q_stats.keys())
        qs = Question.query.filter(Question.id.in_(qids)).all()
        qmap = {q.id: q for q in qs}
        for qid, rec in q_stats.items():
            q = qmap.get(qid)
            prompt = q.prompt if q else f"Q {qid}"
            diff = q.difficulty if q else 1
            acc = round((rec["correct"] / rec["seen"]) * 100, 1) if rec["seen"] else 0.0
            question_info.append({
                "qid": qid,
                "prompt": (prompt[:60] + "...") if len(prompt) > 60 else prompt,
                "difficulty": diff,
                "seen": rec["seen"],
                "correct": rec["correct"],
                "accuracy": acc
            })

    # Difficulty distribution
    diff_buckets = {i: {"seen": 0, "correct": 0} for i in range(1, 11)}
    for item in question_info:
        d = item["difficulty"]
        d = max(1, min(10, d))
        diff_buckets[d]["seen"] += item["seen"]
        diff_buckets[d]["correct"] += item["correct"]

    diff_list = []
    for d in range(1, 11):
        s = diff_buckets[d]["seen"]
        c = diff_buckets[d]["correct"]
        acc = round((c / s) * 100, 1) if s else None
        diff_list.append({"difficulty": d, "seen": s, "accuracy": acc})

    # Sort for top/bottom questions
    top_questions = sorted(question_info, key=lambda x: (-x["accuracy"], -x["seen"]))[:5]
    bottom_questions = sorted(question_info, key=lambda x: (x["accuracy"], -x["seen"]))[:5]

    return {
        "total_attempts": total_attempts,
        "avg_score": avg_score,
        "per_mode": per_mode,
        "diff_list": diff_list,
        "top_questions": top_questions,
        "bottom_questions": bottom_questions
    }

@teacher_bp.route("/analytics")
@login_required
@teacher_required
def analytics():
    """Render analytics page."""
    data = get_analytics_data()
    return render_template("teacher_analytics.html", **data)

@teacher_bp.route("/analytics/data")
@login_required
@teacher_required
def analytics_json():
    """Return analytics data as JSON for JS dashboard."""
    data = get_analytics_data()
    return jsonify(data)


# --- ATTEMPTS MANAGEMENT ---
@teacher_bp.route("/attempts/manage")
@login_required
@teacher_required
def manage_attempts():
    """
    Manage attempts page.
    Optional 'uid' param to filter by specific student.
    """
    uid = request.args.get("uid", type=int)
    users = {u.id: u.username for u in User.query.all()}

    if uid:
        # Show attempts for specific student
        student = User.query.get_or_404(uid)
        attempts = Attempt.query.filter_by(user_id=uid).order_by(Attempt.started_at.desc()).all()
        return render_template("teacher_manage_attempts.html", 
                               attempts=attempts, 
                               user_cache=users, 
                               filtered_student=student)
    else:
        # Summary view (list of students with attempt counts)
        counts = db.session.query(Attempt.user_id, func.count(Attempt.id)).group_by(Attempt.user_id).all()
        counts_map = {r[0]: r[1] for r in counts}
        students = User.query.order_by(User.username).all()
        
        return render_template("teacher_manage_attempts.html", 
                               attempts=[], 
                               user_cache=users, 
                               students=students, 
                               counts_map=counts_map, 
                               filtered_student=None)


@teacher_bp.route("/attempts/mass_delete", methods=["POST"])
@login_required
@teacher_required
def mass_delete_attempts():
    aids = request.form.getlist("aids")
    if not aids:
        flash("No attempts selected.", "danger")
        return redirect(url_for("teacher.manage_attempts"))

    try:
        safe_aids = [int(x) for x in aids]
        Attempt.query.filter(Attempt.id.in_(safe_aids)).delete(synchronize_session=False)
        db.session.commit()
        flash(f"Deleted {len(safe_aids)} attempts.", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Mass delete error: {e}")
        flash("Error deleting attempts.", "danger")

    return redirect(url_for("teacher.manage_attempts"))


@teacher_bp.route("/attempts/<int:aid>/delete", methods=["POST"])
@login_required
@teacher_required
def delete_attempt(aid):
    try:
        a = Attempt.query.get_or_404(aid)
        db.session.delete(a)
        db.session.commit()
        flash("Attempt deleted.", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error deleting attempt.", "danger")
        
    return redirect(url_for("teacher.manage_attempts"))


@teacher_bp.route("/attempts/student/<int:uid>/delete_all", methods=["POST"])
@login_required
@teacher_required
def delete_student_attempts(uid):
    try:
        Attempt.query.filter_by(user_id=uid).delete()
        db.session.commit()
        flash("All logs wiped for student.", "success")
    except Exception as e:
        db.session.rollback()
        flash("Error wiping student logs.", "danger")
        
    return redirect(url_for("teacher.manage_attempts"))