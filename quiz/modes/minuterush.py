import random
from .common import get_pool_all

def get_question(current_diff, seen):
    """
    Minute Rush Mode:
    - Fetches questions randomly from the pool of unseen questions.
    - Does NOT adjust difficulty (pure random or can be set to random within range if desired).
    - Returns None if no questions left.
    """
    # 1. Get all unseen questions
    pool = get_pool_all(exclude_ids=seen)
    
    # 2. Return random choice or None
    return random.choice(pool) if pool else None

def handle_result(attempt, question, correct, time_used=None):
    """
    Minute Rush Scoring:
    - 1 point for correct.
    - No difficulty adjustment (keep it random or static).
    - No time penalty per question (time limit is global).
    """
    points = 1 if correct else 0
    
    # In Minute Rush, we don't typically change difficulty based on one question,
    # but if we wanted to make it progressively harder, we could return a higher next_diff.
    # For now, we return 'maintain' or random.
    # Returning empty dict means "keep current difficulty".
    
    return points, {}