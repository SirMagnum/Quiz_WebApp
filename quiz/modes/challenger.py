# quiz/modes/challenger.py
import random
from models import Question
from .common import pick_question_near

def mode_challenger(current_diff, seen):
    pool = Question.query.filter_by(difficulty=current_diff).all()
    pool = [q for q in pool if q.id not in seen]
    if pool:
        return random.choice(pool)
    return pick_question_near(current_diff, exclude_ids=seen)
