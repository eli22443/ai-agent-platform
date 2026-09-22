# Evaluation

Design + runnable harness. Results from a live-API full suite are recorded in [evaluation-report.md](evaluation-report.md) (N=15, not a formal industry benchmark).
| | |
| --- | --- |
| Harness | [`evals/`](../evals/) — `tasks.yaml`, `run_eval.py` |
| Default fixture | `microsoft/python-sample-vscode-fastapi-tutorial` (commit in `tasks.yaml`) |
| Optional local zip | `.context/stock-market-master.zip` (gitignored) |
| Live notes | [agent-optimization.md](agent-optimization.md) |

## Why

Fixed tasks + recorded runs beat vibes. Compare runs only when fixture, model, and tools are logged.

## Metrics

| Metric | Meaning |
| --- | --- |
| Completion rate | Finished with an answer vs error/halt |
| Answer correctness | Meets rubric (human review) |
| Grounding | Cited paths/symbols exist in the repo |
| Tool selection | Reached the right files efficiently |
| Iterations / latency / tokens | Cost and speed |
| Failure by cause | Model / tool / infra / safeguard |
| Retrieval hit rate | Needed file appeared in retrieval (Phase 8+) |

Grounding is the cheap hallucination proxy: check cited paths against the workspace.

## Test levels

| Level | Scope | CI? |
| --- | --- | --- |
| Unit | Deterministic logic; mocked LLM | Yes |
| Integration | API+DB, tools, worker; no paid APIs | Yes |
| Agent eval | Full loop + real model + fixture | No (paid, deliberate) |

## Current task set

See `evals/tasks.yaml`: analysis, localization/absence, multi-file, insufficient-context, adversarial create (**HTTP 400**).

Historical stock-market task table (A1–M4, S1–S4) remains design reference for a larger polyglot fixture; the runnable suite uses the smaller public pin above. Path/SSRF/symlink cases also live in unit tests.

## Grading and budgets

Prefer mechanical checks (paths exist, URL rejected, tests pass). Explanations need human review.

| Target | Value |
| --- | --- |
| Iterations (analysis) | under 10 |
| Wall-clock (analysis) | under 60s |
| Adversarial | 100% |
| Grounding | &gt; 95% (aspirational until measured) |

## Run

```bash
cd backend && uv run --with pyyaml python ../evals/run_eval.py --api-base http://127.0.0.1:8000 --all
```

Details: [evals/README.md](../evals/README.md).
