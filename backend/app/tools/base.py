from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel


@dataclass
class ToolResult:
    ok: bool
    data: dict | None
    truncated: bool = False
    error: str | None = None


@dataclass(frozen=True)
class ToolContext:
    workspace_root: Path


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    input_model: ClassVar[type[BaseModel]]
    mutating: ClassVar[bool] = False

    @abstractmethod
    def execute(self, context: ToolContext, arguments: BaseModel) -> ToolResult:
        """Run the tool. Failures return ToolResult(ok=False); do not raise for tool errors."""

    def json_schema(self) -> dict:
        schema = self.input_model.model_json_schema()
        schema["additionalProperties"] = False
        return schema
