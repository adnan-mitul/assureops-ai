"""Fixed-window admission limits shared across API instances (Redis), failing closed on overload only.

If Redis is unreachable the limiter allows the request (the database remains the
authority) but records nothing; per-batch size caps still apply.
"""

import time

import redis

from assureops_domain.config import settings

from .auth import api_error

_client = None


def _redis():
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings().redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
    return _client


def check(scope: str, key: str, limit: int, window_seconds: int):
    bucket = int(time.time() // window_seconds)
    name = f"ao:rl:{scope}:{key}:{bucket}"
    try:
        pipe = _redis().pipeline()
        pipe.incr(name)
        pipe.expire(name, window_seconds + 5)
        count = pipe.execute()[0]
    except redis.RedisError:
        return
    if count > limit:
        raise api_error(429, "rate_limited", f"{scope} limit of {limit} per {window_seconds}s reached; retry later")
