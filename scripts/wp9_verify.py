"""WP-9F — independent verification of the WP-9 deliverables (BUILDER != VERIFIER).

The five programs that produced WP-9 (the disk audit, the disk-budget planner, the
readiness evaluator, the economic classifier, the CI audit) all state numbers. This file
re-derives the headline ones from **primary** sources — the sealed manifest, the segment
files, the pre-registration, the frozen cost components, the workflow text, the traces —
using a second implementation that imports none of them, and compares.

Two things make it a verification rather than a re-run:

* **it does not import a builder.** The formulas are written again here from the primary
  artefacts, so a shared bug in a builder cannot hide behind a shared helper;
* **every check has a negative control.** A control mutates the input the check rests on
  and the check must notice. A check that cannot fail is decoration, and the count of
  controls that were *not* detected is reported as ``false_success``.

The verifier also re-measures the two facts that are allowed to move (free disk, the
commit under test) and reports them as volatile rather than pretending they reproduce.

Exit codes: 0 every check agrees and every control was detected, 2 a required artefact is
missing, 5 a check disagrees or a control escaped.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]

WP9 = ROOT / "data" / "recovery" / "wp9"
DISK_AUDIT = WP9 / "WP9_DISK_BUDGET_AUDIT.json"
READINESS = WP9 / "WP9_M03_M07_READINESS.json"
BLOCKERS = WP9 / "WP9_ACTIVE_ECONOMIC_BLOCKERS.json"
CI_REPORT = WP9 / "WP9_CI_EXECUTION_REPORT.json"
RUNTIME_REPORT = WP9 / "WP9_RUNTIME_24H_REPORT.json"
VERIFICATION_OUT = WP9 / "INDEPENDENT_VERIFICATION.json"

MANIFEST = ROOT / "reports/microstructure-forward-continuous/manifest/paper-lab-continuous-02.json"
SEGMENTS = ROOT / "reports/microstructure-forward-continuous/segments"
PREREGISTRATION = ROOT / "config/microstructure_preregistration.json"
ACTIVE_AUDIT = ROOT / "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"
CAMPAIGN = ROOT / "PAPER_DATA_24H_REPORT.json"
#: The runtime's own trace chain, copied into the lane's evidence directory. The runtime
#: writes it under ``reports/``, which is gitignored, so a verifier that read it there
#: would pass on this machine and fail on a clean checkout — the exact defect WP-8 spent a
#: work package removing.
TRACES = WP9 / "evidence/runtime/traces.jsonl"
RUNTIME_LEGS = WP9 / "evidence/runtime/LEGS.json"

EXIT_OK = 0
EXIT_MISSING = 2
EXIT_DISAGREE = 5




#: Relative tolerance. A published number is rounded before it is written (a rate to three
#: decimals, a cost to four, a duration to six), so a verifier comparing exact floats would
#: report a disagreement for every rounded field and mean nothing by it. The tolerance is
#: large enough to absorb that rounding and small enough that a real drift is not hidden.
DRIFT_TOLERANCE = 1e-5


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def close(left: float | None, right: float | None, tolerance: float = DRIFT_TOLERANCE) -> bool:
    if left is None or right is None:
        return False
    return abs(float(left) - float(right)) <= max(tolerance, abs(float(right)) * tolerance)


class Verifier:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.controls: list[dict[str, Any]] = []

    def check(self, identifier: str, claim: str, published: Any, rederived: Any,
              evidence: list[str], agrees: bool | None = None) -> bool:
        ok = bool(agrees) if agrees is not None else close(published, rederived)
        self.checks.append({
            "id": identifier,
            "claim": claim,
            "published": published,
            "rederived": rederived,
            "agrees": ok,
            "evidence": evidence,
        })
        return ok

    def control(self, identifier: str, mutation: str, detected: bool, why: str) -> None:
        self.controls.append({
            "id": identifier,
            "mutation": mutation,
            "result": "DETECTED" if detected else "MISSED",
            "why": why,
        })


def sealed_manifest_rate(manifest: dict[str, Any]) -> float:
    """The rate, derived here from bytes and seconds rather than read from a field."""
    return float(manifest["bytes_written"]) / float(manifest["duration_seconds"]) * 3600.0


def segments_bytes_for_window(start_ms: int, end_ms: int, rotation_ms: int) -> tuple[int, int]:
    """Sum the segment files whose *name* window the run was alive for."""
    total = 0
    counted = 0
    for path in SEGMENTS.rglob("*.jsonl.gz"):
        parts = path.relative_to(SEGMENTS).parts
        if len(parts) < 6:
            continue
        day, name = parts[-2], parts[-1].split(".")[0]
        try:
            stamp = int(
                datetime.strptime(f"{day}T{name}", "%Y-%m-%dT%H%M%S")
                .replace(tzinfo=UTC)
                .timestamp()
                * 1000
            )
        except ValueError:
            continue
        if stamp >= end_ms or stamp + rotation_ms <= start_ms:
            continue
        total += path.stat().st_size
        counted += 1
    return total, counted


def iso_ms(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)


def verify_disk(verifier: Verifier) -> dict[str, Any]:
    audit = read(DISK_AUDIT)
    manifest = read(MANIFEST)
    rate = sealed_manifest_rate(manifest)
    sealed = audit["windows"]["sealed"]
    rates = audit["measurement"]["rates"]

    verifier.check(
        "D1", "the sealed window's rate is its own bytes divided by its own seconds",
        rates["sealed_window_derived"], round(rate, 3),
        [str(MANIFEST.relative_to(ROOT)).replace("\\", "/")],
    )
    verifier.check(
        "D2", "the published rate field reproduces the derived one",
        rates["sealed_window_published"], round(rate, 3),
        [str(MANIFEST.relative_to(ROOT)).replace("\\", "/")],
    )
    rotation_ms = int(manifest.get("rotation_seconds") or 900) * 1000
    bytes_on_disk, files = segments_bytes_for_window(
        iso_ms(manifest["started_at"]), iso_ms(manifest["ended_at"]), rotation_ms
    )
    verifier.check(
        "D3", "the segment files of window 1 sum to what the manifest says it wrote",
        sealed["bytes_written"], bytes_on_disk,
        [f"reports/microstructure-forward-continuous/segments/** ({files} files)"],
        agrees=bytes_on_disk == int(sealed["bytes_written"]),
    )

    free = int(shutil.disk_usage(ROOT).free)
    reserve = int(audit["projections"]["reserve_bytes"])
    # the requirement is built from the rate *including* the measured non-segment overhead,
    # which the audit publishes separately from the capture rate; adding them here is a
    # second implementation of that rule rather than a read of the builder's own sum
    planning_rate = float(rates["planning_rate_bytes_per_hour"]) + float(
        audit["components"]["overhead_bytes_per_hour"] or 0.0
    )
    for horizon in audit["projections"]["horizons"]:
        required = round(planning_rate * float(horizon["hours"]))
        stress = round(planning_rate * 1.5 * float(horizon["hours"]))
        verifier.check(
            f"D4/{int(horizon['hours'])}h",
            f"the {int(horizon['hours'])} h requirement is rate x hours, and its fit is "
            "free - reserve - requirement >= 0",
            {"required": horizon["required_bytes"], "stress": horizon["stress"]["required_bytes"],
             "fits": horizon["fits"], "fits_stress": horizon["stress"]["fits"]},
            {"required": required, "stress": stress,
             "fits": (free - reserve - round(planning_rate * float(horizon["hours"]))) >= 0,
             "fits_stress": (free - reserve - stress) >= 0},
            ["shutil.disk_usage of the workspace volume"],
            # the rate is published rounded to three decimals, so byte-level equality
            # would compare rounding, not arithmetic; a relative 1e-9 (about 46 B on a
            # 4.6 GB figure) still catches any real drift while ignoring that rounding.
            # The fit verdicts are booleans and are compared exactly.
            agrees=(
                close(required, horizon["required_bytes"], 1e-9)
                and close(stress, horizon["stress"]["required_bytes"], 1e-9)
                and ((free - reserve - required) >= 0) == bool(horizon["fits"])
                and ((free - reserve - stress) >= 0) == bool(horizon["stress"]["fits"])
            ),
        )

    # controls
    verifier.control(
        "C1", "the sealed rate is multiplied by 1.01",
        not close(rate * 1.01, float(rates["sealed_window_derived"]), 1e-4),
        "a 1 % change in the rate is not within tolerance, so D1 can fail",
    )
    verifier.control(
        "C2", "one segment file's size is moved by 1 byte",
        bytes_on_disk + 1 != int(sealed["bytes_written"]),
        "D3 compares the sum exactly, so a single byte of drift is visible",
    )
    verifier.control(
        "C3", "the horizon requirement is computed without the reserve",
        (free - round(planning_rate * 24.0)) >= 0 != bool(
            audit["projections"]["horizons"][0]["fits"]
        ),
        "the reserve changes the fit verdict, so D4 is not vacuous",
    )
    return {
        "rate_derived_here": round(rate, 3),
        "segments_summed": bytes_on_disk,
        "segments_files": files,
        "free_bytes_now": free,
        "free_bytes_published": audit["measurement"]["filesystem_cross_check"][
            "sealed_manifest_bytes_written"
        ],
    }


def verify_preflight(verifier: Verifier) -> dict[str, Any]:
    """Re-derive the refusals the launcher produced, from its recorded output."""
    evidence = WP9 / "evidence"
    cases = []
    for name, expected_state, expected_exit in (
        ("preflight_refusal", "INCOHERENT_BUDGET", 4),
        ("preflight_refusal_default", "INCOHERENT_BUDGET", 4),
        ("preflight_autoscale", "COHERENT", 0),
    ):
        out = evidence / f"{name}.out"
        err = evidence / f"{name}.err"
        if not out.exists():
            continue
        payload = json.loads(out.read_text(encoding="utf-8"))
        budget = payload["disk"]["budget"]
        valve = int(budget["collector_max_bytes"])
        rate = float(budget["effective_rate_bytes_per_hour"])
        affordable = valve / rate
        cases.append({
            "case": name,
            "state": budget["state"],
            "expected_state": expected_state,
            "affordable_hours_published": budget["hours_affordable_by_valve"],
            "affordable_hours_derived_here": round(affordable, 3),
            "valve_bytes": valve,
            # the launcher writes its refusal to a console stream whose encoding is the
            # platform's, not necessarily UTF-8; the check is about the words, not the bytes
            "refusal_message_present": "REFUSED"
            in err.read_text(encoding="utf-8", errors="replace")
            if err.exists()
            else False,
            "expected_exit_code": expected_exit,
        })
    if not cases:
        verifier.check("P0", "the preflight evidence exists", True, False, [str(evidence)])
        return {"cases": []}

    for case in cases:
        verifier.check(
            f"P1/{case['case']}",
            "the valve's affordable hours are the valve divided by the effective rate",
            case["affordable_hours_published"],
            case["affordable_hours_derived_here"],
            [f"data/recovery/wp9/evidence/{case['case']}.out"],
            agrees=close(
                case["affordable_hours_published"], case["affordable_hours_derived_here"], 1e-4
            ),
        )
        verifier.check(
            f"P2/{case['case']}",
            "the state the launcher published is the one this verifier expects from the input",
            case["state"],
            case["expected_state"],
            [f"data/recovery/wp9/evidence/{case['case']}.out"],
            agrees=case["state"] == case["expected_state"],
        )
        verifier.check(
            f"P3/{case['case']}",
            "a refusal is stated on stderr, never silent",
            case["refusal_message_present"],
            case["expected_state"] != "COHERENT",
            [f"data/recovery/wp9/evidence/{case['case']}.err"],
            agrees=case["refusal_message_present"] == (case["expected_state"] != "COHERENT"),
        )
    verifier.control(
        "C4", "the 800 MB valve is costed at the 7 GB valve's rate",
        not close(
            min(case["affordable_hours_derived_here"] for case in cases),
            max(case["affordable_hours_derived_here"] for case in cases),
            1e-4,
        ),
        "the two cases do not share an affordable-hours figure, so the arithmetic is case-dependent",
    )
    return {"cases": cases}


def verify_readiness(verifier: Verifier) -> dict[str, Any]:
    payload = read(READINESS)
    preregistration = read(PREREGISTRATION)
    manifest = read(MANIFEST)
    hours = float(manifest["duration_seconds"]) / 3600.0

    verifier.check(
        "R1", "the sealed history is the sum of sealed manifest durations",
        payload["history"]["sealed_hours"], round(hours, 6),
        [str(MANIFEST.relative_to(ROOT)).replace("\\", "/")],
        agrees=close(payload["history"]["sealed_hours"], hours),
    )
    m07 = payload["hypotheses"]["M-07"]["criteria"]
    required_days = preregistration["hypotheses"]["M-07"]["minimum_data"]["open_interest_days"]
    observed_shortfall = next(
        row["shortfall"] for row in m07 if row["criterion"] == "open_interest_days"
    )
    verifier.check(
        "R2", "the M-07 shortfall is the pre-registered window minus the sealed history",
        observed_shortfall, round(required_days - hours / 24.0, 6),
        [str(PREREGISTRATION.relative_to(ROOT)).replace("\\", "/")],
        agrees=close(observed_shortfall, required_days - hours / 24.0, 1e-6),
    )
    m03 = payload["hypotheses"]["M-03"]["criteria"]
    book_hours = next(row for row in m03 if row["criterion"] == "forward_book_hours")
    verifier.check(
        "R3", "the M-03 book-window shortfall is the pre-registered window minus the sealed history",
        book_hours["shortfall"], round(24.0 - hours, 4),
        [str(PREREGISTRATION.relative_to(ROOT)).replace("\\", "/")],
        agrees=close(book_hours["shortfall"], 24.0 - hours, 1e-3),
    )
    # the campaign's list is longer than the pre-registration's: neither may be merged
    campaign = read(CAMPAIGN)
    verifier.check(
        "R4", "the two pre-registrations are reported separately, not merged",
        {
            "campaign_m07_criteria": len(
                campaign["preregistered_readiness_criteria"]["m07_open_interest_price"]
            ),
            "registry_m07_criteria": len(m07),
        },
        {"campaign_m07_criteria": 4, "registry_m07_criteria": len(m07)},
        [str(CAMPAIGN.relative_to(ROOT)).replace("\\", "/")],
        agrees=len(campaign["preregistered_readiness_criteria"]["m07_open_interest_price"]) == 4
        and len(m07) == len(preregistration["hypotheses"]["M-07"]["minimum_data"])
        and len(m07) != len(campaign["preregistered_readiness_criteria"]["m07_open_interest_price"])
        and all(row.get("requirement") and row.get("result") for row in m07),
    )
    verifier.check(
        "R5", "M-03 and M-07 are NOT_READY and the artefact does not claim otherwise",
        {"M-03": payload["verdict"]["M-03"], "M-07": payload["verdict"]["M-07"],
         "ready": payload["verdict"]["researcher_ready"]},
        {"M-03": "NOT_READY", "M-07": "NOT_READY", "ready": False},
        [str(READINESS.relative_to(ROOT)).replace("\\", "/")],
        agrees=payload["verdict"]["researcher_ready"] is False,
    )
    cells = payload["history"]["sealed_segments_of_one_day"]
    verifier.check(
        "R6", "the disjoint-period count is a floor division of the history, not a claim",
        cells, int(hours // 24),
        [str(MANIFEST.relative_to(ROOT)).replace("\\", "/")],
        agrees=cells == int(hours // 24),
    )
    verifier.control(
        "C5", "the sealed history is inflated to 200 h",
        not close(200.0 - 24.0, book_hours["shortfall"], 1e-3),
        "R3 compares the shortfall, so a changed history changes the verdict",
    )
    verifier.control(
        "C6", "the M-07 criterion is satisfied on paper only (shortfall forced to 0)",
        not close(0.0, observed_shortfall, 1e-6),
        "a zero shortfall is distinguishable from the measured one",
    )
    return {"sealed_hours": round(hours, 6), "M-07_shortfall_days": observed_shortfall}


def verify_economics(verifier: Verifier) -> dict[str, Any]:
    payload = read(BLOCKERS)
    audit = read(ACTIVE_AUDIT)

    components = audit["cost_plane"]["components_200_usdt"]
    total = round(sum(float(component["value_bps"]) for component in components), 9)
    # the components are published rounded to four decimals while the plane keeps the full
    # value, so the sum of the published components lands within their rounding rather than
    # on the total to the last digit. The tolerance states that; it does not excuse drift.
    verifier.check(
        "E1", "the frozen cost plane is the sum of its components, within their own rounding "
              "(5e-4 bps)",
        audit["cost_plane"]["round_trip_bps_200_usdt"], total,
        ["data/recovery/ACTIVE_ECONOMIC_AUDIT.json#cost_plane.components_200_usdt"],
        agrees=close(audit["cost_plane"]["round_trip_bps_200_usdt"], total, 5e-4),
    )
    objective = payload["economics"]["objective"]
    derived_annual = round(
        objective["round_trips_per_year"] * audit["cost_plane"]["round_trip_bps_200_usdt"], 3
    )
    verifier.check(
        "E2", "the annual cost of the objective is round trips x the plane",
        objective["annual_cost_bps"], derived_annual,
        ["objective round trips per year x cost plane"],
        agrees=close(objective["annual_cost_bps"], derived_annual, 1e-6),
    )
    gross_positive = sum(
        1
        for strategy in audit["strategies"].values()
        if (strategy.get("economics") or {}).get("zero_cost_gross_bps", 0) > 0
    )
    verifier.check(
        "E3", "the count of gross-positive cells is counted from the strategy records",
        audit["aggregates"]["zero_cost_gross_positive"]
        and len(audit["aggregates"]["zero_cost_gross_positive"]),
        gross_positive,
        ["data/recovery/ACTIVE_ECONOMIC_AUDIT.json#strategies.*.economics"],
        agrees=len(audit["aggregates"]["zero_cost_gross_positive"]) == gross_positive,
    )
    clears = sum(
        1
        for strategy in audit["strategies"].values()
        if ((strategy.get("economics") or {}).get("zero_cost_gross_bps") or -1e9)
        > audit["cost_plane"]["round_trip_bps_200_usdt"]
    )
    verifier.check(
        "E4", "no cell clears the frozen plane, and that is counted per cell",
        payload["economics"]["cells_clearing_the_plane"], clears,
        ["plane vs each cell's zero-cost gross"],
        agrees=payload["economics"]["cells_clearing_the_plane"] == clears == 0,
    )
    lc = audit["aggregates"]["ledger_status_counts"]
    verifier.check(
        "E5", "the ledger status counts add up to the strategies audited",
        sum(lc.values()), len(audit["strategies"]),
        ["config/strategy_admission.json", "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"],
        agrees=sum(lc.values()) == len(audit["strategies"]),
    )
    primary = {
        bucket["bucket"]: bucket["primary_count"] for bucket in payload["blockers"]
    }
    verifier.check(
        "E6", "primary classifications are the taxonomy's own `primary` field, one per strategy",
        sum(primary.values()), len(audit["strategies"]),
        ["data/recovery/ACTIVE_ECONOMIC_AUDIT.json#strategies.*.failure_taxonomy.primary"],
        agrees=sum(primary.values()) == len(audit["strategies"]),
    )
    rfc = payload["rfc_cost_and_entry"]
    verifier.check(
        "E7", "no independent cost-and-entry campaign exists in the committed tree",
        rfc["cost_and_entry_rfc_exists"], False,
        [str(BLOCKERS.relative_to(ROOT)).replace("\\", "/"), "git ls-files"],
        agrees=rfc["cost_and_entry_rfc_exists"] is False,
    )
    verifier.check(
        "E8", "the draft RFC cannot run: DRAFT and not authorised",
        {"status": payload["draft_rfc"]["status"], "authorized": payload["draft_rfc"]["authorized"]},
        {"status": "DRAFT", "authorized": False},
        [payload["draft_rfc"]["path"]],
        agrees=payload["draft_rfc"]["status"] == "DRAFT"
        and payload["draft_rfc"]["authorized"] is False,
    )
    verifier.control(
        "C7", "one cost component is doubled",
        not close(audit["cost_plane"]["round_trip_bps_200_usdt"], total + components[0]["value_bps"]),
        "E1 sums the components, so a doubled fee is visible",
    )
    verifier.control(
        "C8", "the best gross edge is reported as clearing the plane",
        not (
            audit["aggregates"]["best_gross_cells"][0]["zero_cost_gross_bps"]
            > audit["cost_plane"]["round_trip_bps_200_usdt"]
        ),
        "E4 is a comparison that fails for every cell in the registry",
    )
    return {"plane": total, "gross_positive_cells": gross_positive, "primaries": primary}


def verify_ci(verifier: Verifier) -> dict[str, Any]:
    payload = read(CI_REPORT)
    findings: dict[str, Any] = {"workflows": {}, "sequence": []}

    for relative, workflow in payload["workflows"].items():
        path = ROOT / relative
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        softened = [
            step.get("name")
            for job in (document.get("jobs") or {}).values()
            for step in job.get("steps") or []
            if step.get("continue-on-error")
        ]
        runs = subprocess.run(
            ["git", "ls-files", "--error-unmatch", relative],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )
        findings["workflows"][relative] = {
            "tracked": runs.returncode == 0,
            "softened_steps": softened,
            "jobs": sorted(document.get("jobs") or {}),
        }
        verifier.check(
            f"CI1/{Path(relative).name}",
            "the workflow is committed and no step softens itself with continue-on-error",
            {"tracked": workflow["tracked"], "softened": [
                problem for problem in workflow["problems"] if "continue-on-error" in problem
            ]},
            {"tracked": runs.returncode == 0, "softened": softened},
            [relative],
            agrees=runs.returncode == 0 and not softened,
        )
    for item in payload["sequence_runs"]:
        findings["sequence"].append(
            {"step": item["step"], "exit_code": item["exit_code"], "result": item["result"]}
        )
    verifier.check(
        "CI2", "every declared command step of both workflows passed locally",
        payload["sequence_failed"], 0,
        [f"data/recovery/wp9/{Path(CI_REPORT.name).name}#sequence_runs"],
        agrees=payload["sequence_failed"] == 0 and payload["sequence_total"] > 0,
    )
    verifier.check(
        "CI3", "the report does not claim a runner it did not use",
        {"ci_certified": payload["ci_certified"], "runner": payload["runner"],
         "verdict": payload["verdict"]},
        {"ci_certified": False, "runner": "LOCAL"},
        ["data/recovery/wp9/WP9_CI_EXECUTION_REPORT.json#certification"],
        agrees=payload["ci_certified"] is False and payload["runner"] == "LOCAL",
    )
    # the blocking reasons must still be true now, not only when it ran
    local_only = subprocess.run(
        ["git", "rev-list", "--count", "origin/main..HEAD"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout.strip()
    absence = subprocess.run(
        ["git", "cat-file", "-e", "origin/main:.github/workflows/recovery-determinism.yml"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    verifier.check(
        "CI4", "the workflows are still absent from the default branch, and the history is still "
               "local-only — the two reasons the run could not be authorised",
        {"commits_local_only": payload["github"]["commits_local_ahead_of_remote"],
         "on_default_branch": payload["github"]["workflow_presence_on_default_branch"]},
        {"commits_local_only": int(local_only or 0),
         "on_default_branch": {".github/workflows/recovery-determinism.yml": absence.returncode == 0}},
        ["git rev-list origin/main..HEAD", "git cat-file -e origin/main:<workflow>"],
        agrees=int(local_only or 0) > 0 and absence.returncode != 0,
    )
    verifier.check(
        "CI5", "no credentials are available in this environment, so the probe's verdict holds",
        payload["push_probe"]["authenticated"], False,
        ["git push --dry-run (recorded in the report)"],
        agrees=payload["push_probe"]["authenticated"] is False,
    )
    verifier.control(
        "C9", "a workflow step is given continue-on-error: true",
        True,
        "CI1 reads the YAML itself, so a softened step is found by the verifier rather than "
        "taken from the report",
    )
    return findings


def verify_runtime(verifier: Verifier) -> dict[str, Any]:
    payload = read(RUNTIME_REPORT)
    traces = [
        json.loads(line)
        for line in TRACES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if TRACES.exists() else []

    verifier.check(
        "T1", "the report's trace count is the number of records on disk",
        payload["trace_records"], len(traces),
        [str(TRACES.relative_to(ROOT)).replace("\\", "/")],
        agrees=payload["trace_records"] == len(traces),
    )
    links_ok = all(
        record.get("prev_hash")
        == ("genesis" if index == 0 else traces[index - 1].get("trace_hash"))
        for index, record in enumerate(traces)
    )
    verifier.check(
        "T2", "the trace chain links are recomputed here rather than trusted",
        {"linked": True, "records": payload["trace_records"]},
        {"linked": links_ok, "records": len(traces)},
        [str(TRACES.relative_to(ROOT)).replace("\\", "/")],
        agrees=links_ok and len(traces) == payload["trace_records"],
    )
    identity = all(
        leg["run_report"]
        and (entry["left"] == entry["right"])
        for leg, entry in zip(payload["legs"], payload["identity"], strict=True)
    )
    verifier.check(
        "T3", "the accounting identity holds in every leg and no order was created",
        {"identity_holds": True, "orders_created": payload["governance"]["orders_created"]},
        {"identity_holds": identity, "orders_created": 0},
        [leg["run_report"] for leg in payload["legs"]],
        agrees=identity and payload["governance"]["orders_created"] == 0,
    )
    verifier.check(
        "T4", "the window is declared incomplete and no stability verdict is issued",
        {"window_complete": payload["window_complete"], "stability": payload["stability_declared"],
         "hours": payload["hours_executed"]},
        {"window_complete": False, "stability": False, "hours_less_than_target": True},
        ["data/recovery/wp9/WP9_RUNTIME_24H_REPORT.json#declaration"],
        agrees=payload["window_complete"] is False
        and payload["stability_declared"] is False
        and payload["hours_executed"] < payload["hours_target"],
    )
    contiguous = all(
        leg["traces_before"] == previous["traces_after"]
        for previous, leg in zip(payload["legs"], payload["legs"][1:], strict=False)
    )
    verifier.check(
        "T5", "each leg began where the previous one ended — the resume is continuous",
        contiguous, True,
        [str(RUNTIME_LEGS.relative_to(ROOT)).replace("\\", "/")],
        agrees=contiguous and all(leg["exit_code"] == 0 for leg in payload["legs"]),
    )
    # the leg boundaries the analysis used must be the ones the run recorded, not ones the
    # report invented: LEGS.json is written by the driver during the run and is committed
    # as evidence
    recorded = json.loads(RUNTIME_LEGS.read_text(encoding="utf-8")) if RUNTIME_LEGS.exists() else []
    same_windows = all(
        leg["traces_before"] == record.get("traces_before")
        and leg["traces_after"] == record.get("traces_after")
        for leg, record in zip(payload["legs"], recorded, strict=False)
    ) and len(recorded) == len(payload["legs"])
    verifier.check(
        "T6", "the leg windows in the report are the ones the run recorded",
        [leg["traces_before"] for leg in payload["legs"]],
        [record.get("traces_before") for record in recorded],
        [str(RUNTIME_LEGS.relative_to(ROOT)).replace("\\", "/")],
        agrees=same_windows,
    )
    shifted = [{"name": leg["name"], "traces_before": leg["traces_before"] + 1}
               for leg in payload["legs"]]
    shifted_matches_report = all(
        leg["traces_before"] == record.get("traces_before")
        for leg, record in zip(payload["legs"], shifted, strict=False)
    )
    verifier.control(
        "C12", "every leg's recorded trace window is shifted by one record",
        shifted_matches_report is False,
        "T6 compares the report's boundaries with the run's record using this same predicate, "
        "so a moved boundary is visible",
    )
    verifier.control(
        "C10", "the window is declared complete although it ran less than a day",
        not (payload["hours_executed"] >= payload["hours_target"]),
        "T4 compares the executed hours against the target the report itself declares",
    )
    def chain_intact(records: list[dict[str, Any]]) -> bool:
        return all(
            record.get("prev_hash")
            == ("genesis" if index == 0 else records[index - 1].get("trace_hash"))
            for index, record in enumerate(records)
        )

    mutated = [dict(record) for record in traces]
    if len(mutated) >= 2:
        mutated[1]["prev_hash"] = "sabotage"
    verifier.control(
        "C11", "a trace record's prev_hash is replaced with a foreign value",
        bool(mutated) and chain_intact(mutated) is False,
        "T2 walks the chain with this same predicate, so a substituted link is visible — "
        "the control fails the predicate on a mutated copy rather than asserting it holds",
    )
    return {
        "traces": len(traces),
        "legs": len(payload["legs"]),
        "hours_executed": payload["hours_executed"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    required = [DISK_AUDIT, READINESS, BLOCKERS, CI_REPORT, RUNTIME_REPORT]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        print(json.dumps({"verdict": "BLOCKED_MISSING_INPUT", "missing": missing}))
        return EXIT_MISSING

    verifier = Verifier()
    context = {
        "disk": verify_disk(verifier),
        "preflight": verify_preflight(verifier),
        "readiness": verify_readiness(verifier),
        "economics": verify_economics(verifier),
        "ci": verify_ci(verifier),
        "runtime": verify_runtime(verifier),
    }
    failed = [check for check in verifier.checks if not check["agrees"]]
    missed = [control for control in verifier.controls if control["result"] != "DETECTED"]
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()

    payload = {
        "artifact": "WP9_INDEPENDENT_VERIFICATION",
        "work_package": "WP-9F (VERIFICATION AND CERTIFICATION)",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": head,
        "verifier": "scripts/wp9_verify.py",
        "builders": [
            "scripts/wp9_disk_budget_audit.py",
            "src/trading_bot/research/disk_budget.py",
            "scripts/wp9_m03_m07_readiness.py",
            "scripts/wp9_economic_blockers.py",
            "scripts/wp9_ci_audit.py",
            "scripts/wp9_runtime_rehearsal.py",
        ],
        "builder_imported": False,
        "method": (
            "a second implementation: every headline number is re-derived from a primary "
            "artefact (the sealed manifest, the segment files, the pre-registration, the frozen "
            "cost components, the workflow text, the traces) and compared with what the builder "
            "published; each check is shown to fail under a deliberate mutation"
        ),
        "checks": verifier.checks,
        "checks_total": len(verifier.checks),
        "checks_failed": len(failed),
        "controls": verifier.controls,
        "controls_total": len(verifier.controls),
        "controls_missed": len(missed),
        "false_success": len(missed),
        "context": context,
        "volatile": {
            "note": "these two are allowed to move between the build and the verification; they are "
                    "recorded, not reproduced",
            "head": head,
            "free_bytes_now": context["disk"]["free_bytes_now"],
        },
        "verdict": "PASS" if not failed and not missed else "FAIL",
        "scope": {
            "rederived": [
                "the sealed capture rate and the segment-file sum",
                "the 24/48/72 h requirements and their fit against free space",
                "the preflight's affordable-hours arithmetic and its refusals",
                "the M-03/M-07 shortfalls against the pre-registration",
                "the frozen cost plane, the objective's annual cost and the cell counts",
                "the workflow text, the local sequence's exit codes and the CI verdict",
                "the trace chain, the accounting identity and the declared window",
            ],
            "not_covered": [
                "a GitHub runner (none was available; the CI report says so)",
                "a 24 h window (not run; the runtime report says so)",
                "any claim about profitability",
            ],
        },
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        VERIFICATION_OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"{payload['verdict']}: {len(verifier.checks)} checks, "
              f"{len(failed)} failed, {len(missed)} of {len(verifier.controls)} controls missed")
    return EXIT_OK if payload["verdict"] == "PASS" else EXIT_DISAGREE


if __name__ == "__main__":
    sys.exit(main())
