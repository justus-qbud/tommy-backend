import os

import redis
from flask_limiter import Limiter


def create_redis_for_limiter():
    try:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        client = redis.Redis.from_url(redis_url)
        client.ping()
        return client
    except Exception:
        return None


LIMITER = Limiter(
    storage_uri=os.getenv("REDIS_URL", "redis://localhost:6379/0") if create_redis_for_limiter() else "memory://",
    storage_options={"socket_connect_timeout": 30},
    strategy="fixed-window",
    default_limits=["30 per minute"],
    swallow_errors=True
)

