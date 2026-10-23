from huey import RedisHuey

from core.settings import settings

# The worker loads core.tasks (not this module), which imports every feature's tasks.
huey = RedisHuey("app", url=settings.REDIS_URL)
