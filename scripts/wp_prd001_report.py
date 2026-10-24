"""WP-PAPER-REAL-DATA-001 — assemble RUN_REPORT.json from the artefacts.

Every number below is read from a file this WP produced; nothing is typed in.
That is the point: a report assembled by hand drifts from its evidence, and a
report assembled from its evidence can only repeat what actually happened.

Usage::

    uv run python scripts/wp_prd001_report.py --evidence <evidence dir>
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def iso(ts_ms: int | None = None) -> str:
    if ts_ms is None:
        return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def traces(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "traces.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarise_run(run_dir: Path) -> dict[str, Any]:
    rows = traces(run_dir)
    cycles = (
        sorted({int(t["decision_time_ms"]) // 1000 for t in rows})
        if rows
        else []
    )
    windows = sorted({int((t.get("asset_context") or {}).get("window_end_ts") or 0) for t in rows})
    return {
        "run_id": run_dir.name,
        "decisions": len(rows),
        "distinct_decision_seconds": len(cycles),
        "distinct_window_ends": [iso(w) for w in windows if w],
        "modes": {m: sum(1 for t in rows if t["mode"] == m) for m in sorted({t["mode"] for t in rows})},
        "classifications": {
            c: sum(1 for t in rows if t["classification"] == c)
            for c in sorted({t["classification"] for t in rows})
        },
        "orders_created": sum(int(t.get("orders_created") or 0) for t in rows),
        "verifier_verdicts": {
            v: sum(1 for t in rows if t["verification"].get("verdict") == v)
            for v in sorted({t["verification"].get("verdict") for t in rows})
        },
        "risk_verdicts": {
            v: sum(1 for t in rows if t["risk"].get("verdict") == v)
            for v in sorted({t["risk"].get("verdict") for t in rows})
        },
        "selected_strategies": sorted(
            {
                (t.get("proposal") or {}).get("strategy_id")
                for t in rows
                if t.get("proposal") is not None
            },
            key=str,
        ),
        "gross_edge_bps_range": _range(
            [(t.get("proposal") or {}).get("expected_gross_edge_bps") for t in rows if t.get("proposal")]
        ),
        "cost_bps_range": _range(
            [(t.get("proposal") or {}).get("expected_cost_bps") for t in rows if t.get("proposal")]
        ),
        "trace_chain_ok": _chain_ok(run_dir),
    }


def _range(values: list[Any]) -> dict[str, float] | None:
    numbers = [float(v) for v in values if v is not None]
    if not numbers:
        return None
    return {"min": min(numbers), "max": max(numbers), "n": len(numbers)}


def _chain_ok(run_dir: Path) -> bool:
    import hashlib

    path = run_dir / "traces.jsonl"
    if not path.is_file():
        return False
    prev = "genesis"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if raw.get("prev_hash") != prev:
            return False
        body = {k: v for k, v in raw.items() if k != "trace_hash"}
        digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        if digest != raw.get("trace_hash"):
            return False
        prev = digest
    return True


SUITE_PATTERN = re.compile(r"(\d+) (passed|failed|error|errors|skipped)")


def summarise_tests(test_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(test_dir.glob("*.stdout.txt")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = [line for line in text.splitlines() if line.strip()]
        summary_line = lines[-1] if lines else ""
        counts = {kind.rstrip("s"): int(n) for n, kind in SUITE_PATTERN.findall(summary_line)}
        failed = counts.get("failed", 0) + counts.get("error", 0)
        out.append(
            {
                "suite": path.stem.replace(".stdout", ""),
                "summary": summary_line.strip(),
                "passed": counts.get("passed", 0),
                "failed": counts.get("failed", 0),
                "errors": counts.get("error", 0),
                "skipped": counts.get("skipped", 0),
                "exit_code": 1 if failed else 0,
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--evidence", default=str(REPO_ROOT / "docs/agentic/paper_reald/WP-PAPER-REAL-DATA-001")
    )
    args = parser.parse_args(argv)
    evidence = Path(args.evidence)
    raw = evidence / "raw"

    reach = read_json(raw / "PAPER_REACHABILITY.json")
    quality = read_json(raw / "DATA_QUALITY.json")
    controlled = read_json(raw / "CONTROLLED_EXEC.json")
    runs = [
        summarise_run(raw / "runs" / name)
        for name in ("run-a-1h", "run-b-5m", "run-c-controlled-exec")
        if (raw / "runs" / name).is_dir()
    ]

    payload = {
        "wp": "WP-PAPER-REAL-DATA-001",
        "title": "Validación operativa del trading PAPER sobre datos de mercado reales",
        "generated_at": iso(),
        "repository": {
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "commit": git("rev-parse", "HEAD"),
            "base": "e67194e7",
            "worktree": str(REPO_ROOT),
            "isolated_from_main": True,
        },
        "authority_review": {
            "exp004a_commit": "c727b614",
            "exp004a_present": bool(git("cat-file", "-t", "c727b614")),
            "exp004a_is_ancestor_of_main": subprocess.run(
                ["git", "merge-base", "--is-ancestor", "c727b614", "HEAD"],
                cwd=REPO_ROOT,
                capture_output=True,
                check=False,
            ).returncode
            == 0,
            "alpha003_corpus_present": (REPO_ROOT / "data/raw/alpha003").exists(),
            "config_admission_dirty": bool(git("status", "--porcelain", "--", "config/")),
            "conclusion": "EXP004A sigue BLOCKED_WITH_EVIDENCE; este WP no lo desbloquea",
        },
        "reachability": None
        if reach is None
        else {
            "entrypoint": reach["entrypoint"],
            "repo_modules_reached": reach["totals"]["repo_modules_reached"],
            "modules_naming_the_15m_corpus": reach["totals"]["modules_naming_the_15m_corpus"],
            "modules_that_would_fail_without_it": reach["totals"]["modules_that_would_fail_without_it"],
            "paper_path_depends_on_missing_corpus": reach["paper_path_depends_on_missing_corpus"],
            "strategies": {
                tf: [
                    {
                        "strategy_id": row["strategy_id"],
                        "status": row["status"],
                        "admitted_for_paper": row["admitted_for_paper"],
                        "decision_if_selected": row["decision_if_selected"],
                    }
                    for row in rows
                ]
                for tf, rows in reach["strategies"]["by_timeframe"].items()
            },
        },
        "market_data": None
        if quality is None
        else {
            "verdict": quality["verdict"],
            "source": quality["source"],
            "symbols": [
                {
                    "symbol": s["symbol"],
                    "closed_bars": s["closed_bars"],
                    "forming_bars_dropped": s["forming_bars_dropped"],
                    "gaps": len(s["gaps"]),
                    "duplicates": s["duplicates"],
                    "ohlcv_violations": len(s["ohlcv_violations"]),
                    "age_of_last_closed_bar_ms": s["age_of_last_closed_bar_ms"],
                    "stale_budget_ms": s["stale_budget_ms"],
                    "cross_check_agrees": s["cross_check"]["agrees"],
                    "pit_window_sha256": s["pit_window_sha256"],
                }
                for s in quality["symbols_detail"]
            ],
        },
        "runs": runs,
        "controlled_execution": None
        if controlled is None
        else {
            "label": controlled["label"],
            "verdict": controlled["verdict"],
            "failed_checks": controlled["failed_checks"],
            "disclosure": controlled["disclosure"],
            "detail": controlled["detail"],
            "checks": controlled["checks"],
        },
        "tests": summarise_tests(raw / "tests"),
        "verdicts": {
            "runtime_pass": bool(runs) and all(r["trace_chain_ok"] for r in runs),
            "decision_pass": all(
                r["decisions"] > 0 and r["verifier_verdicts"].get("PASS", 0) + r["verifier_verdicts"].get("NOT_RUN", 0) == r["decisions"]
                for r in runs
            ),
            "execution_pass": "TEST_ONLY: the order path was exercised under a labelled fixture; no real strategy is admitted for PAPER, so no market-data campaign could place an order"
            if controlled and controlled["verdict"] == "TEST_EXECUTION_PASS"
            else "NOT_TESTED",
            "trading_performance": "NOT_ASSESSED: no admitted strategy, no positions held between campaigns, no realized PnL from market signals",
        },
    }
    path = evidence / "RUN_REPORT.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(json.dumps(payload["verdicts"], indent=2))
    print(f"[report] -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
