# quiz/modes/__init__.py
# Expose a simple dispatcher: get_question_for_mode(mode, current_diff, seen)
from .adaptive import mode_adaptive
from .challenger import mode_challenger
from .minuterush import mode_minuterush
from .firststrike import mode_firststrike
from .levelinfinity import mode_levelinfinity
from .common import get_pool_all, pick_question_near
import random

_dispatch = {
    "adaptive": mode_adaptive,
    "challenger": mode_challenger,
    "minuterush": mode_minuterush,
    "firststrike": mode_firststrike,
    "levelinfinity": mode_levelinfinity,
}

def get_question_for_mode(mode, current_diff, seen):
    mode = (mode or "").lower()
    fn = _dispatch.get(mode)
    if fn:
        try:
            q = fn(current_diff, seen)
            if q:
                return q
        except Exception:
            # fallthrough to fallback
            pass

    # fallback: return any question not in seen
    pool = get_pool_all(exclude_ids=seen)
    return random.choice(pool) if pool else None
