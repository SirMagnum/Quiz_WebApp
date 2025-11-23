# quiz/modes/common.py
import random
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
