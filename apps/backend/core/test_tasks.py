from core.tasks import huey


def test_worker_registers_every_task():
    names = {name.rsplit(".", 1)[-1] for name in huey._registry._registry}
    assert {"send_email_task", "cleanup_expired_tokens", "purge_conversations_task"} <= names


def test_cleanup_runs_daily_at_three():
    periodic = {task.name.rsplit(".", 1)[-1]: task for task in huey._registry.periodic_tasks}
    validate = periodic["cleanup_expired_tokens"].validate_datetime
    from datetime import datetime

    assert validate(datetime(2026, 10, 23, 3, 0))
    assert not validate(datetime(2026, 10, 23, 4, 0))
