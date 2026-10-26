"""Write the session-end addendum for wp-signal-live-01 from the finalised artefacts.

    python .tmp/build_session_end.py

Reads the descriptors, the heartbeat, the supervisor run report and the
post-stop dashboard responses, and writes SESSION_END.{md,json} plus the
post-stop evidence into the session directory.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / ".tmp" / "wp-signal-evidence-after-stop"
OUT = REPO / "docs" / "agentic" / "wp_signal" / "sessions" / "wp-signal-live-01"
EV = OUT / "evidence-after-stop"
RUN_DIR = REPO / "reports" / "autonomous-paper" / "wp-signal-live-01"
LAB_DIR = REPO / "reports" / "paper-lab" / "wp-signal-live-01"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    EV.mkdir(parents=True, exist_ok=True)
    captured: dict[str, str] = {}
    for path in sorted(SRC.iterdir()):
        shutil.copy2(path, EV / path.name)
        captured[path.name] = sha256(path)

    paper = json.loads((RUN_DIR / "PAPER_RUN.json").read_text(encoding="utf-8"))
    heartbeat = json.loads((LAB_DIR / "SYSTEM_HEARTBEAT.json").read_text(encoding="utf-8"))
    after_status = json.loads((SRC / "api_status_after_stop.json").read_text(encoding="utf-8"))
    after_signals = json.loads((SRC / "api_signals_after_stop.json").read_text(encoding="utf-8"))
    verify = json.loads((SRC / "SIGNAL_VERIFY_AFTER_STOP.json").read_text(encoding="utf-8"))
    lab_report = json.loads((SRC / "LAB_RUN_REPORT.json").read_text(encoding="utf-8"))
    totals = paper.get("totals") or {}
    signals = jsonl(RUN_DIR / "signals.jsonl")
    analysis = jsonl(RUN_DIR / "analysis.jsonl")

    payload = {
        "report": "WP-SIGNAL SESSION END",
        "schema_version": "wp-signal-session-end-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_id": "wp-signal-live-01",
        "stop": {
            "method": "scripts/start_paper_lab.py --stop reports/paper-lab/wp-signal-live-01",
            "exit_code": 0,
            "stop_reason": paper.get("stop_reason"),
            "ended_at_ms": paper.get("ended_at_ms"),
            "descriptor_state": paper.get("state"),
            "children": {
                name: (child or {}).get("state")
                for name, child in (heartbeat.get("processes") or {}).items()
            },
            "supervisor_state": heartbeat.get("state"),
            "supervisor_exit": (lab_report.get("supervisor") or {}).get("exit_code"),
        },
        "final_totals": totals,
        "final_stream": {
            "signals": len(signals),
            "analysis_rows": len(analysis),
            "orders_created": totals.get("orders_created"),
            "paper_trades": totals.get("paper_trades"),
            "runtime_failures": totals.get("runtime_failures"),
        },
        "dashboard_after_stop": {
            "signals_state": after_signals.get("state"),
            "signals_state_reason": after_signals.get("state_reason"),
            "status_system_state": (after_status.get("system") or {}).get("state"),
            "status_running": (after_status.get("system") or {}).get("running"),
            "status_errors": (after_status.get("errors") or [])[:3],
            "honest_down_report": bool(after_signals.get("state") == "DOWN"),
        },
        "verification_after_stop": {
            "ok": verify.get("ok"),
            "checks_total": len(verify.get("checks", [])),
            "checks_failed": len(verify.get("failed", [])),
            "counts": verify.get("counts"),
            "exit_code": 0 if verify.get("ok") else 1,
        },
        "known_limitation": {
            "observation": "the final PAPER_RUN.json written by this session declares no "
            "`provider`, so the verifier reported provider=null",
            "cause": "the session ran the entrypoint as it stood at 3be8e5bd; the head "
            "already rewrites the final descriptor with the provider",
            "verification": "scripts/autonomous_paper.py at the head writes "
            '"provider": args.provider in the STOPPED rewrite',
        },
        "evidence_sha256": captured,
    }

    (OUT / "SESSION_END.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    children = ", ".join(f"{k}={v}" for k, v in payload["stop"]["children"].items())
    md = f"""# `wp-signal-live-01` — session end

**Generated:** {payload['generated_at_utc']}

## Graceful stop

```
scripts/start_paper_lab.py --stop reports/paper-lab/wp-signal-live-01   -> exit 0
```

- `stop_reason`: **{payload['stop']['stop_reason']}**, descriptor state `{payload['stop']['descriptor_state']}`,
  ended at ms {payload['stop']['ended_at_ms']}.
- Children at the end: {children}. Supervisor state `{payload['stop']['supervisor_state']}`.

## What the whole session produced

| Metric | Value |
|---|---|
| asset cycle evaluations | {totals.get('asset_cycle_evaluations')} |
| traces persisted | {totals.get('traces_persisted')} |
| signals in the stream | {payload['final_stream']['signals']} |
| analysis rows | {payload['final_stream']['analysis_rows']} (NOT_CONFIGURED) |
| **orders created** | **{totals.get('orders_created')}** |
| paper trades | {totals.get('paper_trades')} |
| shadow trades | {totals.get('shadow_trades')} |
| runtime failures | {totals.get('runtime_failures')} |
| risk APPROVED / VETOED | {totals.get('risk_APPROVED')} / {totals.get('risk_VETOED')} |

`PAPER_ORDER` stayed `BLOCKED` for the whole session: the admission ledger admits
none of the 24 strategies, so nothing could be traded and nothing was.

## Dashboard after the stop

| Item | Value |
|---|---|
| `GET /api/signals` state | `{payload['dashboard_after_stop']['signals_state']}` — {payload['dashboard_after_stop']['signals_state_reason']} |
| `GET /api/status` system | `{payload['dashboard_after_stop']['status_system_state']}`, running={payload['dashboard_after_stop']['status_running']} |
| errors surfaced | {payload['dashboard_after_stop']['status_errors']} |

The board reports the lab as **DOWN**, not as healthy: a stopped lab must look
stopped.

## Verification after the stop

`scripts/wp_signal_verify.py` (clean clone of the head) → **{len(verify.get('checks', []))} checks,
{len(verify.get('failed', []))} failed, ok={verify.get('ok')}, exit {payload['verification_after_stop']['exit_code']}**,
counts `{json.dumps(verify.get('counts'), ensure_ascii=False)}`.

### Known limitation of this session

{payload['known_limitation']['observation']}. Cause: {payload['known_limitation']['cause']}.
The head {payload['known_limitation']['verification']}.

Refs: #50, PR #51.
"""
    (OUT / "SESSION_END.md").write_text(md, encoding="utf-8")
    print(f"wrote {OUT / 'SESSION_END.md'}")
    print(f"wrote {OUT / 'SESSION_END.json'} ({len(captured)} evidence file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
