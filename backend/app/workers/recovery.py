"""Stuck-task recovery helpers for the ARQ worker.

Manual recovery (v1)::

    from app.database.session import SessionLocal
    from app.services.task_service import TaskService
    from app.api.dependencies import get_repository_service
    from app.services.agent_run_service import AgentRunService

    session = SessionLocal()
    try:
        n = TaskService(
            session, get_repository_service(), AgentRunService(session)
        ).fail_stuck_running_tasks()
        print(f"marked {n} stuck task(s) failed")
    finally:
        session.close()

Optional later: wire ``fail_stuck_running_tasks`` as an ARQ cron job.
"""

from __future__ import annotations
