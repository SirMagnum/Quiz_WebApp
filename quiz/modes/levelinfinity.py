# quiz/modes/levelinfinity.py
import random
from models import Question

def mode_levelinfinity(current_diff, seen):
    pool = Question.query.filter(Question.qtype.in_(["multiple", "reverse", "single"])).all()
    pool = [q for q in pool if q.id not in seen]
    pool = pool or Question.query.all()
    return random.choice(pool) if pool else None
