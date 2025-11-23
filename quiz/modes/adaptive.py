# quiz/modes/adaptive.py
import logging
from extensions import db
from models import Question

logger = logging.getLogger(__name__)

def mode_adaptive(current_diff, seen):
    """
    Backwards-compatible selector used by dispatcher when picking a question.
    This function simply returns a question near current_diff excluding seen ids.
    We keep this simple because the main selection logic (deterministic) is done
    in handle_result when computing next question difficulty.
    """
    # fallback naive approach: pick first question with difficulty == current_diff not in seen
    try:
        q = Question.query.filter(Question.difficulty == current_diff).all()
        for candidate in q:
            if candidate.id not in (seen or []):
                return candidate
    except Exception:
        logger.exception("mode_adaptive fallback selector error")
    # final fallback: return any unseen question
    try:
        pool = Question.query.filter(~Question.id.in_(seen or [])).all()
        return pool[0] if pool else None
    except Exception:
        logger.exception("mode_adaptive final fallback failed")
        return None


def handle_result(attempt, question, correct, time_used=None):
    """
    Determine points and the next difficulty (strictly following the requested rules),
    and choose a candidate next question difficulty (the server will use that difficulty
    to serve the next question). Returns (points:int, adjustment:dict).

    Rules implemented:
      - WRONG OR time_used > 10  -> decrease difficulty by 1 (min 1)
      - CORRECT & time_used < 5  -> increase difficulty by 1 (max 10)
      - CORRECT & 5 <= time_used <= 10 -> same difficulty (closest)
      - If time_used is None, fallback to correctness-only: correct -> increase, wrong -> decrease
    Selection:
      - Try to pick a question with difficulty == next_diff and not in attempt's seen list.
      - If none exist, pick a question with the smallest absolute distance to next_diff
        (tie-breaker: prefer the lower difficulty, then lower id for determinism).
    """
    try:
        uid = getattr(attempt, "user_id", None)
        aid = getattr(attempt, "id", None)
        qid = getattr(question, "id", None)
        cur_diff = getattr(question, "difficulty", 3) or 3
        logger.info("Adaptive.handle_result user=%s attempt=%s q=%s correct=%s time_used=%s diff=%s",
                    uid, aid, qid, correct, time_used, cur_diff)
    except Exception:
        logger.exception("Adaptive.handle_result logging failed")
        cur_diff = getattr(question, "difficulty", 3) or 3

    # Basic points: correct -> 1, incorrect -> 0
    points = 1 if correct else 0

    # Normalize time_used
    t = None
    if time_used is not None:
        try:
            t = float(time_used)
        except Exception:
            t = None

    # Compute next_diff per rules
    if (not correct) or (t is not None and t > 10):
        next_diff = max(1, cur_diff - 1)
        rule = "wrong_or_over10"
    elif correct and (t is not None and t < 5):
        next_diff = min(10, cur_diff + 1)
        rule = "correct_under5"
    elif correct and (t is not None and 5 <= t <= 10):
        next_diff = cur_diff
        rule = "correct_5_10"
    else:
        # fallback when t is None: correctness drives change
        if correct:
            next_diff = min(10, cur_diff + 1)
            rule = "fallback_correct"
        else:
            next_diff = max(1, cur_diff - 1)
            rule = "fallback_wrong"

    # Build exclusion list from attempt.details if possible — attempt.details may contain prior qids
    seen_qids = []
    try:
        # attempt.details is JSON list of events added by Attempt.add_event
        import json
        if getattr(attempt, "details", None):
            evs = json.loads(attempt.details)
            for ev in evs:
                if ev and ev.get("qid") is not None:
                    try:
                        seen_qids.append(int(ev.get("qid")))
                    except Exception:
                        pass
    except Exception:
        logger.exception("error reading attempt.details for seen qids")
    # Also ensure the current question is treated as seen
    try:
        if getattr(question, "id", None) is not None:
            seen_qids.append(int(question.id))
    except Exception:
        pass

    # Normalize seen_qids -> unique ints
    try:
        seen_qids = sorted(set(int(x) for x in seen_qids if x is not None))
    except Exception:
        seen_qids = list(set(seen_qids))

    # Now select a candidate question for the computed next_diff (server-side deterministic selection)
    # 1) Try exact difficulty match first excluding seen
    candidate = None
    try:
        exact = Question.query.filter(
            Question.difficulty == next_diff,
            ~Question.id.in_(seen_qids)
        ).order_by(Question.id.asc()).all()
        if exact:
            candidate = exact[0]  # deterministic: lowest id
    except Exception:
        logger.exception("error querying exact difficulty candidates")

    # 2) If exact not found, pick question with smallest abs(diff - next_diff)
    if not candidate:
        try:
            # fetch all unseen questions and sort by closeness, prefer lower difficulty on ties, then lower id
            pool = Question.query.filter(~Question.id.in_(seen_qids)).all()
            if pool:
                # build list of (absdiff, prefer_lower_flag, difficulty, id, question)
                scored = []
                for p in pool:
                    d = p.difficulty or 0
                    absdiff = abs(d - next_diff)
                    prefer_lower = 0 if d <= next_diff else 1
                    scored.append( (absdiff, prefer_lower, d, p.id, p) )
                scored.sort(key=lambda x: (x[0], x[1], x[2], x[3]))  # deterministic
                candidate = scored[0][4]
        except Exception:
            logger.exception("error building fallback pool")

    # If still no candidate, return points and adjustment (no question available)
    adjustment = {"next_diff": next_diff, "time_factor": rule}
    if not candidate:
        logger.info("Adaptive.handle_result: no unseen candidate found after computing next_diff=%s seen=%s",
                    next_diff, seen_qids)
        return points, adjustment

    # Log which candidate we chose
    try:
        logger.info("Adaptive selected next candidate qid=%s diff=%s (requested diff=%s) rule=%s",
                    candidate.id, candidate.difficulty, next_diff, rule)
    except Exception:
        pass

    # We return the suggested next_diff (server uses it to return question choices).
    # Note: we don't mutate attempt here; the routes.submit_answer will record the event and update attempt.score.
    adjustment["chosen_qid"] = candidate.id
    adjustment["chosen_diff"] = candidate.difficulty
    adjustment["rule_applied"] = rule

    return points, adjustment
