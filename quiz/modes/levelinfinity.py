import random
from .common import get_pool_all

def get_question(current_diff, seen):
    """
    Level Infinity Mode:
    - Randomly selects questions.
    - No time limit (handled by client/routes not enforcing one).
    - If all questions have been seen, it DOES NOT end. 
      It simply picks a random question from the entire pool again.
    """
    # 1. Try to get unseen questions first
    pool = get_pool_all(exclude_ids=seen)
    
    if pool:
        return random.choice(pool)
    
    # 2. If pool is empty (all seen), fetch ALL questions to repeat
    # We pass empty exclude list to get everything
    full_pool = get_pool_all(exclude_ids=[])
    
    if full_pool:
        # We return a random question to keep the game going
        return random.choice(full_pool)
        
    return None

def handle_result(attempt, question, correct, time_used=None):
    """
    Level Infinity Scoring:
    - Standard scoring.
    - No difficulty adjustment needed for this logic, 
      but could be added if desired.
    """
    points = 1 if correct else 0
    return points, {}