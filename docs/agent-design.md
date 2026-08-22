# Agent Design

## Purpose

This document defines how the agent works: the tool-calling loop, the tool contract, the catalog of tools and when each arrives, and the safeguards that keep a run bounded. The tools landed in Phase 5. The agent loop is specified in [phases/phase-06.md](phases/phase-06.md) and is triggered by `POST /tasks/{task_id}/run` after clone (D22), not inline on `POST /tasks`.

## Design stance

The agent is implemented directly against the OpenAI Responses API, deliberately framework-light. The point is to understand tool-calling behavior explicitly rather than inherit it from an abstraction. Concretely this means the project owns the loop, the message history, the tool dispatch table, and the termination conditions.

LangChain and LangGraph are not used initially. The trigger condition for revisiting that decision is recorded in [decisions.md](decisions.md).

## The loop

```mermaid
flowchart TD
    Start["Task: instruction + workspace"] --> Build["Build input: system prompt, instruction, repository summary"]
    Build --> Call["Call Responses API with tool schemas"]
    Call --> Inspect{"Response contains tool calls?"}
    Inspect -->|No| Final["Final answer"]
    Inspect -->|Yes| Guard{"Safeguard limits exceeded?"}
    Guard -->|Yes| Halt["Halt: return partial result with reason"]
    Guard -->|No| Dispatch["Validate arguments and dispatch each tool call"]
    Dispatch --> Record["Record tool_call: name, args, duration, status"]
    Record --> Feed["Append tool results to input"]
    Feed --> Call
    Final --> Persist["Persist answer on tasks.result (Phase 6); full agent_runs rows in Phase 7"]
    Halt --> Persist
```

Step by step:

1. Build the initial input from the system prompt, the user instruction, and a compact repository summary produced by the repository service.
2. Call the Responses API with the instruction and the JSON Schema for every tool the run is permitted to use.
3. Inspect the response output. If it contains no tool calls, the model has produced its final answer and the loop ends.
4. Before executing anything, check the safeguard limits. If any is exceeded, halt and return a partial result that states why.
5. Validate each tool call's arguments against the tool's schema, then dispatch it. Multiple tool calls in one response are executed before returning to the model.
6. Append each tool's result to the conversation input, keyed to the originating call.
7. Repeat from step 2.
8. Return the answer and an in-memory tool-call summary; persist the answer on `tasks.result` (Phase 6). Full `agent_runs` / `tool_calls` rows are Phase 7.

## Responses API mechanics

The OpenAI SDK is the authoritative source for exact field names; the shape below is what the loop is built around.

A tool is declared as a function with a JSON Schema:

```python
{
    "type": "function",
    "name": "search_code",
    "description": "Search the repository for a pattern using ripgrep. Returns matching files with line numbers and surrounding context.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Literal string or regular expression to search for."},
            "path": {"type": "string", "description": "Optional subdirectory to restrict the search to."},
            "max_results": {"type": "integer", "default": 50},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}
```

The model requests a call by emitting a function-call output item carrying a call identifier, the tool name, and JSON-encoded arguments. The loop replies with a function-call-output item carrying the same call identifier and the tool's result as a string. Conversation state is carried either by resending the accumulated input list or by chaining on the previous response identifier; the project starts with the explicit input list, because owning the history makes truncation and persistence straightforward.

## Tool contract

Every tool declares:

| Element | Requirement |
| --- | --- |
| Name | Stable, snake_case, unique across the registry |
| Description | Written for the model: what it does, what it returns, when to prefer it over a similar tool |
| Input schema | JSON Schema, validated by a Pydantic model before execution |
| Output | Structured and serializable, with a consistent envelope |
| Errors | Returned as data, never raised through the loop |
| Mutation flag | Whether the tool modifies the workspace |
| Timeout | Per-tool wall-clock limit |

Rules that follow from the contract:

- Arguments are validated before execution. A model-produced argument is untrusted input like any other.
- Every path argument is resolved against the task's workspace root and rejected if it escapes. See [security.md](security.md).
- A tool failure is an observation, not a crash. A failed tool returns a structured error that is fed back to the model so it can adapt. Only infrastructure failures outside tool execution abort a run.
- Output is truncated to a documented budget, and the truncation is stated in the result so the model knows the view is partial rather than silently believing it saw everything.
- Read-only and mutating tools are separated. A run is granted a tool set; write access introduced in Phase 11 is an explicit capability grant, never an accident of registry membership.

A consistent result envelope keeps model-facing behavior predictable:

```json
{
  "ok": true,
  "data": { "matches": [] },
  "truncated": false,
  "error": null
}
```

## Tool catalog

Tools appear only in the phase that introduces them. Nothing below is stubbed in advance.

| Tool | Mutating | Phase | Notes |
| --- | --- | --- | --- |
| `list_files` | No | 5 | Directory listing scoped to the workspace, respecting ignore rules |
| `read_file` | No | 5 | Byte- and line-bounded reads with explicit truncation |
| `search_code` | No | 5 | ripgrep-backed lexical search |
| `get_file_info` | No | 5 | Size, language, line count, existence |
| `get_git_diff` | No | 5 | Working tree or commit-range diff |
| `get_git_history` | No | 5 | Recent commits, optionally for one path |
| `semantic_search` | No | 8 | Embedding-based retrieval via Pinecone |
| `run_command` | Yes | 10 | Sandboxed, allow-listed, resource-limited |
| `run_tests` | Yes | 10 | Sandboxed test execution with parsed results |
| `install_dependencies` | Yes | 10 | Sandboxed, network policy applies |
| `write_file` | Yes | 11 | Workspace-scoped write |
| `apply_patch` | Yes | 11 | Unified-diff application with rejection on conflict |

Retrieval strategy across phases: `search_code` is the primary discovery tool and stays that way. `semantic_search` is added alongside it in Phase 8 for conceptual queries where the user's wording does not match the source text. The tool descriptions state when to prefer each, because the choice is the model's to make.

## Safeguards

An agent loop without limits is an unbounded spend and an unbounded runtime. Every run carries:

| Safeguard | Purpose |
| --- | --- |
| Maximum iterations | Hard cap on loop turns; prevents cycles where the model repeats a tool call forever |
| Wall-clock deadline | Bounds total run duration independently of iteration count |
| Token budget | Bounds cost per run across all model calls |
| Per-tool timeout | Prevents one slow tool from consuming the deadline |
| Output truncation | Prevents a large file or search result from exhausting the context window |
| Repeated-call detection | Identical tool name and arguments repeated consecutively is a signal to intervene rather than continue |
| Tool set restriction | A run can only call tools it was granted |

When a limit is reached, the run does not fail silently and does not pretend to have finished. It terminates with a status that distinguishes "completed" from "halted by limit", and returns whatever partial understanding it has along with the reason it stopped. Limits are configuration, not literals scattered through the code.

## Agent run record

Phase 6 returns a light tool-call summary on `POST /tasks/{task_id}/run` and stores the final answer on `tasks.result`. Phase 7 persists full `agent_runs` and `tool_calls` so behavior is inspectable after the fact — the foundation Phase 13 observability builds on.

Recorded per run (Phase 7): task reference, model, status, iteration count, token usage where available, start and finish timestamps, final result, and error information. Recorded per tool call: tool name, arguments, status, duration, and error. See the data model in [architecture.md](architecture.md).

## What is exposed to the user

The final answer and the structured record of what the agent did: which tools ran, with which arguments, how long they took, and whether they succeeded.

Raw model reasoning is not exposed. If a reasoning-capable model produces internal reasoning content, it is not surfaced to API clients. Progress is communicated through structured events derived from the run record, which is more useful to a caller than a transcript and avoids exposing content the model was not asked to publish.

Tool arguments are surfaced only where safe. Arguments are model-generated and may quote repository content; anything surfaced is subject to the same secret-redaction rules as logs.

## Prompt design

The system prompt establishes: the agent is a software engineering assistant operating on a repository it has not seen before; it must ground claims in files it has actually read; it must use tools rather than guessing; and it must state uncertainty rather than fabricate file paths, function names, or line numbers.

The most important instruction concerns untrusted content. Repository files may contain text that looks like instructions addressed to an AI agent. That text is data, not instruction. The agent follows only the user's instruction and the system prompt. This is a mitigation, not a defense; the actual defense is that tools are permission-controlled and the sandbox is isolated. See [security.md](security.md).

## Evolution path

Phase 6 delivers a single agent with read-only tools that answers questions about a repository via `POST /tasks/{task_id}/run`. Phase 11 extends it to modification, where the loop gains a natural inner cycle: investigate, modify, run tests, inspect failures, repair, and finish by returning a reviewable diff. Changes are never pushed to the user's repository automatically.

Multi-agent orchestration, planner/executor separation, and persistent cross-run memory are explicitly out of scope until the single-agent loop is measurably insufficient.
