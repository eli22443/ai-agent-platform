# Roadmap

## How to use this document

Fifteen phases, executed in order. Each phase produces working software, has its own tests, and ends in a single commit. A phase introduces only the components it needs; nothing is stubbed in advance because it appears in the target architecture.

This document is the index. When a phase becomes the active one, it gets a detailed specification in `docs/phases/phase-NN.md`. Specifications exist for [Phase 1](phases/phase-01.md) through [Phase 5](phases/phase-05.md). Later phases get a `phase-NN.md` when they become active.

Rules that apply to every phase:

1. Implement only the requested phase.
2. Do not create placeholder modules for future phases.
3. Add tests for new functionality and make them pass before declaring the phase done.
4. Prefer simple code over premature abstraction.
5. Do not silently change a technology decision. If an implementation conflicts with [architecture.md](architecture.md), raise the conflict first.
6. Record intentional technical debt in [decisions.md](decisions.md).

## Phase overview

| Phase | Name | Adds infrastructure | Status |
| --- | --- | --- | --- |
| 1 | FastAPI foundation | None | Complete |
| 2 | Task API | None | Complete |
| 3 | PostgreSQL via Supabase | PostgreSQL | Complete |
| 4 | Repository management | Git CLI | Complete |
| 5 | Repository context tools | ripgrep | Active |
| 6 | OpenAI agent loop | OpenAI API | Not started |
| 7 | Agent runs | None | Not started |
| 8 | Semantic retrieval | Pinecone | Not started |
| 9 | Background execution | Redis | Not started |
| 10 | Docker sandbox | Docker | Not started |
| 11 | Code modification | None | Not started |
| 12 | Authentication, optional | Supabase Auth | Not started |
| 13 | Observability | Langfuse, OpenTelemetry | Not started |
| 14 | AWS deployment | AWS, GitHub Actions | Not started |
| 15 | Production hardening | None | Not started |

**The MVP boundary is the end of Phase 6.** At that point a user can POST a repository URL and an instruction and receive a real engineering answer produced by an agent that investigated the repository through tools. Phases 1 through 6 require no Redis, no Docker, no Pinecone, no authentication, and no agent framework. Everything after Phase 6 adds capability, scale, or production readiness to a system that already works.

## Phase 1 — FastAPI foundation

**Objective.** A clean, tested backend foundation that starts, serves a health endpoint, loads configuration from the environment, logs in a structured way, and returns consistent errors.

**Concepts.** Python project layout with `uv`, ASGI and Uvicorn, FastAPI application structure, `APIRouter`, Pydantic v2 settings management, exception handlers, structured logging, pytest with an ASGI test client.

**Files.** `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/{main,config,logging,errors}.py`, `backend/app/api/routes/health.py`, `backend/tests/test_health.py`, `backend/.env.example`.

**Dependencies.** `uv add fastapi "uvicorn[standard]" pydantic-settings`, `uv add --dev pytest httpx`.

**Definition of done.** The application starts; `GET /health` returns `{"status": "ok"}`; `/docs` and `/redoc` render; settings load from the environment with sensible defaults; unhandled errors produce a consistent JSON shape with a correlation identifier; `uv run pytest` passes; `pyproject.toml` and `uv.lock` exist and no `requirements.txt` does.

**Commit.** `feat: initialize FastAPI backend foundation`

Full specification: [phase-01.md](phases/phase-01.md).

## Phase 2 — Task API

**Objective.** Introduce the engineering task as a domain concept, with a validated request contract and a status lifecycle, before any persistence exists.

**Concepts.** Request and response schemas as separate models, service layer separation, dependency injection, HTTP status code selection, URL validation, the difference between a placeholder store and persistence.

**Files.** `backend/app/schemas/task.py`, `backend/app/services/task_service.py`, `backend/app/api/routes/tasks.py`, `backend/app/api/dependencies.py`, `backend/tests/test_tasks_api.py`.

**Dependencies.** None.

**Interface.**

```text
POST /tasks   {"repository_url": "...", "instruction": "..."}  -> 201 {"task_id": "...", "status": "pending"}
GET  /tasks   -> list
GET  /tasks/{task_id}  -> task or 404
```

Statuses are `pending`, `running`, `completed`, `failed`.

**Definition of done.** Task creation validates the repository URL and rejects malformed input with 422; a task identifier is returned; the status model is defined in one place; the service layer holds the logic and routes stay thin; the in-memory store is clearly documented as a Phase 3 placeholder and is not described as persistence; tests cover creation, retrieval, validation failure, and the not-found path.

**Commit.** `feat: add task API with request validation and status model`

Full specification: [phase-02.md](phases/phase-02.md).

## Phase 3 — PostgreSQL via Supabase

**Objective.** Replace the placeholder store with real persistence.

**Concepts.** SQLAlchemy 2.x declarative models and typed mappings, async sessions and session lifecycle, Alembic migrations, connection pooling, transaction boundaries, keeping database access out of route handlers.

**Files.** `backend/app/database/{session,models,base}.py`, `backend/app/database/migrations/`, `backend/alembic.ini`, `backend/app/repositories/task_repository.py`, updated `task_service.py`, `backend/tests/test_task_persistence.py`.

**Dependencies.** `uv add sqlalchemy alembic "psycopg[binary]"`.

**Tables.** `repositories`, `tasks`, `agent_runs` as sketched in [architecture.md](architecture.md).

**Notes.** Development uses local PostgreSQL via apt (D19). Supabase remains the managed/production target; Supabase Auth is not introduced. Transaction-pooler settings (O7) wait until a Supabase `DATABASE_URL` is used. Persistence lives under `app/database/`; do not add `app/repositories/task_repository.py` (that package name is reserved for Phase 4 Git).

**Definition of done.** Migrations create the schema from empty; the application reads and writes tasks through the database; sessions are request-scoped and always closed; no credential is stored in any row; `DATABASE_URL` comes from the environment; tests run against a real test database and clean up after themselves.

**Commit.** `feat: add PostgreSQL persistence with SQLAlchemy and Alembic`

Full specification: [phase-03.md](phases/phase-03.md).

## Phase 4 — Repository management

**Objective.** Turn a repository URL into a local, isolated, inspectable workspace.

**Concepts.** Subprocess handling with timeouts, Git CLI plumbing, temporary directory lifecycle, URL validation and SSRF defense, repository structure inspection, language detection, cleanup guarantees.

**Files.** `backend/app/repositories/{service,workspace,git_client,url_validation,inspector}.py`, `backend/tests/test_url_validation.py`, `backend/tests/test_repository_service.py`.

**Dependencies.** None in Python; requires the `git` binary.

**Definition of done.** A public HTTPS repository clones into an isolated workspace with a depth limit, a size cap, and a timeout; URL validation rejects non-Git schemes, private and loopback addresses, and the cloud metadata address, with tests for each rejection; the service returns a structure summary including file count, languages, and entry points; workspaces are removed on clone failure and kept on success for Phase 5; the Git CLI is invoked only from this layer; no route calls Git directly.

**Commit.** `feat: add repository service with validated cloning and workspace isolation`

Full specification: [phase-04.md](phases/phase-04.md).

## Phase 5 — Repository context tools

**Objective.** The typed, permission-controlled tool layer the agent will use, built and tested before any model is involved.

**Concepts.** Tool contracts and JSON Schema generation from Pydantic models, path confinement, ripgrep invocation and output parsing, output truncation strategy, structured error results.

**Files.** `backend/app/tools/{base,registry,paths,filesystem,search,git}.py`, `backend/tests/test_tool_paths.py`, `backend/tests/test_tools_filesystem.py`, `backend/tests/test_tools_search.py`.

**Dependencies.** None in Python; requires the `ripgrep` binary. Install with `sudo apt install ripgrep`. Cursor's bundled `rg` must not be used by application code.

**Tools.** `list_files`, `read_file`, `search_code`, `get_file_info`, `get_git_diff`, `get_git_history`. All read-only.

**Definition of done.** Every tool validates its input through a Pydantic model and exposes a JSON Schema; path confinement is implemented once and used by every tool, with tests covering `..` traversal, absolute paths, and symlinks escaping the workspace; ripgrep results are parsed into structured matches with file, line, and context; oversized output is truncated with the truncation flagged in the result; tool errors are returned as data rather than raised; the registry can list available tools with their schemas.

**Commit.** `feat: add repository context tools with path confinement and ripgrep search`

Full specification: [phase-05.md](phases/phase-05.md).

## Phase 6 — OpenAI agent loop

**Objective.** The MVP. An agent that receives an instruction, investigates the repository through tools, and returns an engineering answer.

**Concepts.** The OpenAI Responses API, native function calling, conversation state management, tool dispatch, loop termination, iteration and token budgets, prompt design, mocking model responses in tests.

**Files.** `backend/app/llm/client.py`, `backend/app/agent/{loop,prompts,limits,dispatch}.py`, updated `task_service.py`, `backend/tests/test_agent_loop.py`, `backend/tests/test_agent_limits.py`.

**Dependencies.** `uv add openai`.

**Definition of done.** The loop sends tool schemas, detects tool calls, executes them, feeds results back, and terminates on a final answer; iteration, wall-clock, and token limits are enforced and configurable, and a limit halt is reported distinctly from completion; a tool failure becomes an observation rather than crashing the run; the answer and the tool-call summary are returned through the API; unit tests mock the model entirely and no test makes a paid API call; one manual end-to-end run against a real public repository is documented.

**Commit.** `feat: implement agent loop on the OpenAI Responses API`

## Phase 7 — Agent runs

**Objective.** Make every run inspectable after the fact.

**Concepts.** Execution auditing, schema design for semi-structured data, token accounting, foreign key relationships and cascade behavior, querying run history.

**Files.** `backend/app/database/models.py` extended with `agent_runs` and `tool_calls`, a migration, `backend/app/repositories/run_repository.py`, an optional `GET /tasks/{task_id}/runs`, `backend/tests/test_run_recording.py`.

**Dependencies.** None.

**Definition of done.** Every run persists model, status, iteration count, token usage, timestamps, and final result; every tool call persists name, arguments, status, duration, and error; runs that halt on a limit or fail are recorded with the same fidelity as successful ones; run history is queryable by task; no secret or credential appears in any recorded argument.

**Commit.** `feat: persist agent runs and tool calls`

## Phase 8 — Semantic retrieval

**Objective.** Add semantic search alongside lexical search so the agent can find code by concept rather than by exact string.

**Concepts.** Source-code chunking that respects structure, embedding models and dimensionality, vector upsert and query, metadata filtering, namespace design per repository, hybrid retrieval strategy, index freshness.

**Files.** `backend/app/retrieval/{chunking,embeddings,vector_store,indexer,search}.py`, a `semantic_search` tool, `backend/tests/test_chunking.py`, `backend/tests/test_retrieval_pipeline.py`.

**Dependencies.** `uv add pinecone`.

**Metadata per vector.** Repository identifier, file path, language, chunk start and end lines, and the commit SHA the chunk was indexed from.

**Definition of done.** Repository files are chunked with line ranges preserved and binary and vendored paths excluded; embeddings are generated in batches with retry on failure; vectors are upserted into a per-repository namespace; `semantic_search` returns ranked chunks with metadata sufficient to open the exact lines; lexical search remains available and the tool descriptions explain when to prefer each; chunking is unit tested without calling the embedding API; indexing cost and duration for the fixture repository are recorded.

**Commit.** `feat: add semantic retrieval with OpenAI embeddings and Pinecone`

## Phase 9 — Background execution

**Objective.** Stop holding an HTTP connection open for the duration of an agent run.

**Concepts.** Job queues, worker processes, at-least-once delivery and idempotency, job state transitions, failure and retry semantics, polling APIs, graceful shutdown.

**Files.** `backend/app/workers/{main,jobs}.py`, `backend/app/queue/client.py`, updated task routes, `backend/tests/test_job_enqueue.py`, `backend/tests/test_worker_job.py`.

**Dependencies.** `uv add arq`.

**Definition of done.** `POST /tasks` persists the task, enqueues a job, and returns 202 with a task identifier without waiting for the agent; a worker process executes runs and updates status through `pending`, `running`, and a terminal state; `GET /tasks/{task_id}` reflects live status and returns the result when complete; a worker crash leaves the task in a recoverable state rather than stuck in `running` forever; the worker shuts down gracefully without abandoning an in-flight run silently.

**Commit.** `feat: add background agent execution with Redis and ARQ`

## Phase 10 — Docker sandbox

**Objective.** Execute untrusted repository code safely. This is the most security-sensitive phase in the project.

**Concepts.** Container isolation, resource limits, network policy, filesystem mounts and read-only roots, non-root execution, timeout and cleanup guarantees, capturing and parsing command output.

**Files.** `backend/app/sandbox/{manager,executor,policy,images}.py`, `infrastructure/docker/sandbox.Dockerfile`, `run_command` and `run_tests` tools, `backend/tests/test_sandbox_limits.py`.

**Dependencies.** `uv add docker`; requires a reachable Docker daemon.

**Blocked.** Docker is not currently reachable from the development WSL distribution. This must be resolved before Phase 10 begins. Phases 1 through 9 are unaffected. Substituting host execution is not an acceptable workaround; see [security.md](security.md).

**Definition of done.** Repository code executes only inside a container; containers run as a non-root user, unprivileged, with no Docker socket mounted and no application secrets in the environment; CPU, memory, process count, and wall-clock limits are enforced and tested by attempting to exceed each; network access is disabled by default and enabled only by explicit policy; only the task workspace is mounted; containers and volumes are removed even when execution times out or the worker crashes; test output is captured and parsed into a structured result.

**Commit.** `feat: add Docker sandbox for isolated command and test execution`

## Phase 11 — Code modification

**Objective.** Extend the agent from explaining code to changing it.

**Concepts.** Safe file writing within a workspace, unified diff application and conflict handling, the investigate-modify-test-repair cycle, loop termination when tests keep failing, diff presentation for human review.

**Files.** `backend/app/tools/edit.py`, `backend/app/agent/loop.py` extended, `backend/app/repositories/diff.py`, `backend/tests/test_edit_tools.py`, `backend/tests/test_modification_flow.py`.

**Dependencies.** None; patch application uses the Git CLI.

**Definition of done.** `write_file` and `apply_patch` are workspace-confined and refuse to write outside it; a failed patch reports the conflict rather than partially applying; write tools are granted explicitly per run and absent from analysis-only runs; the agent can run tests, read failures, and attempt a repair within its iteration budget; the run returns a reviewable unified diff; nothing is pushed to the user's repository, and no user-owned checkout is modified.

**Commit.** `feat: add code modification tools and test repair loop`

## Phase 12 — Authentication, optional

**Objective.** Multi-user support, introduced only when the platform actually needs persistent accounts, private repositories, per-user history, or quotas.

**Concepts.** JWT verification against a provider's published keys, FastAPI security dependencies, resource ownership, authorization enforced in the service layer, quota accounting.

**Files.** `backend/app/auth/{dependencies,jwt}.py`, a `users` table and ownership columns with a migration, service-layer authorization, `backend/tests/test_auth.py`, `backend/tests/test_authorization.py`.

**Dependencies.** `uv add "pyjwt[crypto]"`.

**Definition of done.** Tokens are verified for signature, issuer, audience, and expiry against the provider's keys; every user-owned resource carries an owner and every access path filters on the authenticated principal; a test proves one user cannot read another's task; per-user quotas are enforced; no custom password authentication exists anywhere in the codebase.

**Commit.** `feat: add Supabase JWT authentication and per-user authorization`

## Phase 13 — Observability

**Objective.** Make agent behavior diagnosable and its cost visible.

**Concepts.** LLM tracing versus application tracing, span hierarchies, correlation identifiers across API and worker boundaries, structured logging, token and cost accounting, sampling.

**Files.** `backend/app/observability/{logging,tracing,metrics,redaction}.py`, instrumentation in the agent loop and tool dispatch, `backend/tests/test_redaction.py`.

**Dependencies.** `uv add langfuse opentelemetry-sdk opentelemetry-instrumentation-fastapi opentelemetry-exporter-otlp`.

**Definition of done.** A full trace links task, run, each model call, and each tool call in one hierarchy; latency, token usage, and estimated cost are visible per run; a correlation identifier flows from the HTTP request through the queue into the worker and appears in every log line; logs are structured and redact known secret patterns, with tests proving redaction; observability failures degrade gracefully and never break an agent run.

**Commit.** `feat: add Langfuse tracing and OpenTelemetry instrumentation`

## Phase 14 — AWS deployment

**Objective.** Run the platform on AWS with an automated pipeline.

**Concepts.** Multi-stage container builds, image registries, container orchestration, load balancing and health checks, secret injection, IAM roles and least privilege, OIDC-based CI authentication, log aggregation.

**Files.** `backend/Dockerfile`, `infrastructure/aws/`, `.github/workflows/{tests,deploy}.yml`, `docker-compose.yml` for local multi-service development.

**Dependencies.** None in Python; Docker, AWS, GitHub Actions.

**Target.** ECR for images, ECS on Fargate for the API and worker services, an Application Load Balancer, CloudWatch for logs and metrics, Secrets Manager or Parameter Store for secrets, IAM task roles for permissions.

**Definition of done.** The image builds reproducibly and runs as a non-root user; API and worker deploy as separate services with independent scaling; secrets are injected at runtime and never baked into the image or committed; GitHub Actions authenticates to AWS through OIDC with no stored access keys; deployment happens only after tests pass; health checks drive load balancer registration; deployment architecture, networking, IAM, and cost considerations are documented.

**Commit.** `feat: containerize backend and add AWS deployment pipeline`

## Phase 15 — Production hardening

**Objective.** Close the gaps that only matter once the platform is real and exposed.

**Concepts.** Rate limiting strategies, idempotency keys, retry with backoff, graceful degradation, resource reclamation, cost control, alerting.

**Files.** `backend/app/middleware/rate_limit.py`, `backend/app/workers/cleanup.py`, hardening across existing modules.

**Dependencies.** As required; likely `uv add tenacity`.

**Scope.** Rate limiting and request size limits; idempotency on task creation; retry with backoff for transient model, database, and network failures; a sweeper for abandoned workspaces and orphaned containers; per-user and global cost ceilings with alerting; tightened repository URL restrictions; sandbox hardening review; dependency vulnerability scanning in CI; documented incident response for a runaway agent run.

**Definition of done.** Every item in [security.md](security.md) is either implemented, explicitly deferred with a reason, or recorded as an accepted risk; load testing establishes the concurrent-run ceiling; a runaway run can be identified and terminated.

**Commit.** `feat: add production hardening, rate limiting, and resource cleanup`

## Deferred and out of scope

| Item | Status |
| --- | --- |
| Frontend application | Out of scope. Swagger UI is the demonstration surface. No Next.js, no Vercel. |
| LangChain or LangGraph | Deferred. Trigger condition recorded in [decisions.md](decisions.md). |
| tree-sitter AST analysis | Deferred. Revisit if chunking or symbol resolution proves insufficient after Phase 8. |
| GitHub App integration, branch and PR creation | Deferred until after Phase 12, since it requires repository credentials and authorization. |
| Multi-agent orchestration | Out of scope until the single-agent loop is measurably insufficient. |
| `ruff` and `mypy` | Deferred to the Phase 14 CI pipeline unless requested earlier. |
