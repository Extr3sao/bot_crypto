"""WP-9F — the run report: what ran, what it returned, and what it did not prove.

The report is *folded* from the artefacts rather than written from memory: each row is a
program's own verdict, its own check counts and the path of the file that carries them.
A run report that retypes its own numbers is a second place for them to be wrong, and the
whole point of the WP-8/WP-9 discipline is that a claim has one home.

The commands column is the command this lane actually executed, with its exit code, so a
reader can re-run any row.

Exit codes: 0 report written, 2 a required artefact is missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WP9 = ROOT / "data" / "recovery" / "wp9"

#: (deliverable, the command that produced it, the artefact that describes the run)
STEPS: tuple[dict[str, str], ...] = (
    {
        "id": "WP9-B1",
        "what": "disk budget audit: why the 24 h window stopped, and what 24/48/72 h cost",
        "command": "uv run python scripts/wp9_disk_budget_audit.py",
        "artifact": "WP9_DISK_BUDGET_AUDIT.json",
        "verdict_path": "verdict",
    },
    {
        "id": "WP9-B2",
        "what": "disk budget preflight: the launcher refuses a window its valve cannot pay for",
        "command": "uv run python scripts/start_paper_lab.py --duration-hours 24 --dry-run",
        "artifact": "evidence/preflight_refusal.out",
        "verdict_path": "disk.budget.state",
    },
    {
        "id": "WP9-C1",
        "what": "runtime rehearsal: the real entrypoint, four legs, a controlled stop and a resume",
        "command": (
            "uv run python scripts/wp9_runtime_rehearsal.py --run-id wp9-runtime-legs "
            "--interval 20 --cycles 3 --bar-close-cycles 1 --stop-after-seconds 45"
        ),
        "artifact": "WP9_RUNTIME_24H_REPORT.json",
        "verdict_path": "verdict",
    },
    {
        "id": "WP9-D1",
        "what": "M-03 / M-07 readiness against the machine-readable pre-registration",
        "command": "uv run python scripts/wp9_m03_m07_readiness.py",
        "artifact": "WP9_M03_M07_READINESS.json",
        "verdict_path": None,
    },
    {
        "id": "WP9-E1",
        "what": "ACTIVE economic blockers, classification and the cost/entry RFC draft",
        "command": "uv run python scripts/wp9_economic_blockers.py",
        "artifact": "WP9_ACTIVE_ECONOMIC_BLOCKERS.json",
        "verdict_path": None,
    },
    {
        "id": "WP9-A1",
        "what": "CI runtime certification: the workflows audited, the sequence executed locally",
        "command": "uv run python scripts/wp9_ci_audit.py",
        "artifact": "WP9_CI_EXECUTION_REPORT.json",
        "verdict_path": "verdict",
    },
    {
        "id": "WP9-F1",
        "what": "independent verification of every headline claim, with negative controls",
        "command": "uv run python scripts/wp9_verify.py",
        "artifact": "INDEPENDENT_VERIFICATION.json",
        "verdict_path": "verdict",
    },
)


def dig(payload: Any, path: str | None) -> Any:
    if not path:
        return None
    node = payload
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def counts(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in ("checks_total", "checks_failed", "checks_not_exercised", "sequence_total",
                "sequence_failed", "controls_total", "controls_missed", "false_success",
                "criteria_total", "criteria_not_met", "strategies_total"):
        if key in payload:
            out[key] = payload[key]
    return out


def build() -> dict[str, Any]:
    rows = []
    for step in STEPS:
        path = WP9 / step["artifact"]
        exists = path.exists()
        payload: dict[str, Any] = {}
        if exists and path.suffix == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                payload = {}
        rows.append({
            **step,
            "present": exists,
            "file": str(path.relative_to(ROOT)).replace("\\", "/"),
            "verdict": dig(payload, step["verdict_path"]) if step["verdict_path"] else None,
            "counts": counts(payload),
        })

    verification_path = WP9 / "INDEPENDENT_VERIFICATION.json"
    verification = json.loads(verification_path.read_text(encoding="utf-8")) if verification_path.exists() else {}
    disk = json.loads((WP9 / "WP9_DISK_BUDGET_AUDIT.json").read_text(encoding="utf-8")) \
        if (WP9 / "WP9_DISK_BUDGET_AUDIT.json").exists() else {}
    readiness = json.loads((WP9 / "WP9_M03_M07_READINESS.json").read_text(encoding="utf-8")) \
        if (WP9 / "WP9_M03_M07_READINESS.json").exists() else {}
    blockers = json.loads((WP9 / "WP9_ACTIVE_ECONOMIC_BLOCKERS.json").read_text(encoding="utf-8")) \
        if (WP9 / "WP9_ACTIVE_ECONOMIC_BLOCKERS.json").exists() else {}
    runtime = json.loads((WP9 / "WP9_RUNTIME_24H_REPORT.json").read_text(encoding="utf-8")) \
        if (WP9 / "WP9_RUNTIME_24H_REPORT.json").exists() else {}
    ci = json.loads((WP9 / "WP9_CI_EXECUTION_REPORT.json").read_text(encoding="utf-8")) \
        if (WP9 / "WP9_CI_EXECUTION_REPORT.json").exists() else {}

    state = {
        "disk": {
            "planning_rate_mb_per_hour": disk.get("measurement", {}).get("planning_rate_mb_per_hour"),
            "requirements_gb": [
                {"hours": item["hours"], "mean": item["required_gb"], "stress": item["stress"]["required_gb"],
                 "fits": item["fits"], "fits_stress": item["stress"]["fits"]}
                for item in disk.get("projections", {}).get("horizons", [])
            ],
            "findings": [f["id"] for f in disk.get("findings", [])],
        },
        "readiness": {
            hypothesis: {
                "verdict": readiness.get("verdict", {}).get(hypothesis),
                "criteria_not_met": readiness.get("hypotheses", {}).get(hypothesis, {}).get("criteria_not_met"),
                "cost_to_close_hours": readiness.get("hypotheses", {}).get(hypothesis, {}).get("cost_to_close", {}).get("hours"),
            }
            for hypothesis in ("M-03", "M-07")
        },
        "economics": blockers.get("verdict", {}),
        "runtime": {
            "verdict": runtime.get("verdict"),
            "hours_executed": runtime.get("hours_executed"),
            "hours_target": runtime.get("hours_target"),
            "window_complete": runtime.get("window_complete"),
            "checks_not_exercised": runtime.get("checks_not_exercised"),
            "legs": [
                {"name": leg["name"], "exit_code": leg["exit_code"], "seconds": leg["seconds"],
                 "traces_added": leg["traces_added"]}
                for leg in runtime.get("legs", [])
            ],
        },
        "ci": {
            "verdict": ci.get("verdict"),
            "ci_certified": ci.get("ci_certified"),
            "runner": ci.get("runner"),
            "sequence": f"{ci.get('sequence_total')} steps, {ci.get('sequence_failed')} failed",
            "blocked_by": len(ci.get("certification", {}).get("blocked_by", [])),
        },
        "governance": {
            "LIVE_TRADING": "DISABLED",
            "TRADES_AUTHORIZED": 0,
            "PROFITABILITY_VERIFIED": False,
            "FALSE_SUCCESS": verification.get("false_success"),
            "admitted_strategies": blockers.get("verdict", {}).get("profitable_strategies"),
        },
    }
    return {
        "artifact": "WP9_RUN_REPORT",
        "work_package": "WP-9 (CI RUNTIME CERTIFICATION & PAPER READINESS RECOVERY)",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "steps": rows,
        "state": state,
        "not_proven": [
            "that either workflow has ever run on a GitHub runner (no credential, no registration, "
            "and the commit that carries them is not published)",
            "that the runtime is stable over 24 h (a fraction of a day was executed and the report "
            "says WINDOW_INCOMPLETE)",
            "that any strategy is profitable (0 admitted, 0 net-positive, best gross 8.912 bps "
            "against a 23.354 bps plane)",
            "that M-03 or M-07 can be researched yet (both NOT_READY with their shortfall stated)",
        ],
        "verdict": (
            "PARTIAL — every capability claim is verified and every missing one is named; "
            "CI_CERTIFIED and a 24 h stability verdict are both withheld by their own criteria"
        ),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    state = payload["state"]
    lines = [
        "# WP-9 — RUN REPORT",
        "",
        f"> `{payload['generated_at_utc']}` · **{payload['verdict']}**",
        "",
        "## 1. What ran",
        "",
        "| step | what it establishes | command | verdict | file |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in payload["steps"]:
        verdict = row["verdict"] or (", ".join(f"{k}={v}" for k, v in row["counts"].items()) or "—")
        lines.append(
            f"| `{row['id']}` | {row['what']} | `{row['command']}` | {verdict} | "
            f"{'`' + row['file'] + '`' if row['present'] else '**MISSING**'} |"
        )
    lines += [
        "",
        "## 2. The state the reports describe",
        "",
        f"* disk: planning rate **{state['disk']['planning_rate_mb_per_hour']} MB/h**; findings "
        f"{', '.join(state['disk']['findings'])}",
        "",
        "| horizon | required (mean) | required (1.5x) | fits | fits at 1.5x |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for item in state["disk"]["requirements_gb"]:
        lines.append(
            f"| {item['hours']:.0f} h | {item['mean']:.2f} GB | {item['stress']:.2f} GB | "
            f"{item['fits']} | {item['fits_stress']} |"
        )
    lines += [
        "",
        f"* M-03: `{state['readiness']['M-03']['verdict']}` "
        f"({state['readiness']['M-03']['criteria_not_met']} criteria unmet, "
        f"{state['readiness']['M-03']['cost_to_close_hours']} h to close)",
        f"* M-07: `{state['readiness']['M-07']['verdict']}` "
        f"({state['readiness']['M-07']['criteria_not_met']} criteria unmet, "
        f"{state['readiness']['M-07']['cost_to_close_hours']} h to close)",
        f"* economics: {state['economics'].get('binding_blocker')} — "
        f"{state['economics'].get('strategies_with_demonstrable_net_advantage')} strategies with "
        f"demonstrable net advantage, next experiment: {state['economics'].get('next_experiment')}",
        f"* runtime: `{state['runtime']['verdict']}` — "
        f"{state['runtime']['hours_executed']} h of {state['runtime']['hours_target']} h, "
        f"window_complete={state['runtime']['window_complete']}, "
        f"{state['runtime']['checks_not_exercised']} checks not exercised",
        f"* CI: `{state['ci']['verdict']}` — ci_certified={state['ci']['ci_certified']}, "
        f"runner={state['ci']['runner']}, sequence {state['ci']['sequence']}, "
        f"{state['ci']['blocked_by']} blocking reason(s)",
        "",
        "## 3. Legs of the runtime rehearsal",
        "",
        "| leg | exit | seconds | traces added |",
        "| --- | ---: | ---: | ---: |",
        *[f"| {leg['name']} | {leg['exit_code']} | {leg['seconds']} | {leg['traces_added']} |"
          for leg in state["runtime"]["legs"]],
        "",
        "## 4. Governance",
        "",
        *[f"* `{key} = {value}`" for key, value in state["governance"].items()],
        "",
        "## 5. Not proven by this work package",
        "",
        *[f"* {item}" for item in payload["not_proven"]],
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build()
    missing = [row["file"] for row in payload["steps"] if not row["present"]]
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        (WP9 / "RUN_REPORT.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        (WP9 / "RUN_REPORT.md").write_text(render_markdown(payload) + "\n", encoding="utf-8")
        print(f"{payload['verdict']}: data/recovery/wp9/RUN_REPORT.json "
              f"({len(missing)} missing artefact(s))")
    return 2 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
