# Agent Optimization Notes (Phase 6)

Lessons from live agent testing against real repos (`psf/requests`, `encode/httpx`) while hardening the Phase 6 agent loop (originally via `POST /tasks/{task_id}/run`; Phase 9 runs the same loop in the worker). Companion to [agent-design.md](agent-design.md) and [phases/phase-06.md](phases/phase-06.md).

## Goals

- Fewer wasted iterations and token spend
- Reliable completion (real answers, not empty `max_iterations` halt text)
- Correct Responses API conversation replay for reasoning models (`gpt-5*`)
- Observable mid-run status (`running` in the DB)

## Problems observed

### 1. Status never showed `running`

`TaskService.run` set `running` with `flush()` only. `get_db()` commits after the route returns, so external DB clients only saw `pending` → `completed`. Interrupted mid-run runs rolled back to `pending`.

**Fix:** commit immediately after setting `running`, before `run_agent()`.

### 2. Token / iteration burn

Explicit conversation history resends growing tool outputs every turn. Broad instructions + weak “stop when done” prompting led to 15–20 LLM turns, rate limits (429), and ~300K input tokens on incomplete runs.

**Mitigations:**

- Default `AGENT_MAX_ITERATIONS` lowered (10)
- Stronger system prompt: targeted tools, obey constraints, finalize early
- Near-cap budget nudge in the loop when ≤2 iterations remain

### 3. `read_file` without pagination

`sessions.py` (~920 lines) exceeds `TOOL_READ_MAX_LINES` (500). Re-reading the same path without an offset returned the identical first window; answers hedged with “not shown here.”

**Fix:** `start_line` on `read_file`, return `total_lines`, prompt to continue with `start_line=end_line+1`.

### 4. Bad / empty paths

Model passed `path=""` (overriding defaults) or guessed `requests/` instead of `src/requests/…`, burning turns on failures.

**Fix:** `min_length=1` on path fields; prompt to use `"."` / omit default, list or search from `"."` after failures, don’t keep guessing prefixes.

### 5. Redundant tool calls

Even with history present, mini models re-issued the same `read_file` / failed search. Prompt alone was soft.

**Fix:** per-run `DispatchCache`:

- Exact dedupe of `(name, canonical args)` → short “already ran” observation (includes prior error)
- Near-duplicate `read_file` windows (same path, `start_line` within 50 lines)

Note: dedupe does **not** reduce `iterations` (each tool-calling model turn still counts). It avoids re-executing tools and re-injecting large file bodies into the next prompt.

### 6. Reasoning models 400 on turn 2

With `gpt-5-mini` / `gpt-5.4-mini`, Responses API returns a `reasoning` item paired with `function_call`. The loop only replayed function calls →:

`function_call was provided without its required reasoning item`

**Fix:** echo `reasoning` + `function_call` items (in order) before `function_call_output`s. Surface `BadRequestError` detail in `LLMError`.

### 7. Config vs `.env` confusion

Changing `config.py` defaults did not change the live model while `OPENAI_MODEL=gpt-4.1-mini` remained in `backend/.env` (wins via pydantic-settings). Usage dashboard correctly showed only `gpt-4.1-mini` until `.env` was updated and the server restarted (`get_settings` is cached).

### 8. Uvicorn `--reload` + workspaces

Cloning into `.workspaces/` can trigger WatchFiles reload mid-request. Prefer excluding `.workspaces` from the reloader for stable local runs.

## Prompt rules that helped

See `backend/app/agent/prompts.py`. High-signal additions:

- Prefer search for symbols, then one `read_file` near the hit; don’t page whole files unless asked
- Paths relative to workspace root as shown by `list_files` (often under `src/`)
- Never empty paths; obey explicit user constraints (“only read X”)
- Reuse prior tool results; paginate truncated reads with `start_line=end_line+1`
- Stop tools and write a final answer once evidence is enough

## Model comparison (same cookie-trace style task)

| Model | Typical iterations | Notes |
| --- | --- | --- |
| `gpt-4.1-mini` | ~9–10 | Often path flailing / over-reading; sometimes empty halt |
| `gpt-5-mini` | ~9 | Needs reasoning replay; deep answers once fixed |
| `gpt-5.4-mini` | ~4 | Best efficiency for these Q&A traces; strong default candidate |

HttpX “Client vs one-off” with module constraint: `gpt-5.4-mini` finished in ~4 turns staying in `_client.py`.

**Recommendation:** default to `gpt-5.4-mini` for quality/turn efficiency; keep `gpt-5-mini` if optimizing for lower list price. Always set the model in `.env` (`OPENAI_MODEL=...`).

## Useful test instructions

```text
Trace how cookies set on a response get stored on a Session. Name the key functions.
```

```text
Explain how Client differs from a one-off request in httpx. Read the main client module only.
```

```text
Search for extract_cookies_to_jar under src/requests and explain how response cookies reach Session.cookies.
```

Tighter instructions finish faster; broad “architecture overview” invites iteration burn.

## Checking cost

- Live spend: [OpenAI Usage dashboard](https://platform.openai.com) → Usage (filter by model / export CSV). Help: [export usage/cost](https://help.openai.com/en/articles/20001072-how-do-i-export-monthly-usage-details-from-the-api-usage-dashboard).
- List prices: [Pricing](https://developers.openai.com/api/docs/pricing), e.g. [gpt-5.4-mini](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
- Programmatic: [Usage & Cost API cookbook](https://developers.openai.com/cookbook/examples/completions_usage_api).
- App persists per-run token usage on `agent_runs` (Phase 7); currency cost estimation can layer on those columns.

Rough cost: mostly **input** tokens (history + tool outputs × turns). Fewer iterations usually beats a slightly cheaper model that wanders.

## Code touchpoints

| Area | Location |
| --- | --- |
| Loop + reasoning replay + budget nudge | `backend/app/agent/loop.py` |
| Tool dedupe cache | `backend/app/agent/dispatch.py` |
| System prompt | `backend/app/agent/prompts.py` |
| `read_file` `start_line` | `backend/app/tools/filesystem.py` |
| Path `min_length` | filesystem / search / git tool inputs |
| Early `running` commit | `backend/app/services/task_service.py` |
| LLM errors | `backend/app/llm/client.py` |
| Limits / model settings | `backend/app/config.py`, `backend/.env` |

## Follow-ups (optional)

- Exclude `.workspaces` from uvicorn WatchFiles
- Estimated currency cost from stored token columns (rates × `agent_runs` usage)
- Consider `previous_response_id` or history truncation when conversations get huge
