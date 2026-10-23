from redis.asyncio import Redis

from core.settings import settings

# One connection pool for the whole process: Litestar's rate limit store and the auth counters.
# Connections open lazily, on first command.
redis_client: Redis = Redis.from_url(settings.REDIS_URL)
