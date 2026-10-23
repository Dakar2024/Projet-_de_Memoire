"""Entry point of the Huey worker (`huey_consumer core.tasks.huey`).

A task is known to the worker only if its module was imported: list every feature's tasks here.
"""

import features.auth.tasks  # noqa: F401
from core.worker import huey

__all__ = ["huey"]
