from __future__ import annotations

import redis

from .config import settings


class QueueClient:
    def __init__(self) -> None:
        self.redis = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        self.key = settings.queue_key

    def enqueue(self, task_id: str) -> None:
        self.redis.lpush(self.key, task_id)

    def dequeue(self, timeout: int = 10) -> str | None:
        item = self.redis.brpop(self.key, timeout=timeout)
        if not item:
            return None
        return item[1]


queue_client = QueueClient()

