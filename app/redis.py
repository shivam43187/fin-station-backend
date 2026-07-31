import os
from upstash_redis import Redis

UPSTASH_REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL", "")
UPSTASH_REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

redis_client = Redis(
    url=UPSTASH_REDIS_REST_URL,
    token=UPSTASH_REDIS_REST_TOKEN,
)


class RedisCache:
    @staticmethod
    def get(key: str):
        return redis_client.get(key)

    @staticmethod
    def set(key: str, value, ex: int | None = None):
        """
        ex = expiration time in seconds
        """
        if ex:
            return redis_client.set(key, value, ex=ex)
        return redis_client.set(key, value)

    @staticmethod
    def delete(key: str):
        return redis_client.delete(key)

    @staticmethod
    def exists(key: str):
        return redis_client.exists(key)
