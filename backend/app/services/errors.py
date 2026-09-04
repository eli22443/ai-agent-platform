class TaskNotFound(Exception):
    pass


class TaskNotRunnable(Exception):
    """Task cannot be run (wrong status or missing workspace)."""

    def __init__(self, message: str = "Task not runnable.") -> None:
        self.message = message
        super().__init__(message)


class AgentRunNotFound(Exception):
    pass


class RetrievalError(Exception):
    """Indexing or vector-store failure. Message is safe to surface upstream."""

    def __init__(self, message: str = "Semantic index failed.") -> None:
        self.message = message
        super().__init__(message)
