import logging
from extensions import db
from models import Question

logger = logging.getLogger(__name__)

def get_question(current_diff, seen):
    """
    Selects the next question based on the calculated current_diff.
    """
    # 1. Try exact difficulty match first
    candidate = Question.query.filter(
        Question.difficulty == current_diff,
        ~Question.id.in_(seen or [])
    ).first()

    if candidate:
        return candidate

    # 2. Fallback: Find closest difficulty
    pool = Question.query.filter(~Question.id.in_(seen or [])).all()
    
    if not pool:
        return None

    # Sort Priority:
    # 1. Abs Distance to target (find closest)
    # 2. Actual Difficulty (ascending) -> If diff 2 and 4 are both dist 1 from 3, pick 2.
    # 3. ID (deterministic tie-breaker)
    pool.sort(key=lambda q: (
        abs((q.difficulty or 1) - current_diff), 
        q.difficulty, 
        q.id
    ))
    
    return pool[0]


def handle_result(attempt, question, correct, time_used=None):
    """
    Calculates the next difficulty based on specific time/accuracy rules.
    Returns: (points, adjustment_dict)
    """
    # Current difficulty level (default to 3 if unknown)
    cur_diff = getattr(question, "difficulty", 3) or 3
    
    # Normalize time_used safely
    try:
        t = float(time_used) if time_used is not None else 0.0
    except (ValueError, TypeError):
        t = 0.0

    next_diff = cur_diff
    rule_applied = "maintain"

    # --- RULE IMPLEMENTATION ---

    # 1. Decrease: Wrong Answer OR Time > 10s
    if (not correct) or (t > 10):
        next_diff = max(1, cur_diff - 1)
        rule_applied = "decrease_wrong_or_slow"

    # 2. Increase: Correct Answer AND Time < 5s
    elif correct and t < 5:
        next_diff = min(10, cur_diff + 1)
        rule_applied = "increase_fast_correct"

    # 3. Maintain: Correct Answer AND 5s <= Time <= 10s
    # (Implicit else from above logic coverage)
    else:
        next_diff = cur_diff
        rule_applied = "maintain_medium_pace"

    # ---------------------------

    points = 1 if correct else 0

    logger.info(
        "Adaptive: correct=%s time=%.2fs | old_diff=%s -> new_diff=%s | rule=%s",
        correct, t, cur_diff, next_diff, rule_applied
    )

    adjustment = {
        "next_diff": next_diff,
        "rule_applied": rule_applied
    }

    return points, adjustment