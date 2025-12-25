import random
import json
from datetime import datetime
from models import Question
from extensions import db
from .common import get_pool_all

# ======================================================
# FIRST STRIKE MODE (Simplified)
# Rules:
# - One wrong answer ends the game immediately.
# - Questions are picked randomly from the pool of unseen questions.
# - No complex state storage needed, just standard "seen" tracking.
# ======================================================

def start_attempt(attempt):
    """
    Initialize First Strike attempt.
    """
    # Just set the timestamp. We don't need to pre-generate an order.
    attempt.started_at = datetime.utcnow()
    # Note: caller commits to DB

def get_question(attempt):
    """
    Get the next random question.
    """
    # 1. Check if we are already "dead" (finished)
    # We check the details log to see if the last answer was wrong.
    try:
        details = json.loads(attempt.details) if attempt.details else []
    except:
        details = []

    if details:
        last_event = details[-1]
        # If the last action was an answer (has 'correct' field) and it was False -> Game Over
        if 'correct' in last_event and not last_event['correct']:
             return {"finished": True, "message": "Game Over! You missed a question."}

    # 2. Get Seen IDs
    seen = set()
    for d in details:
        if d.get('qid'):
            seen.add(d.get('qid'))

    # 3. Pick Random Unseen Question
    pool = get_pool_all(exclude_ids=list(seen))
    
    if not pool:
        return {"finished": True, "message": "You answered all questions correctly! Impressive."}
        
    q = random.choice(pool)

    # 4. Return Payload
    try:
        opts = json.loads(q.options_json or "[]")
    except: opts = []

    return {
        "id": q.id,
        "prompt": q.prompt,
        "difficulty": q.difficulty,
        "options": opts,
        "qtype": q.qtype,
        "finished": False
    }

def submit_answer(attempt, question_id, selected, time_used):
    """
    Check answer. If wrong, the next call to get_question will see it and end the game.
    """
    q = Question.query.get(question_id)
    if not q: return {"error": "Question not found"}

    # --- Check Correctness ---
    try: opts = json.loads(q.options_json or "[]")
    except: opts = []
    
    id_map = {str(o.get('id')): str(o.get('text','')).lower() for o in opts}
    raw_correct = [str(x).strip() for x in (q.correct_answers or "").split(",") if x.strip()]
    
    correct_set = set()
    for rc in raw_correct:
        if rc in id_map: correct_set.add(id_map[rc])
        else: correct_set.add(rc.lower())
        
    user_set = set()
    for us in selected:
        us = str(us).strip()
        if us in id_map: user_set.add(id_map[us])
        else: user_set.add(us.lower())

    is_correct = (user_set == correct_set)

    # --- Update Score ---
    if is_correct:
        attempt.score = (attempt.score or 0) + 1
    else:
        # End immediately
        attempt.ended_at = datetime.utcnow()

    # --- Log Event ---
    try:
        details = json.loads(attempt.details) if attempt.details else []
    except: details = []
    
    details.append({
        "qid": q.id,
        "selected": selected,
        "correct": is_correct,
        "time_used": time_used,
        "timestamp": datetime.utcnow().isoformat()
    })
    
    attempt.details = json.dumps(details)
    # Caller commits

    return {
        "correct": is_correct,
        "finished": not is_correct, # Immediate feedback to frontend
        "attempt_score": attempt.score,
        "correct_answers": raw_correct
    }