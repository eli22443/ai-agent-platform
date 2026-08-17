# Phase 1 — FastAPI Foundation

Status: not started. This is the active phase specification.

## Phase objective

Build the backend foundation everything else sits on: a FastAPI application that starts cleanly, serves a health endpoint, loads configuration from the environment, emits structured logs with a correlation identifier, returns consistent error responses, and is covered by a passing test suite run through `uv`.

Nothing beyond that. No database, no Supabase, no Pinecone, no Redis, no Docker, no authentication, no OpenAI call, no agent, and no repository handling. Those arrive in their own phases, and adding them here would mean shipping code with no current purpose.

The value of this phase is that every later phase inherits its conventions. Configuration, logging, error shape, and test layout are decided once, here, and then followed.

## Concepts to learn

- Python project management with `uv`: `pyproject.toml`, the lock file, `uv run`, and why a lock file matters for reproducibility.
- ASGI and the relationship between FastAPI, Starlette, and Uvicorn.
- FastAPI application structure and `APIRouter` composition.
- Pydantic v2 and `pydantic-settings`: typed configuration, environment variables, defaults, and validation at startup.
- FastAPI exception handlers and why a consistent error envelope matters to API clients.
- Structured logging, and correlation identifiers for tracing a request across log lines.
- ASGI application lifespan for startup and shutdown work.
- pytest fixtures and testing an ASGI application with an HTTP client.



## Files to create

```text
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                  Application factory, lifespan, handler registration
│   ├── config.py                Settings via pydantic-settings
│   ├── logging.py               Structured logging configuration
│   ├── errors.py                Error envelope and exception handlers
│   ├── middleware.py            Correlation identifier middleware
│   └── api/
│       ├── __init__.py
│       ├── router.py            Aggregates route modules
│       └── routes/
│           ├── __init__.py
│           └── health.py        GET /health
├── tests/
│   ├── __init__.py
│   ├── conftest.py              Shared fixtures, including the test client
│   ├── test_health.py
│   ├── test_config.py
│   └── test_errors.py
├── .env.example
├── pyproject.toml
└── uv.lock
```

Note on `app/logging.py`: it does not shadow the standard library. Python 3 uses absolute imports, so `import logging` inside that module resolves to the standard library, while the project module is reachable only as `app.logging`.

## Dependencies

Run from `backend/`:

```bash
uv add fastapi "uvicorn[standard]" pydantic-settings
uv add --dev pytest httpx
```

`httpx` is required because Starlette's test client is built on it. `pydantic` arrives transitively through FastAPI and is not added explicitly.

Nothing else. `ruff` and `mypy` are deferred to the CI phase, and adding them now would be a silent change to the specified stack.

## Implementation steps



### 1. Initialize the project

```bash
mkdir -p backend && cd backend
uv init --bare --python 3.12
```

If the installed `uv` does not support `--bare`, run `uv init` and delete the sample module it generates. The result either way should be a `pyproject.toml` and no example code.

Confirm `requires-python = ">=3.12"` and that the project is configured as an application rather than a distributable package.

### 2. Add dependencies

Run the two `uv add` commands above. Verify that `uv.lock` is created and that no `requirements.txt` exists anywhere in the repository.

### 3. Configure pytest

Add to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

`pythonpath` makes `app` importable from the tests without installing the project or relying on implicit path behavior.

### 4. Write the settings module

`app/config.py` defines a `Settings` class based on `BaseSettings`, reading from the environment and an optional `.env` file, with a cached accessor so settings are constructed once.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ai-agent-platform"
    app_env: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"
    debug: bool = False
```

Two rules that later phases depend on: configuration is read only through this object, never through `os.environ` scattered across modules, and a missing required setting fails at startup rather than at first use.

### 5. Write the logging module

`app/logging.py` configures the root logger once, at startup, driven by `settings.log_level`. Log records are emitted as single-line JSON with at least a timestamp, level, logger name, message, and, when present, the correlation identifier.

The correlation identifier is stored in a `contextvars.ContextVar` and injected by a logging filter, so application code writes ordinary log calls and the identifier appears automatically.

### 6. Write the correlation middleware

`app/middleware.py` adds middleware that reads an incoming `X-Request-ID` header or generates a UUID, sets the context variable, and echoes the value back on the response. This is what makes a log line traceable to a request, and in Phase 9 the same identifier will be carried into the worker.

### 7. Write the error handling module

`app/errors.py` defines one response envelope and the handlers that produce it:

```json
{
  "error": {
    "code": "internal_error",
    "message": "An unexpected error occurred.",
    "request_id": "0f7c9b2e-..."
  }
}
```

Register handlers for `HTTPException`, `RequestValidationError`, and unhandled `Exception`. The unhandled case logs the full traceback server-side and returns a generic message with the correlation identifier, so a client can report a failure without the server leaking internals.

### 8. Write the health route

`app/api/routes/health.py` exposes `GET /health` returning exactly:

```json
{"status": "ok"}
```

Use a Pydantic response model so the shape appears in the OpenAPI schema. The endpoint reports process liveness only. It must not acquire resources or check dependencies, because in Phase 14 a load balancer will call it frequently and a health check that does real work becomes an outage amplifier. Dependency checks belong in a separate readiness endpoint introduced when there are dependencies to check.

`app/api/router.py` aggregates route modules into a single router that `main.py` includes, so adding a route module in Phase 2 touches one line.

### 9. Write the application factory

`app/main.py` provides `create_app()` which configures logging, builds the `FastAPI` instance with title and version, registers middleware and exception handlers, includes the router, and defines a lifespan that logs startup and shutdown. Module-level `app = create_app()` gives Uvicorn its target.

A factory rather than a module-level-only application matters for testing: tests can build an isolated instance with overridden settings.

### 10. Write `.env.example`

Names and safe defaults only, never real values:

```bash
APP_ENV=local
LOG_LEVEL=INFO
DEBUG=false
```

Confirm `.env` is git-ignored and `.env.example` is not.

## Tests


| Test                                        | Asserts                                                                                                                  |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `test_health_returns_ok`                    | `GET /health` returns 200 and exactly `{"status": "ok"}`                                                                 |
| `test_openapi_schema_available`             | `/openapi.json` returns 200 and includes the `/health` path                                                              |
| `test_docs_available`                       | `/docs` returns 200                                                                                                      |
| `test_settings_defaults`                    | `Settings()` produces expected defaults with a clean environment                                                         |
| `test_settings_from_environment`            | An environment variable overrides a default                                                                              |
| `test_settings_rejects_invalid_env`         | An invalid `APP_ENV` raises a validation error                                                                           |
| `test_unknown_route_error_shape`            | A missing route returns the error envelope, not FastAPI's default shape                                                  |
| `test_unhandled_exception_returns_envelope` | A route raising an exception returns 500 in the envelope with a request identifier, and the exception does not propagate |
| `test_request_id_echoed`                    | A supplied `X-Request-ID` is returned on the response                                                                    |
| `test_request_id_generated`                 | A request without the header still receives one                                                                          |


`tests/conftest.py` provides a `client` fixture wrapping the application in Starlette's `TestClient`, and sets `APP_ENV=test` so tests never read a developer's local `.env`.

For the unhandled-exception test, register a route that raises on the app instance under test rather than adding a permanent debug endpoint to the application.

Run with:

```bash
uv run pytest -v
```

All tests must pass before the phase is complete.

## Manual verification

```bash
cd backend
uv run uvicorn app.main:app --reload
```

Then confirm:

```bash
curl -i http://127.0.0.1:8000/health
# 200, body {"status": "ok"}, and an X-Request-ID response header

curl -s -H "X-Request-ID: manual-check-123" http://127.0.0.1:8000/health -D - -o /dev/null
# the same identifier comes back

curl -i http://127.0.0.1:8000/does-not-exist
# 404 in the error envelope, with a request_id
```

In a browser, check that `/docs` renders Swagger UI with the health endpoint documented, and `/redoc` renders.

In the server console, confirm log lines are single-line JSON, include the correlation identifier, and that changing `LOG_LEVEL=DEBUG` changes what is emitted.

## Definition of done

- [x] `backend/pyproject.toml` and `backend/uv.lock` exist; no `requirements.txt` anywhere in the repository
- [x] Dependencies are exactly `fastapi`, `uvicorn[standard]`, `pydantic-settings`, plus dev `pytest` and `httpx`
- [x] `uv run uvicorn app.main:app --reload` starts the application without warnings
- [x] `GET /health` returns 200 and exactly `{"status": "ok"}`
- [x] `/docs` and `/redoc` render, and `/openapi.json` includes the health path
- [ ] Settings load from the environment with validated types and sensible defaults
- [ ] No module reads `os.environ` directly; configuration flows through `Settings`
- [ ] Logs are structured, single-line JSON at the configured level, carrying the correlation identifier
- [ ] Every request has a correlation identifier, echoed in the response header
- [ ] `HTTPException`, validation errors, and unhandled exceptions all produce the same error envelope
- [ ] Unhandled exceptions log a traceback server-side and return a generic message to the client
- [x] `.env.example` is committed with names only; `.env` is git-ignored
- [ ] `uv run pytest` passes with every test listed above
- [ ] Manual verification steps all confirmed
- [ ] No code exists for any future phase



## Git commit

```text
feat: initialize FastAPI backend foundation

Add the backend application skeleton managed by uv: FastAPI app factory,
environment-based settings, structured JSON logging with request
correlation identifiers, a consistent error envelope, the health
endpoint, and the pytest suite covering them.
```



## Notes for the next phase

Phase 2 adds the task API on top of this foundation. It will reuse the error envelope, the settings object, and the router aggregation added here, and it will introduce the schema and service layers. It does not introduce a database; the store stays in memory and is documented as a Phase 3 placeholder rather than described as persistence.