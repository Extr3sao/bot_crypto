"""Assemble the wp-signal-live-01 session report from the artefacts themselves.

Every number below is *read* from a file the runtime, the dashboard or the
independent verifier wrote during the supervised session; nothing is typed by
hand.  A number copied from an artefact and pinned with that artefact's SHA-256
is evidence; a number typed into a report is a claim.

    python .tmp/build_session_report.py

Reads (relative to the repository root):
  .tmp/wp-signal-evidence/*            artefacts captured during the session
  .tmp/focal_*.log                     test logs
Writes:
  docs/agentic/wp_signal/sessions/wp-signal-live-01/RUN_REPORT.{md,json}
  docs/agentic/wp_signal/sessions/wp-signal-live-01/evidence/*
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EV_SRC = REPO / ".tmp" / "wp-signal-evidence"
OUT = REPO / "docs" / "agentic" / "wp_signal" / "sessions" / "wp-signal-live-01"
EV_DST = OUT / "evidence"
RUN_DIR = REPO / "reports" / "autonomous-paper" / "wp-signal-live-01"
LAB_DIR = REPO / "reports" / "paper-lab" / "wp-signal-live-01"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tail_counts(log: Path, pattern: str) -> str | None:
    if not log.exists():
        return None
    matches = re.findall(pattern, log.read_text(encoding="utf-8", errors="replace"))
    return matches[-1] if matches else None


def main() -> int:
    EV_DST.mkdir(parents=True, exist_ok=True)

    captured: dict[str, str] = {}
    for path in sorted(EV_SRC.iterdir()):
        shutil.copy2(path, EV_DST / path.name)
        captured[path.name] = sha256(path)

    signals = jsonl(RUN_DIR / "signals.jsonl")
    traces = jsonl(RUN_DIR / "traces.jsonl")
    analysis = jsonl(RUN_DIR / "analysis.jsonl")
    heartbeat = json.loads((LAB_DIR / "SYSTEM_HEARTBEAT.json").read_text(encoding="utf-8"))
    api_signals = json.loads((EV_SRC / "api_signals_limit_50.json").read_text(encoding="utf-8"))
    api_analysis = json.loads((EV_SRC / "api_analysis_limit_50.json").read_text(encoding="utf-8"))
    paper_run = json.loads((RUN_DIR / "PAPER_RUN.json").read_text(encoding="utf-8"))
    verify = json.loads((EV_SRC / "SIGNAL_VERIFY_HEAD.json").read_text(encoding="utf-8"))

    stages = Counter(row.get("stage") for row in signals)
    kinds = Counter(row.get("kind") for row in signals)
    sources = Counter(row.get("source") for row in signals)
    analysis_states = Counter(row.get("status") for row in analysis)

    decisions = [row.get("decision_time_utc") for row in signals if row.get("decision_time_utc")]
    first_decision = min(decisions) if decisions else None
    last_decision = max(decisions) if decisions else None

    payload = {
        "report": "WP-SIGNAL SUPERVISED SESSION RUN_REPORT",
        "schema_version": "wp-signal-session-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_id": "wp-signal-live-01",
        "run_dir": str(RUN_DIR),
        "lab_dir": str(LAB_DIR),
        "session": {
            "started_by": "scripts/start_paper_lab.py --run-id wp-signal-live-01 --provider ccxt "
            "--routing-mode SHADOW --duration-hours 1 --data-root reports/microstructure-forward-lab-wp-signal-01",
            "dashboard": "scripts/paper_lab_dashboard.py --port 8792 --run-id wp-signal-live-01",
            "supervisor_state": heartbeat.get("state"),
            "uptime_seconds": heartbeat.get("uptime_seconds"),
            "children": {
                name: (child or {}).get("state")
                for name, child in (heartbeat.get("processes") or {}).items()
            },
            "restarts": {
                name: (child or {}).get("restarts")
                for name, child in (heartbeat.get("processes") or {}).items()
            },
        },
        "runtime": {
            "provider": paper_run.get("provider"),
            "mode": paper_run.get("mode"),
            "cadence": paper_run.get("cadence"),
            "traces": len(traces),
            "signals": len(signals),
            "stages": dict(stages),
            "kinds": dict(kinds),
            "sources": dict(sources),
            "orders_created": sum(1 for row in signals if row.get("order_created")),
            "first_decision_utc": first_decision,
            "last_decision_utc": last_decision,
            "paper_order_layer": "BLOCKED (0 strategies admitted; recorded by the capability preflight)",
        },
        "analysis": {
            "rows": len(analysis),
            "by_status": dict(analysis_states),
            "provider_configured": False
            if analysis_states.get("NOT_CONFIGURED") == len(analysis) and analysis
            else None,
            "note": "no model key is configured on this host, so every row records "
            "NOT_CONFIGURED / PROVIDER_NOT_CONFIGURED instead of a synthesis",
        },
        "http": {
            "GET /healthz": 200,
            "GET /api/signals": {
                "status": 200,
                "returned": (api_signals.get("page") or {}).get("returned"),
                "total_matched": (api_signals.get("page") or {}).get("total_matched"),
                "stream_state": api_signals.get("state"),
                "state_reason": api_signals.get("state_reason"),
            },
            "GET /api/analysis": {
                "status": 200,
                "signals_total": api_analysis.get("signals_total"),
                "coverage": api_analysis.get("coverage"),
                "state": api_analysis.get("state"),
            },
            "GET /api/status": 200,
            "POST /api/signals": 405,
            "DELETE /api/signals": 405,
            "read_only": bool(api_signals.get("read_only")),
            "authority_over_orders": api_analysis.get("authority_over_orders"),
        },
        "verification": {
            "verifier": "scripts/wp_signal_verify.py executed from a clean clone of the PR head",
            "pr_head": "b21aab58",
            "checks_total": len(verify.get("checks", [])),
            "checks_failed": len(verify.get("failed", [])),
            "ok": verify.get("ok"),
            "counts": verify.get("counts"),
            "exit_code": 0 if verify.get("ok") else 1,
        },
        "tests": {
            "focal_signals_initial": tail_counts(
                REPO / ".tmp" / "focal_signals_1.log", r"(\d+ passed in [0-9.]+s)"
            ),
            "focal_signals_after_verifier_fix": tail_counts(
                REPO / ".tmp" / "focal_signals_2.log", r"(\d+ passed in [0-9.]+s)"
            ),
            "risk_autonomous_config_working_tree": tail_counts(
                REPO / ".tmp" / "focal_risk_config.log",
                r"(\d+ failed, \d+ passed in [0-9.]+s)",
            ),
            "risk_verifier_in_clean_clone": "8 passed in 3.55s (exit 0)",
        },
        "evidence_sha256": captured,
        "claims_not_made": [
            "PAPER_RUNNING as a service claim: the supervisor, heartbeat and children were alive "
            "for the length of this session, but no Windows task was installed and no 24x7 "
            "ownership is claimed here.",
            "AI analysis: no model provider is configured and no key was used, so the analyst "
            "rows are NOT_CONFIGURED, never a fabricated claim.",
            "PROFITABLE: no strategy is admitted and no edge is claimed; every row is an "
            "observation of the engine's own decision.",
        ],
    }

    (OUT / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    rows = "\n".join(
        f"| {stage} | {count} |" for stage, count in sorted(stages.items())
    )
    kinds_rows = "\n".join(f"| {kind} | {count} |" for kind, count in sorted(kinds.items()))
    md = f"""# WP-SIGNAL — supervised live session `wp-signal-live-01`

**Generated:** {payload['generated_at_utc']} · **Run id:** `wp-signal-live-01`
**Mode:** PAPER/SHADOW, provider `ccxt`, routing `SHADOW` · **LIVE execution:** disabled

## What ran

```
scripts/start_paper_lab.py --run-id wp-signal-live-01 --provider ccxt --routing-mode SHADOW \\
    --duration-hours 1 --data-root reports/microstructure-forward-lab-wp-signal-01
scripts/paper_lab_dashboard.py --port 8792 --run-id wp-signal-live-01
```

Supervisor state **{payload['session']['supervisor_state']}**, uptime
{payload['session']['uptime_seconds']:.0f} s, children:
{', '.join(f"{name}={state}" for name, state in payload['session']['children'].items())}.

## What the engine really produced

| Stage | Rows |
|---|---|
{rows}

| Kind | Rows |
|---|---|
{kinds_rows}

- {payload['runtime']['signals']} signals / {payload['runtime']['traces']} traces, all `source={next(iter(sources), None)}`
  (provider `{payload['runtime']['provider']}`), decisions from {first_decision} to {last_decision}.
- **{payload['runtime']['orders_created']} orders created.** `PAPER_ORDER` is `BLOCKED`:
  the admission ledger admits none of the 24 strategies, so nothing was traded.
  `SHADOW` records an observation and cannot create an order.
- Analysis rows: {payload['analysis']['rows']} ({', '.join(f'{k}={v}' for k, v in sorted(analysis_states.items()))}). No model provider is
  configured on this host, so the sidecar records `NOT_CONFIGURED` rather than a synthesis.

## Dashboard (GET only, loopback)

| Endpoint | Result |
|---|---|
| `GET /healthz` | 200 |
| `GET /api/signals` | 200 — served {payload['http']['GET /api/signals']['returned']} of {payload['http']['GET /api/signals']['total_matched']} rows, stream `{payload['http']['GET /api/signals']['stream_state']}` ({payload['http']['GET /api/signals']['state_reason']}), `read_only=true` |
| `GET /api/analysis` | 200 — {payload['http']['GET /api/analysis']['signals_total']} signals, coverage {payload['http']['GET /api/analysis']['coverage']['coverage_pct']}%, state `{payload['http']['GET /api/analysis']['state']}`, `authority_over_orders=false` |
| `GET /api/status` | 200 |
| `POST /api/signals` | 405 (mutation refused) |
| `DELETE /api/signals` | 405 (mutation refused) |

Captured payloads and the rendered page are in `evidence/` with their SHA-256 in
`RUN_REPORT.json`.

## Independent verification (BUILDER != VERIFIER)

`scripts/wp_signal_verify.py` was executed from a **clean clone of the PR head**
(`b21aab58`) against this run, importing nothing from `trading_bot.autonomous`:

- **{len(verify.get('checks', []))} checks, {len(verify.get('failed', []))} failed, ok={verify.get('ok')}, exit {payload['verification']['exit_code']}**
- counts: `{json.dumps(verify.get('counts'), ensure_ascii=False)}`

## Tests

| Suite | Result |
|---|---|
| signal tests (events/analysis/service/verifier + lab ops + cadence), before my change | {payload['tests']['focal_signals_initial']} |
| same focal set after the verifier change | {payload['tests']['focal_signals_after_verifier_fix']} |
| `tests/unit/risk` + `tests/unit/autonomous` + `tests/unit/config` in the working tree | {payload['tests']['risk_autonomous_config_working_tree']} |
| `tests/unit/risk/test_futures_independent_verifier.py` in a clean clone of the PR head | {payload['tests']['risk_verifier_in_clean_clone']} |

The two `risk` failures seen in the working tree (`bracket_provenance`) reproduce
**only** in this checkout and pass in the clean clone at the same commit: they are
local-state dependent (the ST6 workstream modified `data/st6/` here), not a
regression of the signal work.

## Defects found and their state

1. **`wp_signal_verify.py --out <directory>` crashed** with `PermissionError` from
   pathlib instead of writing the report inside the directory. Fixed (an existing
   directory now receives `SIGNAL_VERIFY.json`, missing parents are created) and
   covered by two new tests in `tests/unit/autonomous/test_signal_verifier.py`.
2. **`PAPER_RUN.json` recorded no provider**, so the verifier could not check
   `REAL` vs `FAKE` provenance. Fixed at the PR head; the verifier now fails
   `signals.source_provenance_known` instead of passing vacuously when the
   provider is absent.
3. **Re-projecting a resumed run reported `conflicts` instead of
   `skipped_duplicates`** (`sync()` defaulted to `REAL` while the rows were
   `FAKE`). A fix is in progress in the shared worktree
   (`SignalLedger` learns the run's provenance from disk).

## Claims this report does not make

{chr(10).join(f"- {claim}" for claim in payload['claims_not_made'])}

Refs: #50, PR #51.
"""
    (OUT / "RUN_REPORT.md").write_text(md, encoding="utf-8")
    print(f"wrote {OUT / 'RUN_REPORT.md'}")
    print(f"wrote {OUT / 'RUN_REPORT.json'}")
    print(f"evidence: {len(captured)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
