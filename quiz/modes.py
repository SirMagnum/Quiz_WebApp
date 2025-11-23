# quiz/modes.py
# Modular mode handlers for the quiz app.
# Each function is small and focused so adding/updating a mode is simple.

import random
from extensions import db
from models import Question

def pick_question_near(diff, exclude_ids=None):
    exclude_ids = exclude_ids or []
    low = max(1, diff - 1)
    high = min(10, diff + 1)
    pool = Question.query.filter(Question.difficulty.between(low, high)).all()
    pool = [q for q in pool if q.id not in exclude_ids]
    if not pool:
        pool = [q for q in Question.query.all() if q.id not in exclude_ids]
    if not pool:
        return None
    return random.choice(pool)

def get_pool_all(exclude_ids=None):
    exclude_ids = exclude_ids or []
    pool = [q for q in Question.query.all() if q.id not in exclude_ids]
    if not pool:
        pool = Question.query.all()
    return pool

def mode_adaptive(current_diff, seen):
    return pick_question_near(current_diff, exclude_ids=seen)

def mode_challenger(current_diff, seen):
    pool = Question.query.filter_by(difficulty=current_diff).all()
    pool = [q for q in pool if q.id not in seen]
    if pool:
        return random.choice(pool)
    return pick_question_near(current_diff, exclude_ids=seen)

def mode_minuterush(current_diff, seen):
    pool = get_pool_all(exclude_ids=seen)
    return random.choice(pool) if pool else None

def mode_firststrike(current_diff, seen):
    pool = Question.query.filter(Question.difficulty <= 5).all()
    pool = [q for q in pool if q.id not in seen]
    pool = pool or Question.query.all()
    return random.choice(pool) if pool else None

def mode_levelinfinity(current_diff, seen):
    pool = Question.query.filter(Question.qtype.in_(["multiple", "reverse", "single"])).all()
    pool = [q for q in pool if q.id not in seen]
    pool = pool or Question.query.all()
    return random.choice(pool) if pool else None

# Dispatcher
def get_question_for_mode(mode, current_diff, seen):
    """
    Returns a Question instance (or None).
    mode: canonical string: adaptive, challenger, minuterush, firststrike, levelinfinity
    """
    mode = (mode or "").lower()
    if mode == "adaptive":
        return mode_adaptive(current_diff, seen)
    if mode == "challenger":
        return mode_challenger(current_diff, seen)
    if mode == "minuterush":
        return mode_minuterush(current_diff, seen)
    if mode == "firststrike":
        return mode_firststrike(current_diff, seen)
    if mode == "levelinfinity":
        return mode_levelinfinity(current_diff, seen)
    # fallback
    pool = get_pool_all(exclude_ids=seen)
    return random.choice(pool) if pool else None
