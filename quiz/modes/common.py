import random
from models import Question

def get_pool_all(exclude_ids=None):
    """
    Get all questions, excluding specific IDs.
    """
    exclude_ids = exclude_ids or []
    # Optimization: If exclude list is empty, don't filter
    if not exclude_ids:
        return Question.query.all()
    
    # Filter in Python to avoid complex IN clauses if list is huge, 
    # but for typical quiz app SQL filter is fine.
    # We use a list comprehension for robust excluding.
    all_q = Question.query.all()
    pool = [q for q in all_q if q.id not in exclude_ids]
    return pool

def pick_question_near(diff, exclude_ids=None):
    """
    Pick a question near the target difficulty.
    """
    exclude_ids = exclude_ids or []
    
    # Try exact match
    pool = Question.query.filter_by(difficulty=diff).all()
    valid_pool = [q for q in pool if q.id not in exclude_ids]
    
    if valid_pool:
        return random.choice(valid_pool)

    # Try +/- 1 range
    low = max(1, diff - 1)
    high = min(10, diff + 1)
    pool = Question.query.filter(Question.difficulty.between(low, high)).all()
    valid_pool = [q for q in pool if q.id not in exclude_ids]
    
    if valid_pool:
        return random.choice(valid_pool)

    # Fallback to anything available
    return random.choice(get_pool_all(exclude_ids)) if get_pool_all(exclude_ids) else None