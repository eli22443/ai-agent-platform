from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


class RepositoryRecord(Base):
    __tablename__ = "repositories"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    url: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    default_branch: Mapped[str | None] = mapped_column(String)
    last_commit_sha: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class TaskRecord(Base):
    __tablename__ = "tasks"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    repository_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("repositories.id"), nullable=False
    )
    instruction: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    result: Mapped[str | None] = mapped_column(String)
    error: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index(
            "ix_agent_runs_task_id_started_at",
            "task_id",
            "started_at",
            postgresql_ops={"started_at": "DESC"},
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    halt_reason: Mapped[str | None] = mapped_column(String)
    iterations: Mapped[int | None] = mapped_column(Integer)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    result: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[list["ToolCallRecord"]] = relationship(
        back_populates="agent_run",
        order_by="ToolCallRecord.sequence",
    )


class ToolCallRecord(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        UniqueConstraint("agent_run_id", "sequence", name="uq_tool_calls_run_sequence"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    agent_run_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String, nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[str | None] = mapped_column(String)
    deduplicated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    agent_run: Mapped["AgentRunRecord"] = relationship(back_populates="tool_calls")
