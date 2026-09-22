# Evaluation report

Filled from a deliberate live-API run of [`evals/run_eval.py`](../evals/run_eval.py). **Small internal set (N=15) — not a formal public benchmark.**

## Methodology

| | |
| --- | --- |
| Size | 15 tasks (13 agent + 2 adversarial create-only) |
| Fixture | `microsoft/python-sample-vscode-fastapi-tutorial` (documented pin `225de1e5afe435f1f1ea431c8742f1fe1dc2282f`; live clone uses default branch tip) |
| Grading | HTTP status for S3/S3b; path/mention heuristics + **human** review for agent tasks |
| Claim | Internal smoke/full suite on the deployed demo — not an industry benchmark |

## Run metadata

| Field | Value |
| --- | --- |
| Date (UTC) | 2026-09-22T18:01:15Z (`started_at` stamp) |
| API base | `https://api.airepoagent.app` |
| Model | `gpt-5.4-mini` (from run records) |
| Indexing on? | As configured on the live demo (Pinecone present in deploy) |
| Artifact | Local (gitignored): `evals/results/run-20260922T180115Z.jsonl` + `…-summary.json` |
| Prior smoke | A1,L1,S3 only — `run-20260922T175846Z` (all pass) |

## Aggregates

| Metric | Result |
| --- | --- |
| Completion rate | **100%** (13/13 agent tasks `completed`) |
| Heuristic pass rate | **92.3%** (12/13) |
| Human correctness (this review) | **15/15 pass** — L3 counted pass despite heuristic miss (see notes) |
| Grounding (sampled) | Strong on A/L/I tasks reviewed; paths cited matched the small fixture |
| Avg iterations | ~3.5 |
| Avg latency | ~16.3 s (agent tasks; adversarial ~225 ms) |
| Avg total tokens | ~9.2k per agent task |
| Failure causes | 1× `heuristic_rubric` (L3 only) |
| Adversarial URL reject | **2/2** HTTP **400**, no agent job |

## Per-task

| ID | Done | Heuristic | Human | Notes |
| --- | --- | --- | --- | --- |
| A1 | yes | pass | pass | Structure / `main.py` |
| A2 | yes | pass | pass | Models |
| A3 | yes | pass | pass | Dependencies |
| A4 | yes | pass | pass | How to start / uvicorn |
| A5 | yes | pass | pass | Routes |
| L1 | yes | pass | pass | Correctly reported no auth (~41s, 13 tools) |
| L2 | yes | pass | pass | Correctly reported no rate limiting |
| L3 | yes | **fail** | **pass** | Rubric expected `flushdb.py`; agent correctly described Redis persistence in `main.py` |
| L4 | yes | pass | pass | CI under `.github` |
| M1 | yes | pass | pass | Handler → model flow |
| M2 | yes | pass | pass | Domain / multi-file |
| I1 | yes | pass | pass | No OAuth2 — admitted absence |
| I2 | yes | pass | pass | No Helm chart — admitted absence |
| S3 | yes | pass | pass | `https://127.0.0.1/…` → **400** |
| S3b | yes | pass | pass | Link-local metadata URL → **400** |

## Interpretation

- Completion and adversarial SSRF checks are the strongest signals in this run.
- Absence tasks (L1, L2, I1, I2) did not invent fake modules.
- L3 shows heuristic rubrics can be stricter/narrower than a good answer; human review required.
- Do not extrapolate these rates to larger/polyglot repos or other models without a new run.

## How to reproduce

```bash
cd backend
uv run --with pyyaml python ../evals/run_eval.py --api-base https://api.airepoagent.app --all
```
