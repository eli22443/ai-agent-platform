
from app.services.task_service import TaskService
from app.database.session import get_db
from sqlalchemy.orm import Session
from fastapi import Depends


def get_task_service(db: Session = Depends(get_db)) -> TaskService:
    return TaskService(db)