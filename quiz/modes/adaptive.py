from .common import pick_question_near

def get_question(current_diff, seen):
    """
    Adaptive mode: tries to find questions matching the current skill level.
    """
    return pick_question_near(current_diff, exclude_ids=seen)

def handle_result(attempt, question, correct, time_used=None):
    """
    Adjust difficulty based on performance.
    """
    try:
        t = float(time_used or 0)
    except: t = 0

    cur = question.difficulty or 3
    nxt = cur

    if t > 10: # Too slow
        nxt = max(1, cur - 1)
        rule = "decrease_slow"
    elif not correct: # Wrong
        nxt = max(1, cur - 1)
        rule = "decrease_wrong"
    else: # Correct and fast enough
        nxt = min(10, cur + 1)
        rule = "increase"

    return (1 if correct else 0), {"next_diff": nxt, "rule": rule}