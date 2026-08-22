# Decisions

## Purpose

A record of what was decided, why, and what was rejected. Its job is to stop settled questions from being silently relitigated during implementation, and to make it obvious when a change is a deliberate revision rather than drift.

Three sections: settled decisions, open items that must not be resolved by assumption, and accepted technical debt.

**Scope.** Decisions D1–D22 cover Phases 1–6. Phases 1–5 are implemented in `backend/`. Phase 6 is specified in [phases/phase-06.md](phases/phase-06.md) but not yet implemented; D22 governs the `/run` endpoint when that phase lands.

## Settled decisions

### D1 — `uv` for dependency management

`uv` with `pyproject.toml` and `uv.lock`. A `requirements.txt` is never created in this repository.

Rejected: pip with `requirements.txt`, which has no real lock semantics; Poetry and Pipenv, which solve the same problem more slowly.

Consequence: every command runs through `uv run`, and the lock file is committed.

### D2 — FastAPI with Pydantic v2

FastAPI is the application layer, with Pydantic v2 for validation and settings.

Rejected: Django, too much framework for an API-only service; Flask, which would mean rebuilding validation and OpenAPI generation by hand.

### D3 — OpenAI Responses API, called directly

The agent loop is written against the OpenAI Responses API with native function calling, using the official SDK, with no agent framework.

Rejected: the Chat Completions API, since the Responses API is the current interface and its tool-calling model is what the project should be built around; LangChain and LangGraph, which would hide exactly the mechanics this project exists to understand.

Revisit when: the workflow genuinely requires multi-agent orchestration, durable branching state, or human-in-the-loop interrupts that a hand-written loop handles badly. Ergonomic preference is not a trigger. Any adoption is a deliberate revision recorded here.

### D4 — Pinecone as the vector store, from Phase 8

Pinecone with OpenAI `text-embedding-3-small`.

Rejected: pgvector, which was recommended in an earlier draft of the plan on the grounds that PostgreSQL was already present and it avoided a second external service. That recommendation is withdrawn. Pinecone is the specified choice, and the learning value of operating a dedicated vector database is part of the project's purpose. Also rejected: Qdrant and Chroma, which are reasonable but not specified.

Consequence: application state lives in PostgreSQL and vectors live in Pinecone. Pinecone is never used as a source of truth.

### D5 — Lexical search first, semantic search alongside it

`search_code` backed by ripgrep arrives in Phase 5 and remains permanently. Semantic search is added beside it in Phase 8, not in place of it.

Rationale: a large fraction of real code questions are exact-match questions, where ripgrep is faster, cheaper, and more precise than an embedding lookup, and needs no index to be fresh. Vector search is not assumed to be the best way to retrieve code; it is the right tool for conceptual queries where the user's wording does not appear in the source.

### D6 — PostgreSQL via Supabase, as a database only

Supabase provides managed PostgreSQL. Business logic stays in FastAPI. Supabase client libraries, edge functions, and row-level-security-as-authorization are not used.

Rejected: self-hosted PostgreSQL, which currently needs either Docker or a system install; AWS RDS, which is heavier to operate for this scale.

Revisit when: managed hosting becomes a constraint rather than a convenience.

### D7 — SQLAlchemy 2.x with Alembic

Typed declarative models with SQLAlchemy 2.x and Alembic migrations.

Rejected: raw SQL, which loses type checking and migration tooling; SQLModel, which adds a layer over both SQLAlchemy and Pydantic and blurs the boundary between the persistence and API schemas.

### D8 — ARQ with Redis for background jobs

ARQ with Redis for durable background work (clone and agent runs), from Phase 9.

Rejected: Celery, heavier than needed and awkward with async code; RQ, which is synchronous; FastAPI `BackgroundTasks`, which runs in the API process and provides no durability, no retries, and no visibility, making it unsuitable for multi-minute agent runs.

### D9 — Docker for sandboxed execution

All execution of repository code happens in a Docker container with resource limits and network policy.

Rejected: subprocess isolation, which is not an isolation boundary at all; gVisor and Firecracker, which offer stronger isolation and remain a legitimate future upgrade if the platform ever runs genuinely hostile workloads at scale.

Hard constraint: no unrestricted host shell execution is exposed to the agent at any phase.

### D10 — No frontend

Swagger UI is the demonstration surface. No Next.js, no Vercel, no frontend framework at any phase.

Rationale: the project's purpose is backend, agent, and infrastructure engineering. A frontend would consume time without exercising any of it.

### D11 — Authentication deferred, and never custom

No authentication initially. When multi-user behavior is actually needed, Supabase Auth with JWT verification and FastAPI security dependencies.

Custom password authentication is not implemented under any circumstances.

Trigger for Phase 12: persistent user accounts, private repositories, per-user history, or per-user quotas. Until then the posture is public repositories only, IP-based rate limiting if exposed, and a deployment that is not publicly reachable.

### D12 — Langfuse and OpenTelemetry, from Phase 13

Langfuse for LLM and agent tracing, OpenTelemetry for application traces and metrics. Deliberately after the agent works, because instrumenting a design that is still changing wastes the instrumentation.

### D13 — AWS for application infrastructure, external services retained

ECR, ECS on Fargate, an Application Load Balancer, CloudWatch, IAM, and Secrets Manager or Parameter Store. Supabase, Pinecone, OpenAI, and GitHub remain external.

"Use AWS" means the application's own infrastructure runs on AWS. It does not mean replacing every managed service with an AWS equivalent.

### D14 — Git CLI rather than a Git library

Repository operations shell out to `git` from the repository service.

Rejected: GitPython, which adds a dependency and its own failure modes over the same CLI; pygit2, which adds a native build dependency for capability the project does not need.

Consequence: subprocess handling, timeouts, and output parsing are the repository service's responsibility, and Git is invoked from nowhere else.

### D15 — Database at Phase 3, before the agent at Phase 6

Persistence lands early, so that when the agent arrives there is already somewhere to record runs, and the in-memory placeholder from Phase 2 has a short life.

Rejected: an earlier draft that placed the database at Phase 8, which would have meant building the agent against a placeholder store and then migrating it.

### D16 — Strict layer separation

The seven layers in [architecture.md](architecture.md) communicate through explicit interfaces. Routes do not call Git or construct prompts. The agent loop does not call `subprocess` or open files. Tools do not call the model.

This is what makes the sandbox and persistence layers replaceable later without touching agent logic, and it is the rule most likely to be eroded under time pressure.

### D17 — Documentation before implementation

The architecture, agent design, threat model, evaluation approach, and roadmap were written before Phase 1 code. Each phase gets a detailed specification in `docs/phases/phase-NN.md` just before implementation, not all at once upfront.

Rationale: the security posture and phase boundaries are the parts most expensive to retrofit. The cost is that some documented details will be wrong, which is why every document states its status and is expected to be revised as phases land.

Consequence: Phases 1–5 landed against this documentation. Phase 6 is the active spec; later phases remain outlined in [roadmap.md](roadmap.md) until they become active.

### D18 — Unversioned API paths

Domain routes are unversioned: `/tasks`, not `/api/v1/tasks`. Health checks stay unversioned regardless, as they already are.

Decided at the start of Phase 2, resolving open item O4.

Rationale: the original specification shows unversioned `GET /health` and `POST /tasks`, and the platform has no external clients, so a version prefix would carry cost without buying compatibility for anyone. It also keeps the route declarations consistent, since every route module owns its full path with no prefix applied by `app/api/router.py`.

Rejected: an `/api/v1` prefix from the start, which is the safer default for an API with real consumers.

Revisit before: exposing the API publicly or building any client against it. Adding a prefix later means changing every path, so it is much cheaper to do while this project is the only caller.

### D19 — Local apt PostgreSQL for development

Development and tests for Phase 3 use PostgreSQL installed with `apt` on WSL (`postgresql://` via `psycopg` v3). Two databases: `ai_agent_platform` for local runs and `ai_agent_platform_test` for pytest.

Decided at the start of Phase 3, resolving open item O3.

Rationale: Docker is unreachable from this distro, so a containerized Postgres is not available. A hosted Supabase project would match production (D6) but requires a provisioned project and makes every test a network call. A system install is local, offline-capable, and enough to learn SQLAlchemy and Alembic.

Rejected: hosted Supabase as the Phase 3 development target; Docker Compose Postgres (blocked by O1).

D6 is unchanged: managed/production PostgreSQL remains Supabase. This decision is the development database only. SQLAlchemy stays sync to match the existing FastAPI routes; async sessions are not introduced here.

Consequence: replaced the Phase 2 in-memory task store when Phase 3 landed (see accepted technical debt table).

### D20 — HTTPS allow-list and post-DNS SSRF checks for clone URLs

Clone URLs must be `https` with a hostname on a configurable allow-list (default `github.com`, `gitlab.com`, `bitbucket.org`). After `getaddrinfo`, every resolved address is checked: reject loopback, RFC1918, link-local, unique-local, and `169.254.169.254`. URLs with userinfo, `file://`, `ssh://`, `http://`, and scp-style syntax are rejected.

Decided at the start of Phase 4. Implements the Phase 4 controls in [security.md](security.md).

Rationale: Phase 2 `HttpUrl` only checks syntax. A clone is a server-side fetch; the hostname string is not a sufficient allow-list if DNS returns a private address.

Rejected: allowing any public HTTPS host (broader SSRF surface); `git://` (unencrypted); cloning `file://` in tests as a production code path.

Private repositories remain out of scope (existing debt, Phase 12).

### D21 — System ripgrep for `search_code`

The `search_code` tool invokes ripgrep via `subprocess` using a binary resolved by `shutil.which(settings.ripgrep_path)` (default `"rg"`). Developers install with `sudo apt install ripgrep`. Cursor's bundled ripgrep under `~/.cursor-server` must not be used.

Decided at the start of Phase 5, resolving open item O2.

Rationale: Phase 5 tests and runtime need a stable binary on PATH in WSL and in future containers. Editor-bundled tools are not deployment dependencies.

Rejected: vendoring a ripgrep binary in the repo (heavier maintenance); pure-Python search (slower, wrong learning goal for this phase).

### D22 — Agent runs via `POST /tasks/{task_id}/run`

Creating a task (`POST /tasks`) only validates, clones, and stores a `pending` task. The agent executes on a separate `POST /tasks/{task_id}/run`, which runs the OpenAI Responses loop synchronously and returns the answer.

Decided at the start of Phase 6.

Rationale: keeps clone failures distinct from agent failures; makes the MVP flow explicit (create, then run); avoids making every task creation pay for an LLM call. Inline agent-on-create was rejected as harder to reason about and harder to evolve toward Phase 9 background jobs.

Consequence: Phase 6 `/run` holds the HTTP request for the whole agent loop (same class of debt as sync clone). Phase 9 moves execution to a worker; the separate-run resource can become enqueue or stay as an explicit trigger.

Idempotency in Phase 6: a second `/run` on `completed`, `failed`, or `running` returns 409. Re-run semantics wait for a later phase if needed.

Phase 6 implementation details locked in [phases/phase-06.md](phases/phase-06.md): explicit Responses API input list (not `previous_response_id` alone), read-only tool registry only, persist answer on `tasks.result` without Phase 7 `agent_runs` rows, and return an in-memory tool-call summary in the run response.

## Open items

These must be resolved explicitly, not by assumption during implementation.

### O1 — Docker unavailable in the development environment

Docker Desktop is installed on the Windows host but its daemon is not reachable from this WSL distribution; `docker info` reports the binary is not found in the distro.

Impact: blocks Phase 10 entirely, which in turn blocks Phase 11, since `run_tests` requires the sandbox, and complicates the Phase 14 image build. Phases 1 through 9 are unaffected.

Options: enable WSL integration in Docker Desktop settings, install the Docker engine directly inside the distribution, or perform sandbox work on a different machine.

Not an option: running repository code on the host and calling it a sandbox. See [security.md](security.md).

Decide by: the start of Phase 10.

### O2 — System ripgrep is not installed — resolved

Resolved at the start of Phase 5: require `sudo apt install ripgrep` and resolve `rg` via `shutil.which`. See D21.

### O3 — Supabase hosted versus local PostgreSQL for development — resolved

Resolved at the start of Phase 3 in favour of local PostgreSQL via apt. See D19.

### O4 — API versioning — resolved

Resolved at the start of Phase 2 in favour of unversioned paths. See D18.

The entry is kept rather than deleted so that the numbering of O5 through O8 stays stable and references to them elsewhere do not rot.

### O5 — Lint and type tooling

`ruff` and `mypy` are not in the specified stack and appear only implicitly in the Phase 14 CI pipeline. Adding them at Phase 1 would be cheap and would apply to all code as it is written; adding them at Phase 14 means retrofitting annotations across the whole codebase.

Recommendation: adopt both earlier than Phase 14. Not acted on, because it would be a silent change to the specified stack.

Decide by: whenever requested; the cost of deferring grows with each phase.

### O6 — Second evaluation fixture

The `stock-market-master` fixture has one test file, so test-repair tasks require seeded bugs. A second fixture with a real test suite would make the Phase 11 modification metrics meaningful.

Decide by: the start of Phase 11.

### O7 — Supabase connection pooler driver configuration — deferred

Local apt PostgreSQL (D19) has no transaction pooler, so prepared-statement settings are not a Phase 3 blocker.

Decide by: the first time `DATABASE_URL` points at Supabase's transaction pooler (expected at production deployment, Phase 14). Verify `psycopg` against the pooler then and record the required settings here.

### O8 — Chunking strategy for code embeddings

Phase 8 needs a chunking approach: fixed-size windows are simple but split functions, while structure-aware chunking requires parsing. tree-sitter would enable the latter and is currently deferred.

Decide by: implementation of Phase 8.

## Accepted technical debt

| Item | Introduced | Cost | Repaid |
| --- | --- | --- | --- |
| In-memory task store | Phase 2 | State lost on restart; single-process only | Phase 3 (implementation landed) |
| Validation errors omit the offending field | Phase 2 | A 422 says only "Request validation failed."; a client cannot tell which field was wrong or why | Deferred; revisit at Phase 15, or sooner if it slows development |
| Synchronous clone on `POST /tasks` | Phase 4 | HTTP request stays open for `git clone`; timeouts feel like API failures | Phase 9 |
| Synchronous agent execution on `POST /tasks/{id}/run` | Phase 6 (not yet landed) | Long-held HTTP connections, no progress visibility; pairs with sync clone debt | Phase 9 |
| No authentication | Phase 1 | Anyone with network access can invoke the API | Phase 12, or on public exposure |
| Public repositories only | Phase 4 | Cannot handle private repositories | Phase 12 |
| Single evaluation fixture | Phase 6 (when eval runs begin) | Benchmark may overfit to one repository's structure | See O6 |
| `.context/` excluded from version control | Phase 1 | Reference PDFs and the fixture archive are not tracked | Not planned; they are large binaries, not source |

Recording debt is only useful if it is read. Each item above names the phase that repays it, and a phase is not complete while it silently leaves new debt unrecorded here.
