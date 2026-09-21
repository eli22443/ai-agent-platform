#!/usr/bin/env python3
"""Run the evaluation task set against a live API (local or deployed).

This is a deliberate, paid evaluation harness — not part of CI.

Examples:
  python evals/run_eval.py --list
  python evals/run_eval.py --api-base http://127.0.0.1:8000 --dry-run
  python evals/run_eval.py --api-base https://api.airepoagent.app --task-ids A1,L1,S3
  python evals/run_eval.py --api-base http://127.0.0.1:8000 --all

Outputs JSONL + a summary JSON under evals/results/ (gitignored except .gitkeep).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - optional convenience
    yaml = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
TASKS_PATH = Path(__file__).resolve().parent / "tasks.yaml"
RESULTS_DIR = Path(__file__).resolve().parent / "results"

PATH_RE = re.compile(
    r"(?:^|[\s`\"'(])((?:[\w.-]+/)*[\w.-]+\.(?:py|md|txt|yml|yaml|toml|json|ini))"
    r"(?:$|[\s`\"'),:])"
)


def _load_tasks() -> dict[str, Any]:
    text = TASKS_PATH.read_text(encoding="utf-8")
    if yaml is None:
        raise SystemExit(
            "PyYAML is required. Install temporarily with:\n"
            "  cd backend && uv run --with pyyaml python ../evals/run_eval.py --help"
        )
    return yaml.safe_load(text)

def _http_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 60.0,
) -> tuple[int, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw else None
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return exc.code, payload


def _extract_cited_paths(text: str) -> list[str]:
    if not text:
        return []
    found = {m.group(1).lstrip("./") for m in PATH_RE.finditer(text)}
    return sorted(found)


def _heuristic_correctness(task: dict[str, Any], result_text: str | None) -> dict[str, Any]:
    """Cheap mechanical checks — not a substitute for human grading."""
    text = result_text or ""
    lower = text.lower()
    cited = _extract_cited_paths(text)
    notes: list[str] = []
    score_parts: list[bool] = []

    expect_paths = [p.rstrip("/") for p in task.get("expect_paths") or []]
    for path in expect_paths:
        hit = path in cited or path.lower() in lower or path.split("/")[-1].lower() in lower
        score_parts.append(hit)
        if not hit:
            notes.append(f"missing expected path signal: {path}")

    for token in task.get("must_mention") or []:
        hit = token.lower() in lower
        score_parts.append(hit)
        if not hit:
            notes.append(f"missing mention: {token}")

    if task.get("expect_absent_claim"):
        absent_markers = (
            "not found",
            "no authentication",
            "does not",
            "doesn't",
            "there is no",
            "not implemented",
            "no evidence",
            "insufficient",
            "does not contain",
            "not present",
            "none exists",
            "no rate limit",
        )
        hit = any(m in lower for m in absent_markers)
        score_parts.append(hit)
        if not hit:
            notes.append("expected an explicit absence / insufficient-evidence claim")

    if not score_parts:
        return {
            "heuristic_pass": None,
            "cited_paths": cited,
            "notes": ["no automatic rubric; grade manually"],
        }

    return {
        "heuristic_pass": all(score_parts),
        "checks_passed": sum(1 for x in score_parts if x),
        "checks_total": len(score_parts),
        "cited_paths": cited,
        "notes": notes,
    }


def _poll_task(
    api_base: str,
    task_id: str,
    *,
    timeout_s: float,
    interval_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        status, payload = _http_json("GET", f"{api_base}/tasks/{task_id}")
        if status != 200 or not isinstance(payload, dict):
            raise RuntimeError(f"poll failed status={status} body={payload}")
        last = payload
        if payload.get("status") in {"completed", "failed"}:
            return last
        time.sleep(interval_s)
    raise TimeoutError(f"task {task_id} still {last.get('status')} after {timeout_s}s")


def _fetch_runs(api_base: str, task_id: str) -> list[dict[str, Any]]:
    status, payload = _http_json("GET", f"{api_base}/tasks/{task_id}/runs")
    if status != 200 or not isinstance(payload, list):
        return []
    return payload


def run_create_only(api_base: str, task: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    status, payload = _http_json(
        "POST",
        f"{api_base}/tasks",
        {
            "repository_url": task["repository_url"],
            "instruction": task["instruction"].strip(),
        },
    )
    latency_ms = int((time.perf_counter() - started) * 1000)
    expected = int(task.get("expect_http_status", 422))
    ok = status == expected
    return {
        "task_id_eval": task["id"],
        "category": task.get("category"),
        "mode": "create_only",
        "http_status": status,
        "expected_http_status": expected,
        "completed": ok,
        "correctness": {"deterministic_pass": ok},
        "latency_ms": latency_ms,
        "platform_task_id": None,
        "result": None,
        "error": None if ok else payload,
        "failure_cause": None if ok else "unexpected_http_status",
        "runs": [],
    }


def run_agent_task(
    api_base: str,
    task: dict[str, Any],
    fixture_url: str,
    *,
    timeout_s: float,
    interval_s: float,
) -> dict[str, Any]:
    repo = task.get("repository_url") or fixture_url
    started = time.perf_counter()
    status, payload = _http_json(
        "POST",
        f"{api_base}/tasks",
        {
            "repository_url": repo,
            "instruction": task["instruction"].strip(),
        },
    )
    if status not in {200, 201, 202} or not isinstance(payload, dict):
        return {
            "task_id_eval": task["id"],
            "category": task.get("category"),
            "mode": "agent",
            "http_status": status,
            "completed": False,
            "correctness": {},
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "platform_task_id": None,
            "result": None,
            "error": payload,
            "failure_cause": "create_failed",
            "runs": [],
        }

    platform_id = str(payload["task_id"])
    try:
        final = _poll_task(
            api_base, platform_id, timeout_s=timeout_s, interval_s=interval_s
        )
    except Exception as exc:  # noqa: BLE001 - record and continue suite
        return {
            "task_id_eval": task["id"],
            "category": task.get("category"),
            "mode": "agent",
            "http_status": status,
            "completed": False,
            "correctness": {},
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "platform_task_id": platform_id,
            "result": None,
            "error": str(exc),
            "failure_cause": "timeout_or_poll_error",
            "runs": [],
        }

    latency_ms = int((time.perf_counter() - started) * 1000)
    runs = _fetch_runs(api_base, platform_id)
    run0 = runs[0] if runs else {}
    completed = final.get("status") == "completed"
    result_text = final.get("result")
    correctness = _heuristic_correctness(task, result_text)

    failure_cause = None
    if not completed:
        failure_cause = "task_failed"
    elif correctness.get("heuristic_pass") is False:
        failure_cause = "heuristic_rubric"

    return {
        "task_id_eval": task["id"],
        "category": task.get("category"),
        "mode": "agent",
        "http_status": status,
        "completed": completed,
        "status": final.get("status"),
        "correctness": correctness,
        "latency_ms": latency_ms,
        "platform_task_id": platform_id,
        "result": result_text,
        "error": final.get("error"),
        "failure_cause": failure_cause,
        "iterations": run0.get("iterations"),
        "prompt_tokens": run0.get("prompt_tokens"),
        "completion_tokens": run0.get("completion_tokens"),
        "total_tokens": run0.get("total_tokens"),
        "halt_reason": run0.get("halt_reason"),
        "tool_call_count": run0.get("tool_call_count"),
        "model": run0.get("model"),
        "runs": runs,
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    agent_rows = [r for r in rows if r.get("mode") == "agent"]
    completed = [r for r in agent_rows if r.get("completed")]
    heuristic = [
        r for r in completed if r.get("correctness", {}).get("heuristic_pass") is True
    ]
    latencies = [r["latency_ms"] for r in agent_rows if r.get("latency_ms") is not None]
    iterations = [
        r["iterations"] for r in agent_rows if isinstance(r.get("iterations"), int)
    ]
    tokens = [
        r["total_tokens"] for r in agent_rows if isinstance(r.get("total_tokens"), int)
    ]
    causes: dict[str, int] = {}
    for r in rows:
        cause = r.get("failure_cause")
        if cause:
            causes[cause] = causes.get(cause, 0) + 1

    return {
        "n_tasks": len(rows),
        "n_agent_tasks": len(agent_rows),
        "completion_rate": (len(completed) / len(agent_rows)) if agent_rows else None,
        "heuristic_pass_rate": (len(heuristic) / len(completed)) if completed else None,
        "avg_latency_ms": (sum(latencies) / len(latencies)) if latencies else None,
        "avg_iterations": (sum(iterations) / len(iterations)) if iterations else None,
        "avg_total_tokens": (sum(tokens) / len(tokens)) if tokens else None,
        "failure_causes": causes,
        "note": (
            "Heuristic pass rate is a mechanical proxy, not a formal benchmark score. "
            "Fill docs/evaluation-report.md after human review."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:8000",
        help="API base URL (no trailing slash)",
    )
    parser.add_argument("--task-ids", default="", help="Comma-separated task ids")
    parser.add_argument("--all", action="store_true", help="Run every task in tasks.yaml")
    parser.add_argument("--list", action="store_true", help="List tasks and exit")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the selected plan without calling the API",
    )
    parser.add_argument("--timeout-s", type=float, default=300.0)
    parser.add_argument("--poll-interval-s", type=float, default=2.0)
    args = parser.parse_args(argv)

    doc = _load_tasks()
    fixture = doc["fixture"]
    tasks: list[dict[str, Any]] = doc["tasks"]

    if args.list:
        for t in tasks:
            print(f"{t['id']:4}  {t.get('category', ''):20}  {t['instruction'][:70].strip()}...")
        return 0

    selected_ids = {x.strip() for x in args.task_ids.split(",") if x.strip()}
    if args.all:
        selected = tasks
    elif selected_ids:
        selected = [t for t in tasks if t["id"] in selected_ids]
        missing = selected_ids - {t["id"] for t in selected}
        if missing:
            print(f"unknown task ids: {sorted(missing)}", file=sys.stderr)
            return 2
    else:
        print("Pass --all, --task-ids, or --list", file=sys.stderr)
        return 2

    if args.dry_run:
        print(json.dumps({"api_base": args.api_base, "tasks": [t["id"] for t in selected]}, indent=2))
        return 0

    api_base = args.api_base.rstrip("/")
    health_status, health_body = _http_json("GET", f"{api_base}/health")
    if health_status != 200:
        print(f"health check failed: {health_status} {health_body}", file=sys.stderr)
        return 1

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    jsonl_path = RESULTS_DIR / f"run-{stamp}.jsonl"
    summary_path = RESULTS_DIR / f"run-{stamp}-summary.json"

    rows: list[dict[str, Any]] = []
    with jsonl_path.open("w", encoding="utf-8") as out:
        for task in selected:
            print(f"running {task['id']}...", flush=True)
            if task.get("mode") == "create_only":
                row = run_create_only(api_base, task)
            else:
                row = run_agent_task(
                    api_base,
                    task,
                    fixture["repository_url"],
                    timeout_s=args.timeout_s,
                    interval_s=args.poll_interval_s,
                )
            row["fixture_commit_sha"] = fixture.get("commit_sha")
            row["recorded_at"] = datetime.now(timezone.utc).isoformat()
            rows.append(row)
            out.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = {
        "api_base": api_base,
        "fixture": fixture,
        "started_at": stamp,
        "results_path": str(jsonl_path.relative_to(ROOT)),
        "metrics": _summarize(rows),
        "task_ids": [r["task_id_eval"] for r in rows],
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary["metrics"], indent=2))
    print(f"wrote {jsonl_path}")
    print(f"wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
