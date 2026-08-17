
from app.services.task_service import TaskService

_task_service = TaskService()

def get_task_service() -> TaskService:
    return _task_service