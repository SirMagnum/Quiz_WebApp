# quiz/modes/firststrike.py
import random
from models import Question

def mode_firststrike(current_diff, seen):
    pool = Question.query.filter(Question.difficulty <= 5).all()
    pool = [q for q in pool if q.id not in seen]
    pool = pool or Question.query.all()
    return random.choice(pool) if pool else None
