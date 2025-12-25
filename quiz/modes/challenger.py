import random
from models import Question
from .common import pick_question_near

def get_question(current_diff, seen):
    """
    Challenger: Stick to the difficulty, fallback if needed.
    """
    # Strict filter first
    pool = Question.query.filter_by(difficulty=current_diff).all()
    valid = [q for q in pool if q.id not in seen]
    
    if valid:
        return random.choice(valid)
        
    return pick_question_near(current_diff, seen)