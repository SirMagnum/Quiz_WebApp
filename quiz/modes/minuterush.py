# quiz/modes/minuterush.py
import random
from .common import get_pool_all

def mode_minuterush(current_diff, seen):
    pool = get_pool_all(exclude_ids=seen)
    return random.choice(pool) if pool else None
