from __future__ import annotations

from pydantic import ValidationError

from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.filesystem import GetFileInfoTool, ListFilesTool, ReadFileTool
from app.tools.git import GetGitDiffTool, GetGitHistoryTool
from app.tools.search import SearchCodeTool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_schemas(self) -> list[dict]:
        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.json_schema(),
            }
            for tool in self._tools.values()
        ]

    def execute(
        self, name: str, context: ToolContext, arguments: dict
    ) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(ok=False, data=None, error=f"unknown tool: {name}")

        try:
            parsed = tool.input_model.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(
                ok=False,
                data=None,
                error=_validation_error_message(exc),
            )

        return tool.execute(context, parsed)


def build_read_only_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (
        ListFilesTool(),
        ReadFileTool(),
        GetFileInfoTool(),
        SearchCodeTool(),
        GetGitDiffTool(),
        GetGitHistoryTool(),
    ):
        registry.register(tool)
    return registry


def _validation_error_message(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "invalid tool arguments"
    first = errors[0]
    loc = ".".join(str(part) for part in first.get("loc", ()))
    msg = first.get("msg", "invalid value")
    if loc:
        return f"invalid arguments: {loc}: {msg}"
    return f"invalid arguments: {msg}"
