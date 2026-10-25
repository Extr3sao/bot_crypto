"""WP-TDM-06 report builder.

Assembles ``RUN_REPORT.json`` / ``RUN_REPORT.md`` from the artifacts this Work
Package actually produced (verifier reports, profitability replay, baseline
checks, negative controls, preserved-change inventory). Test and lint results are
constants here because they are the output of commands run in this session; each
one names the exact command so it can be re-run.

    PYTHONPATH=src python scripts/tdm06_report.py
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
WP = REPO_ROOT / "reports" / "trading-decision-monitor" / "WP-TDM-06"

#: Observed in this session (command, result). Re-runnable verbatim.
TESTS = [
    {
        "command": (
            "pytest tests/unit/config tests/unit/autonomous tests/unit/storage "
            "tests/unit/monitor tests/integration tests/regression -q"
        ),
        "where": "isolated worktree @ e67194e7",
        "result": "485 passed",
        "exit_code": 0,
    },
    {
        "command": (
            "pytest tests/unit/paper tests/unit/risk tests/unit/scanner "
            "tests/unit/backtesting tests/unit/market_data tests/unit/strategy_lifecycle -q"
        ),
        "where": "isolated worktree @ e67194e7",
        "result": "635 passed, 2 failed (pre-existing: RFC-048 CRLF provenance)",
        "exit_code": 1,
    },
    {
        "command": "pytest tests/unit/monitor -q",
        "where": "isolated worktree (after WP-TDM-06 fixes)",
        "result": "117 passed",
        "exit_code": 0,
    },
    {
        "command": "ruff check src/trading_bot/monitor tests/unit/monitor scripts/tdm*.py",
        "where": "isolated worktree",
        "result": "All checks passed",
        "exit_code": 0,
    },
    {
        "command": "uvx --with pydantic --with pydantic-settings mypy src/trading_bot/monitor",
        "where": "isolated worktree (isolated env; project config: strict)",
        "result": "Success: no issues found in 5 source files (was 56 errors)",
        "exit_code": 0,
    },
]

DEFECTS_FIXED = [
    {
        "id": "DEF-TDM-06-1",
        "summary": "API pagination reported a shrinking total_matching and could not signal truncation",
        "found_by": "independent verifier on the 2 232-decision replay (V2)",
        "fix": "total counted before the cursor filter; has_more computed from the remaining slice",
        "regression": "tests/unit/monitor/test_api.py::test_pagination_reports_a_stable_total_and_loses_no_decision",
    },
    {
        "id": "DEF-TDM-06-2",
        "summary": "Verifier assumed a single page and failed every run larger than 500 decisions",
        "found_by": "same replay run",
        "fix": "verifier walks every page, requires no advance-loop and total_matching == decisions served",
        "regression": "verified on 2 232 decisions (5 pages) + negative controls",
    },
    {
        "id": "DEF-TDM-06-3",
        "summary": "Verifier crashed on a truncated ledger and passed an empty one vacuously",
        "found_by": "negative controls (truncated_ledger, empty_ledger)",
        "fix": "JSON parse error becomes V1 FAIL; empty ledger is never evidence",
        "regression": "scripts/tdm06_negative_controls.py (7 cases, verdict PASS)",
    },
    {
        "id": "DEF-TDM-06-4",
        "summary": "Monitor module did not type-check under the project's strict mypy",
        "found_by": "mypy run required by §B",
        "fix": "typed _EventCommon mapping + explicit strategy_id per event + bytes-safe host label",
        "regression": "mypy clean; 117 monitor tests still pass",
    },
    {
        "id": "DEF-TDM-06-5",
        "summary": "Chart marker labels overlapped into an unreadable block at 2 232 decisions",
        "found_by": "browser inspection of the replay run",
        "fix": "markers kept, labels only when <= 80 visible buckets",
        "regression": "tests/unit/monitor/test_static_assets.py::test_marker_labels_are_dropped_when_the_window_is_dense",
    },
]

DEFECTS_OPEN = [
    {
        "id": "DEF-TDM-06-6",
        "summary": "RFC-048 provenance digests were recorded over CRLF bytes; the committed payloads are LF",
        "evidence": "6/6 digests match only after lf->crlf; fails at HEAD and in the clean worktree",
        "impact": "2 tests in tests/unit/risk/test_futures_independent_verifier.py fail everywhere",
        "why_not_fixed": (
            "re-recording a signed certification bundle is a research decision, not a runtime repair"
        ),
    },
    {
        "id": "DEF-TDM-06-7",
        "summary": "Shared checkout is BLOCKED_MUTATED_RUNTIME (7 files replaced by recovery005 stubs)",
        "evidence": "EXTERNAL_CHANGES_PRESERVED.json + TypeError from scripts/autonomous_paper.py",
        "impact": "no runtime claim may be based on the shared tree",
        "why_not_fixed": "restoring would overwrite owner changes; restore_runtime.sh is provided, not run",
    },
    {
        "id": "DEF-TDM-06-8",
        "summary": "Proposal gross edge is the admission ledger constant, not a per-cycle market estimate",
        "evidence": "1 930 proposals show exactly -4.56 / -1.88 / -0.11 / 1.49 bps (one value per strategy)",
        "impact": "the loop can rank and gate, but cannot discover edge from the current bar",
        "why_not_fixed": "changing it changes the decision model; out of scope by WP-06 restrictions",
    },
]


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


def build() -> dict[str, Any]:
    baseline = load(WP / "baseline_checks.json")
    profitability = load(WP / "profitability.json")
    negatives = load(WP / "verification" / "negative_controls.json")
    preserved = load(WP / "EXTERNAL_CHANGES_PRESERVED.json")
    verifiers = {
        name: load(WP / f"verifier-{name}" / "verifier_report.json")
        for name in ("live", "replay", "fixture")
    }
    live_run = load(WP / "runtime-runs" / "tdm06-live-20261024T105508Z" / "RUN_REPORT.json")
    analysis = profitability.get("analysis", {})

    return {
        "schema": "wp-tdm-06-run-report-v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "repository": {
            "head": git("rev-parse", "HEAD"),
            "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "worktree_state": "DIRTY_PRESERVED" if git("status", "--porcelain") else "CLEAN",
            "modified_by_campaign": [
                row["path"] for row in preserved.get("files", []) if row.get("tracked_in_head")
            ],
            "preserved_copies": str((WP / "preserved").relative_to(REPO_ROOT)).replace("\\", "/"),
            "policy": "nothing reverted, staged, stashed or deleted by this Work Package",
        },
        "baseline": {
            "kind": "git worktree (isolated, detached)",
            "path": "../ff-wt-tdm06",
            "commit": "e67194e79a42aef2a2ded3aca21ac4a0ea3689c5",
            "contents": "HEAD + the new monitor layer only (no tracked file modified)",
            "settings": baseline.get("settings"),
            "cost_model": {
                key: value
                for key, value in (baseline.get("cost_model") or {}).items()
                if key != "rows"
            },
            "cost_rows": (baseline.get("cost_model") or {}).get("rows"),
            "admission": {
                "verdict": (baseline.get("admission") or {}).get("verdict"),
                "paper_candidates": (baseline.get("admission") or {}).get("paper_candidates"),
                "entries": len((baseline.get("admission") or {}).get("entries") or {}),
            },
            "pit": baseline.get("pit"),
        },
        "work_packages": {
            "A_audit_and_recovery": "COMPLETE (inventory, preservation, isolated baseline, diagnosis)",
            "B_operational_validation": "COMPLETE (suites, YAML/cost/admission/PIT, live PAPER run, panel)",
            "C_independent_verification": "COMPLETE (3 verifications + 7 negative controls, false_success=0)",
            "D_profitability": "COMPLETE (3-day replay over fresh public data, 2 232 decisions)",
        },
        "tests": TESTS,
        "runtime": {
            "live_paper": {
                "run_id": live_run.get("run_id"),
                "environment": live_run.get("environment"),
                "commit": live_run.get("commit"),
                "totals": live_run.get("totals"),
                "orders": len(live_run.get("executions") or []),
                "evidence": "WP-TDM-06/runtime-runs/tdm06-live-20261024T105508Z",
            },
            "replay": {
                "run_id": profitability.get("run_id"),
                "window_days": analysis.get("window_days"),
                "cycles": analysis.get("cycles"),
                "decisions": analysis.get("decisions"),
                "executions": analysis.get("executions"),
                "chain_ok": analysis.get("chain_ok"),
                "outcomes": analysis.get("outcomes"),
                "evidence": "WP-TDM-06/replay-runs/tdm06-replay-20261024T110829Z",
            },
            "fixture_labeled": {
                "runs": ["tdm-sim-filled", "tdm-sim-order-rejected"],
                "label": "SIMULATED_FIXTURE — never presented as live",
                "purpose": "exercise ORDER_FILLED / EXECUTION_FAILED semantics",
            },
        },
        "verification": {
            name: {
                "status": report.get("status"),
                "false_success": report.get("false_success"),
                "coverage": report.get("coverage"),
            }
            for name, report in verifiers.items()
        },
        "negative_controls": {
            "verdict": negatives.get("verdict"),
            "cases": [
                {
                    "case": row.get("case"),
                    "status": row.get("status"),
                    "failed_checks": row.get("failed_checks"),
                    "detected": row.get("detected_correctly"),
                    "false_success": row.get("false_success"),
                }
                for row in negatives.get("cases", [])
            ],
        },
        "profitability": {
            "decisions": analysis.get("decisions"),
            "decisions_per_day": analysis.get("decisions_per_day"),
            "trades_per_day": analysis.get("trades_per_day"),
            "reason_distribution": analysis.get("reason_distribution"),
            "causes": analysis.get("causes"),
            "proposal_gross_bps": analysis.get("proposal_gross_bps"),
            "proposal_cost_bps": analysis.get("proposal_cost_bps"),
            "proposal_net_bps": analysis.get("proposal_net_bps"),
            "counterfactual": analysis.get("counterfactual"),
            "per_strategy": analysis.get("per_strategy"),
            "data": analysis.get("provenance"),
        },
        "defects_fixed": DEFECTS_FIXED,
        "defects_open": DEFECTS_OPEN,
        "blockers": [
            "shared worktree is BLOCKED_MUTATED_RUNTIME (owner decision required)",
            "REA not installed: no binary, no [mcp_servers.rea] → REQ-TDM-010 NOT_PERFORMED",
            "no admitted strategy in the ledger → zero PAPER fills on real data (not a bug)",
            "browser rendering verified by DOM + screenshots; no automated visual regression suite",
        ],
        "next_step": (
            "Owner restores the seven runtime files (or approves restore_runtime.sh), then "
            "WP-TDM-07 measures whether any admissible family exists above the 23,79 bps barrier."
        ),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    repo = payload["repository"]
    base = payload["baseline"]
    live = payload["runtime"]["live_paper"]
    replay = payload["runtime"]["replay"]
    prof = payload["profitability"]
    lines = [
        "# WP-TDM-06 — RUN REPORT",
        "",
        f"Generado: `{payload['generated_at']}` · commit `{repo['head'][:12]}` "
        f"(`{repo['branch']}`) · working tree **{repo['worktree_state']}**",
        "",
        "## 1. Baseline",
        "",
        f"- Worktree aislado: `{base['path']}` @ `{base['commit'][:12]}`, {base['contents']}.",
        f"- Config: modo `{(base['settings'] or {}).get('runtime_mode')}`, "
        f"live `{(base['settings'] or {}).get('live_trading_enabled')}`, "
        f"{(base['settings'] or {}).get('universe_pairs')} pares, "
        f"riesgo máx/trade `{((base['settings'] or {}).get('risk') or {}).get('max_risk_per_trade_pct')}%`.",
        f"- Coste: `{(base['cost_model'] or {}).get('cost_model_version')}` · "
        f"BTC `{(base['cost_rows'] or {}).get('BTC/USDT', {}).get('round_trip_bps')}` bps · "
        f"ETH `{(base['cost_rows'] or {}).get('ETH/USDT', {}).get('round_trip_bps')}` bps · "
        f"SOL `{(base['cost_rows'] or {}).get('SOL/USDT', {}).get('round_trip_bps')}` bps.",
        f"- Admisión: `{(base['admission'] or {}).get('verdict')}` "
        f"({(base['admission'] or {}).get('entries')} entradas, "
        f"candidatas={(base['admission'] or {}).get('paper_candidates')}).",
        f"- PIT: barra en formación excluida "
        f"`{((base['pit'] or {}).get('forming_bar_excluded'))}`.",
        "",
        "## 2. Tests y análisis estático",
        "",
        "| comando | dónde | resultado |",
        "| --- | --- | --- |",
    ]
    for row in payload["tests"]:
        lines.append(f"| `{row['command']}` | {row['where']} | {row['result']} |")

    lines += [
        "",
        "## 3. Runtime real (PAPER, datos públicos, sin órdenes)",
        "",
        f"- Run `{live.get('run_id')}` · `{live.get('environment')}` · commit `{str(live.get('commit'))[:12]}`.",
        f"- Totales: {json.dumps(live.get('totals'), ensure_ascii=False)}",
        f"- Órdenes: **{live.get('orders')}** · fills: 0 · fallos de runtime: "
        f"`{(live.get('totals') or {}).get('runtime_failures')}`.",
        f"- Replay {replay.get('window_days')} días: {replay.get('decisions')} decisiones, "
        f"{replay.get('executions')} ejecuciones, cadena íntegra `{replay.get('chain_ok')}`.",
        "",
        "## 4. Verificación independiente",
        "",
        "| conjunto | estado | false_success | checks |",
        "| --- | --- | --- | --- |",
    ]
    for name, row in payload["verification"].items():
        cov = row.get("coverage") or {}
        lines.append(
            f"| {name} | {row.get('status')} | {row.get('false_success')} | "
            f"{cov.get('checks_total')} ({cov.get('passed')} PASS / "
            f"{cov.get('not_exercised')} NOT_EXERCISED) |"
        )
    lines += [
        "",
        f"Controles negativos: **{payload['negative_controls']['verdict']}** "
        f"({len(payload['negative_controls']['cases'])} casos).",
        "",
        "| caso | estado obtenido | checks en FAIL | detectado |",
        "| --- | --- | --- | --- |",
    ]
    for row in payload["negative_controls"]["cases"]:
        lines.append(
            f"| {row['case']} | {row['status']} | {', '.join(row['failed_checks'] or []) or '—'} | "
            f"{'sí' if row['detected'] else 'NO'} |"
        )

    lines += [
        "",
        "## 5. Diagnóstico de rentabilidad",
        "",
        f"- Decisiones/día: {prof.get('decisions_per_day')} · trades/día: {prof.get('trades_per_day')}.",
        f"- Motivos: {json.dumps(prof.get('reason_distribution'), ensure_ascii=False)}.",
        f"- Causas: {json.dumps(prof.get('causes'), ensure_ascii=False)}.",
        f"- Bruto por propuesta: {json.dumps(prof.get('proposal_gross_bps'), ensure_ascii=False)}",
        f"- Neto por propuesta: {json.dumps(prof.get('proposal_net_bps'), ensure_ascii=False)}",
        f"- Outcome medido: {json.dumps((prof.get('outcomes') or {}).get('net_hypothetical_bps'), ensure_ascii=False)} "
        f"(dirección correcta {(prof.get('outcomes') or {}).get('direction_correct_pct')}%)",
        f"- Contrafactual: {json.dumps(prof.get('counterfactual'), ensure_ascii=False)}",
        "",
        "## 6. Defectos",
        "",
        "### Corregidos",
        "",
    ]
    for row in payload["defects_fixed"]:
        lines.append(f"- **{row['id']}** — {row['summary']} · encontrado por: {row['found_by']}")
    lines += ["", "### Abiertos", ""]
    for row in payload["defects_open"]:
        lines.append(f"- **{row['id']}** — {row['summary']} · evidencia: {row['evidence']}")
    lines += ["", "## 7. Bloqueos", ""]
    lines += [f"- {item}" for item in payload["blockers"]]
    lines += ["", "## 8. Próximo paso", "", payload["next_step"], ""]
    return "\n".join(lines)


def main() -> int:
    payload = build()
    WP.mkdir(parents=True, exist_ok=True)
    (WP / "RUN_REPORT.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    (WP / "RUN_REPORT.md").write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("work_packages",)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
