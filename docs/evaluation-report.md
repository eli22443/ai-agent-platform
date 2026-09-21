# Evaluation report

**Template only** — no suite results committed. Do not present a published benchmark until this is filled from [`evals/run_eval.py`](../evals/run_eval.py).

## Methodology

| | |
| --- | --- |
| Size | ~15 tasks |
| Fixture | `microsoft/python-sample-vscode-fastapi-tutorial` @ `225de1e5afe435f1f1ea431c8742f1fe1dc2282f` |
| Grading | HTTP checks for S3/S3b; heuristics + **human** review for agent tasks |
| Claim | Small internal set, not a formal benchmark |

## Run metadata

| Field | Value |
| --- | --- |
| Date (UTC) | _TBD_ |
| API base | _TBD_ |
| Model | _TBD_ |
| Indexing on? | _TBD_ |
| Artifact | `evals/results/run-….jsonl` |

## Aggregates

| Metric | Result |
| --- | --- |
| Completion rate | _TBD_ |
| Heuristic pass rate | _TBD_ |
| Human correctness | _TBD_ |
| Grounding (sampled) | _TBD_ |
| Avg iterations / latency / tokens | _TBD_ |
| Failure causes | _TBD_ |

## Per-task

| ID | Done | Heuristic | Human | Notes |
| --- | --- | --- | --- | --- |
| A1–A5, L1–L4, M1–M2, I1–I2 | | | | |
| S3 / S3b | | | | Expect **400** |

Absence tasks fail if the agent invents files. Compare runs only with matching fixture/model/tools.

```bash
cd backend && uv run --with pyyaml python ../evals/run_eval.py --api-base http://127.0.0.1:8000 --all
```
