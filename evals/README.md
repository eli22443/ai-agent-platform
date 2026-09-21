# Evaluation harness

~15 tasks against one pinned public repo. **Not** a formal benchmark.

| | |
| --- | --- |
| Repo | `https://github.com/microsoft/python-sample-vscode-fastapi-tutorial` |
| Commit (docs) | `225de1e5afe435f1f1ea431c8742f1fe1dc2282f` |

Optional: `.context/stock-market-master.zip` (gitignored). Tasks: [`tasks.yaml`](tasks.yaml) (A/L/M/I + S3/S3b → HTTP **400**).

## Run (costs money)

```bash
cd backend
uv run --with pyyaml python ../evals/run_eval.py --list
uv run --with pyyaml python ../evals/run_eval.py --api-base http://127.0.0.1:8000 --all
```

Needs API + worker + OpenAI (Pinecone optional). Results → `evals/results/` (gitignored). Copy into [evaluation-report.md](../docs/evaluation-report.md).

**Metrics:** completion, latency, iterations, tokens, tool calls, halt reason, heuristic path checks, failure causes. Heuristics ≠ human correctness.
