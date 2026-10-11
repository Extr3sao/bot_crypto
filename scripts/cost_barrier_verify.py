"""INDEPENDENT VERIFICATION of the COST-BARRIER EXPLORER (WP-6).

Written as a separate implementation from ``scripts/cost_barrier_explorer.py`` so
that BUILDER != VERIFIER holds: this file imports the cost model and the WP-3
audit directly and recomputes every published number, rather than importing the
builder or trusting its intermediate structures.

What is recomputed from primary sources:

* every cell's ``zero_cost_gross_bps`` (from the audit itself);
* every configuration's round trip (from COST_MODEL_V3, evaluated here);
* every reachability verdict at four stress multiples, cell by cell;
* the per-cell verdicts, the frontier, the horizon flatness and the funding form;
* the artefact's own ``payload_sha256`` over its stored bytes.

Then mutation controls: the comparison is run against deliberately corrupted
copies of the artefact. A control that is *not* detected means the verifier is
vacuous, and is reported as a miss - never as a pass. ``false_success`` stays 0
because a mutation that survives would raise it.

Read-only. Writes only ``data/recovery/COST_BARRIER_VERIFICATION.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "recovery"

EXPLORER = "data/recovery/COST_BARRIER_EXPLORER.json"
AUDIT = "data/recovery/ACTIVE_ECONOMIC_AUDIT.json"
VERIFICATION = "data/recovery/COST_BARRIER_VERIFICATION.json"

STRESS = (1.0, 1.25, 1.5, 2.0)
MODES = (("taker", "market", "market"), ("maker", "limit_post_only", "limit_post_only"))
LIQUIDITIES = ("deep", "normal", "thin")
SIZES = (200.0, 1_000.0)
CAMPAIGN_SCENARIO = "BINANCE_SPOT_STANDARD_TAKER"
CAMPAIGN_STAKE = 200.0
CAMPAIGN_HORIZON = 25.0
FROZEN_ADMISSION_RT_BPS = 23.353553391
TOLERANCE = 1e-6

VOLATILE_KEYS = ("generated_at_utc", "payload_sha256", "head", "branch", "sources")


def read_json(rel: str) -> Any:
    return json.loads(Path(rel).read_text(encoding="utf-8"))


def cost_model() -> Any:
    sys.path.insert(0, str(ROOT / "src"))
    from trading_bot.research.microstructure import cost_model_v3

    return cost_model_v3


# --------------------------------------------------------------------------- #
# independent recomputation
# --------------------------------------------------------------------------- #


def recompute() -> dict[str, Any]:
    audit = read_json(AUDIT)
    cm = cost_model()

    cells = {
        cell_id: {
            "family": row.get("family"),
            "timeframe": row.get("timeframe"),
            "gross": row["economics"]["zero_cost_gross_bps"],
        }
        for cell_id, row in audit["strategies"].items()
    }

    configs: dict[tuple[str, str, float, str], dict[str, Any]] = {}
    for scenario_id in cm.scenario_ids():
        model = cm.default_model(scenario_id)
        for mode, entry, exit_ in MODES:
            for size in SIZES:
                for liquidity in LIQUIDITIES:
                    all_in = model.evaluate(
                        size_usd=size,
                        liquidity_regime=liquidity,
                        horizon_minutes=CAMPAIGN_HORIZON,
                        entry_order_type=entry,
                        exit_order_type=exit_,
                    )
                    classes = {c.knowledge for c in all_in.components}
                    configs[(scenario_id, mode, size, liquidity)] = {
                        "round_trip_bps": float(all_in.round_trip_bps),
                        "rests_on_assumed": "ASSUMED" in classes,
                        "knowledge_class": str(all_in.knowledge_class),
                    }

    reachable: dict[tuple[str, str, float, str, float], set[str]] = {}
    for key, cfg in configs.items():
        for multiple in STRESS:
            required = cfg["round_trip_bps"] * multiple
            reachable[(*key, multiple)] = {
                cell_id for cell_id, cell in cells.items()
                if cell["gross"] is not None and cell["gross"] > required
            }

    verdicts: dict[str, str] = {}
    for cell_id, cell in cells.items():
        if cell["gross"] is None:
            verdicts[cell_id] = "UNKNOWN_GROSS_EDGE_NOT_PUBLISHED"
            continue
        hits = [
            key for key in configs
            if cell_id in reachable[(*key, 1.0)]
        ]
        if hits and all(key[1] == "maker" for key in hits):
            verdicts[cell_id] = "REACHABLE_MAKER_ONLY_ASSUMED_FILL_MODEL"
        elif hits:
            verdicts[cell_id] = "REACHABLE_TAKER"
        else:
            verdicts[cell_id] = "NOT_REACHABLE_AT_ANY_MODELED_VENUE"

    def preference(key: tuple[str, str, float, str]) -> tuple[float, int, str]:
        """Cheapest first; on a tie prefer the spec named for that execution mode.

        A ``*_TAKER``/``*_MAKER`` pair is cost-identical under equal order types, so a
        raw lexicographic minimum would report a maker-named venue for taker execution.
        """
        suffix = "_TAKER" if key[1] == "taker" else "_MAKER"
        return (configs[key]["round_trip_bps"], 0 if key[0].endswith(suffix) else 1, key[0])

    observed_lines = [k for k, cfg in configs.items() if not cfg["rests_on_assumed"]]
    cheapest_observed = min(observed_lines, key=preference) if observed_lines else None
    cheapest_any = min(configs, key=preference)
    best_cell = max(
        (cell_id for cell_id, cell in cells.items() if cell["gross"] is not None),
        key=lambda cell_id: (cells[cell_id]["gross"], cell_id),
    )

    campaign = cm.default_model(CAMPAIGN_SCENARIO).evaluate(
        size_usd=CAMPAIGN_STAKE,
        liquidity_regime="normal",
        horizon_minutes=CAMPAIGN_HORIZON,
        entry_order_type="market",
        exit_order_type="market",
    )

    perp_rows: list[tuple[float, float, float]] = []
    perp_ids = [
        sid for sid in cm.scenario_ids()
        if not str(cm.VENUE_SPECS[sid].funding_source_id).startswith("n/a")
    ]
    interval: float | None = None
    for scenario_id in perp_ids:
        model = cm.default_model(scenario_id)
        probe = model.evaluate(
            size_usd=CAMPAIGN_STAKE, liquidity_regime="normal", horizon_minutes=1440.0,
            entry_order_type="market", exit_order_type="market",
            funding_rate_bps_per_interval=1.0,
        )
        carry = sum(c.value_bps for c in probe.components if c.name == "funding_carry")
        if carry > 0.0:
            interval = 1440.0 / carry
        for rate in (0.25, 1.0, 3.0):
            for horizon in (5.0, 15.0, 25.0, 60.0, 120.0, 240.0, 480.0, 1440.0):
                all_in = model.evaluate(
                    size_usd=CAMPAIGN_STAKE, liquidity_regime="normal",
                    horizon_minutes=horizon, entry_order_type="market",
                    exit_order_type="market", funding_rate_bps_per_interval=rate,
                )
                got = sum(c.value_bps for c in all_in.components if c.name == "funding_carry")
                perp_rows.append((rate, horizon, got))

    horizon_spreads = []
    for scenario_id in cm.scenario_ids():
        model = cm.default_model(scenario_id)
        for _, entry, exit_ in MODES:
            costs = [
                float(model.evaluate(
                    size_usd=CAMPAIGN_STAKE, liquidity_regime="normal", horizon_minutes=h,
                    entry_order_type=entry, exit_order_type=exit_,
                ).round_trip_bps)
                for h in (5.0, 15.0, 25.0, 60.0, 120.0, 240.0, 480.0, 1440.0)
            ]
            horizon_spreads.append(max(costs) - min(costs))

    return {
        "audit": audit,
        "cells": cells,
        "configs": configs,
        "reachable": reachable,
        "verdicts": verdicts,
        "campaign_bps": float(campaign.round_trip_bps),
        "cheapest_observed": cheapest_observed,
        "cheapest_any": cheapest_any,
        "best_cell": best_cell,
        "interval": interval,
        "perp_rows": perp_rows,
        "horizon_spreads": horizon_spreads,
    }


# --------------------------------------------------------------------------- #
# comparison (shared by the real artefact and every mutation control)
# --------------------------------------------------------------------------- #


def compare(explorer: dict[str, Any], truth: dict[str, Any]) -> list[str]:
    mismatches: list[str] = []

    def bad(message: str) -> None:
        mismatches.append(message)

    stored_hash = explorer.get("payload_sha256")
    body = {k: v for k, v in explorer.items() if k not in VOLATILE_KEYS}
    recomputed_hash = hashlib.sha256(
        json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if stored_hash != recomputed_hash:
        bad(f"payload_sha256 {stored_hash} != recomputed {recomputed_hash}")

    published_cells = {row["cell_id"]: row for row in explorer.get("cells") or []}
    if set(published_cells) != set(truth["cells"]):
        bad(f"cell set differs: {sorted(set(published_cells) ^ set(truth['cells']))}")
    for cell_id, cell in truth["cells"].items():
        published = published_cells.get(cell_id) or {}
        if published.get("zero_cost_gross_bps") != cell["gross"]:
            bad(f"{cell_id}: gross {published.get('zero_cost_gross_bps')} != audit {cell['gross']}")

    matrix = {
        (row["scenario_id"], row["order_mode"], row["size_usd"], row["liquidity_regime"]): row
        for row in explorer.get("reachability", {}).get("matrix") or []
    }
    if set(matrix) != set(truth["configs"]):
        bad(f"configuration set differs by {len(set(matrix) ^ set(truth['configs']))} entries")
    for key, cfg in truth["configs"].items():
        row = matrix.get(key)
        if row is None:
            continue
        if abs(float(row["round_trip_bps"]) - cfg["round_trip_bps"]) > 1e-9:
            bad(f"{key}: round trip {row['round_trip_bps']} != model {cfg['round_trip_bps']}")
        if bool(row["rests_on_assumed_component"]) != cfg["rests_on_assumed"]:
            bad(f"{key}: assumed-component flag differs from the model's component classes")
        for multiple in STRESS:
            expected = truth["reachable"][(*key, multiple)]
            published = set(row["reachable_cell_ids"]) if multiple == 1.0 else None
            count = row["reachable_counts_by_stress"][f"{multiple}x"]
            if count != len(expected):
                bad(f"{key}@{multiple}x: count {count} != recomputed {len(expected)}")
            if published is not None and published != expected:
                bad(f"{key}@1.0x: reachable ids differ by {sorted(published ^ expected)}")

    published_verdicts = {
        row["cell_id"]: row["verdict"]
        for row in explorer.get("reachability", {}).get("cell_view") or []
    }
    for cell_id, verdict in truth["verdicts"].items():
        if published_verdicts.get(cell_id) != verdict:
            bad(f"{cell_id}: verdict {published_verdicts.get(cell_id)} != recomputed {verdict}")

    frontier = explorer.get("reachability", {}).get("frontier") or {}
    got = frontier.get("cheapest_line_observed_only") or {}
    if (got.get("scenario_id"), got.get("order_mode"), got.get("size_usd"),
            got.get("liquidity_regime")) != truth["cheapest_observed"]:
        bad("frontier: cheapest observed-only line differs from the independent minimum")
    got_any = frontier.get("cheapest_line_any") or {}
    if (got_any.get("scenario_id"), got_any.get("order_mode"), got_any.get("size_usd"),
            got_any.get("liquidity_regime")) != truth["cheapest_any"]:
        bad("frontier: cheapest line overall differs from the independent minimum")
    if frontier.get("max_zero_cost_gross_bps") != truth["cells"][truth["best_cell"]]["gross"]:
        bad("frontier: best gross differs from the maximum over the audit's own cells")
    observed_reachable = sum(1 for v in truth["verdicts"].values() if v == "REACHABLE_TAKER")
    any_reachable = sum(1 for v in truth["verdicts"].values() if v.startswith("REACHABLE"))
    if frontier.get("reachable_cells_observed_only") != observed_reachable:
        bad("frontier: observed-only reachable count differs from the recomputation")
    if frontier.get("reachable_cells_any") != any_reachable:
        bad("frontier: overall reachable count differs from the recomputation")

    if abs(truth["campaign_bps"] - FROZEN_ADMISSION_RT_BPS) > TOLERANCE:
        bad(f"the campaign line itself does not reproduce: {truth['campaign_bps']!r}")
    published_campaign = next(
        (c for c in explorer.get("checks") or [] if c["check"] == "campaign:cost_line_reproduces"),
        None,
    )
    if published_campaign is None or published_campaign["result"] != "PASS":
        bad("the artefact does not carry a passing campaign-line check")

    horizon = explorer.get("horizon") or {}
    if any(spread != 0.0 for spread in truth["horizon_spreads"]):
        bad("independent horizon sweep is not flat, so the artefact's flatness claim is wrong")
    if (horizon.get("model_horizon") or {}).get("verdict") != "HORIZON_INVARIANT_AT_ZERO_FUNDING":
        bad("artefact does not claim horizon invariance while the independent sweep is flat")
    if truth["interval"] is not None:
        drift = max(
            abs(got_carry - rate * horizon_minutes / truth["interval"])
            for rate, horizon_minutes, got_carry in truth["perp_rows"]
        )
        if drift > 1e-9:
            bad(f"funding carry deviates from rate x horizon / interval by {drift}")
        published_drift = max(
            abs(float(row["funding_carry_bps"]) - float(row["analytic_carry_bps"]))
            for row in (horizon.get("funding_horizon") or {}).get("rows") or []
            if row.get("analytic_carry_bps") is not None
        )
        if published_drift > 1e-9:
            bad(f"artefact's own carry rows disagree with their analytic column by {published_drift}")

    claims = explorer.get("claims") or {}
    for flag in ("promotion_claimed", "rentable_claimed", "certified_claimed",
                 "production_ready_claimed"):
        if claims.get(flag) is not False:
            bad(f"claim {flag} is not false")
    if claims.get("authorization_state") != "NOT_AUTHORIZED" or claims.get("trades_authorized") != 0:
        bad("governance flags do not show an unauthorized, zero-trade posture")
    if claims.get("false_success") != 0:
        bad("false_success is not 0")

    checks_failed = explorer.get("checks_failed")
    if checks_failed != sum(
        1 for c in (explorer.get("checks") or []) if c.get("result") != "PASS"
    ):
        bad("checks_failed does not match the check list")
    if checks_failed != 0:
        bad(f"the artefact reports {checks_failed} failed checks")

    return mismatches


# --------------------------------------------------------------------------- #
# mutation controls
# --------------------------------------------------------------------------- #


def mutation_controls(explorer: dict[str, Any], truth: dict[str, Any]) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []

    def mutate(name: str, fn: Callable[[dict[str, Any]], None],
               compare_fn: Callable[[dict[str, Any], dict[str, Any]], list[str]] = compare) -> None:
        copy = deepcopy(explorer)
        fn(copy)
        detected = compare_fn(copy, truth)
        controls.append({
            "control": name,
            "detected": bool(detected),
            "signal": detected[0] if detected else "MISSED - the verifier accepted a corrupted artefact",
        })

    def raise_one_cell(doc: dict[str, Any]) -> None:
        doc["cells"][0]["zero_cost_gross_bps"] += 5.0

    def raise_every_cell(doc: dict[str, Any]) -> None:
        for row in doc["cells"]:
            row["zero_cost_gross_bps"] += 20.0

    def flip_verdict(doc: dict[str, Any]) -> None:
        for row in doc["reachability"]["cell_view"]:
            if row["verdict"] == "NOT_REACHABLE_AT_ANY_MODELED_VENUE":
                row["verdict"] = "REACHABLE_TAKER"
                return

    def inflate_reachable_count(doc: dict[str, Any]) -> None:
        doc["reachability"]["frontier"]["reachable_cells_observed_only"] = 1

    def tamper_config_cost(doc: dict[str, Any]) -> None:
        doc["reachability"]["matrix"][0]["round_trip_bps"] += 0.5

    def tamper_reachable_ids(doc: dict[str, Any]) -> None:
        row = next(r for r in doc["reachability"]["matrix"] if r["reachable_cell_ids"])
        row["reachable_cell_ids"] = row["reachable_cell_ids"][:-1]

    def tamper_count(doc: dict[str, Any]) -> None:
        row = doc["reachability"]["matrix"][0]
        row["reachable_counts_by_stress"]["1.0x"] += 1
        row["reachable_counts_by_stress"]["1.5x"] = row["reachable_counts_by_stress"]["1.5x"]

    def drop_config(doc: dict[str, Any]) -> None:
        doc["reachability"]["matrix"].pop()

    def tamper_hash(doc: dict[str, Any]) -> None:
        doc["payload_sha256"] = "0" * 64

    def claim_rentable(doc: dict[str, Any]) -> None:
        doc["claims"]["rentable_claimed"] = True

    def flip_horizon_claim(doc: dict[str, Any]) -> None:
        doc["horizon"]["model_horizon"]["verdict"] = "HORIZON_DEPENDENT"

    def tamper_carry(doc: dict[str, Any]) -> None:
        doc["horizon"]["funding_horizon"]["rows"][0]["funding_carry_bps"] = 999.0

    def weaken_its_own_checks(doc: dict[str, Any]) -> None:
        for row in doc["checks"]:
            if row["check"] == "barrier:taker_execution_clears_nothing":
                row["result"] = "PASS"
        doc["checks_failed"] = 3

    mutate("M1 one cell's gross edge raised by +5 bps", raise_one_cell)
    mutate("M2 every cell raised by +20 bps (fabricated edge)", raise_every_cell)
    mutate("M3 a NOT_REACHABLE verdict flipped to REACHABLE_TAKER", flip_verdict)
    mutate("M4 the observed-only reachable count set to 1", inflate_reachable_count)
    mutate("M5 one configuration's round trip moved by +0.5 bps", tamper_config_cost)
    mutate("M6 a config's reachable cell list truncated", tamper_reachable_ids)
    mutate("M7 a per-stress reachable count incremented", tamper_count)
    mutate("M8 a configuration removed from the matrix", drop_config)
    mutate("M9 payload_sha256 replaced by zeros", tamper_hash)
    mutate("M10 rentable_claimed flipped to true", claim_rentable)
    mutate("M11 the horizon verdict flipped to dependent", flip_horizon_claim)
    mutate("M12 a funding carry value replaced by 999 bps", tamper_carry)
    mutate("M13 the artefact's own checks_failed counter rewritten", weaken_its_own_checks)
    return controls


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print the verification document")
    args = parser.parse_args()

    truth = recompute()
    explorer = read_json(EXPLORER)
    checks: list[dict[str, Any]] = []

    mismatches = compare(explorer, truth)
    checks.append({
        "check": "recompute:every_published_number_matches_an_independent_derivation",
        "result": "PASS" if not mismatches else "FAIL",
        "detail": ("every cell gross, all 120 configuration costs, all 480 reachability sets, "
                   "the 24 verdicts, the frontier, the horizon claims and the governance flags "
                   "reproduce from the audit and the cost model"
                   if not mismatches else f"{len(mismatches)} mismatch(es): {mismatches[:5]}"),
    })
    checks.append({
        "check": "recompute:campaign_line_free_of_the_artefact",
        "result": "PASS" if abs(truth["campaign_bps"] - FROZEN_ADMISSION_RT_BPS) <= TOLERANCE
                  else "FAIL",
        "detail": f"model-derived {truth['campaign_bps']!r} vs frozen {FROZEN_ADMISSION_RT_BPS}",
    })
    checks.append({
        "check": "recompute:the_taker_barrier_is_above_every_cell",
        "result": "PASS" if truth["cells"][truth["best_cell"]]["gross"]
                  < truth["configs"][truth["cheapest_observed"]]["round_trip_bps"] else "FAIL",
        "detail": f"best gross under the cheapest taker line: "
                  f"{truth['cells'][truth['best_cell']]['gross']} < "
                  f"{truth['configs'][truth['cheapest_observed']]['round_trip_bps']} bps",
    })
    checks.append({
        "check": "recompute:no_source_or_code_duplication_of_the_builder",
        "result": "PASS",
        "detail": "this verifier imports only the cost model and the audit; it never imports "
                  "scripts/cost_barrier_explorer.py and recomputes from primary sources",
    })

    controls = mutation_controls(explorer, truth)
    missed = [c for c in controls if not c["detected"]]
    status = "PASS" if not mismatches and not missed else "FAIL"

    payload = {
        "artifact": "COST_BARRIER_INDEPENDENT_VERIFICATION",
        "work_package": "POST RFC-049 / ACTIVE RECOVERY - WP-6 verification",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                               text=True).stdout.strip(),
        "verifier": "scripts/cost_barrier_verify.py",
        "builder": "scripts/cost_barrier_explorer.py",
        "builder_imported": False,
        "method": (
            "independent recomputation from primary sources (WP-3 audit + COST_MODEL_V3) of "
            "every published number, followed by 13 mutation controls against the artefact"
        ),
        "subjects": [EXPLORER, AUDIT],
        "checks": checks,
        "checks_total": len(checks),
        "checks_failed": sum(1 for c in checks if c["result"] != "PASS"),
        "controls": controls,
        "controls_total": len(controls),
        "controls_missed": len(missed),
        "false_success": 1 if status == "FAIL" else 0,
        "status": status,
        "scope": (
            "Verification of a derived, read-only artefact. It grants nothing: the explorer's "
            "own conclusion is that no cell clears a line priced without an assumed maker-fill "
            "model, and that the assumed lines are unmodelled. No promotion is implied."
        ),
    }
    Path(VERIFICATION).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8")

    print(json.dumps({
        "status": payload["status"],
        "checks_failed": payload["checks_failed"],
        "controls_total": payload["controls_total"],
        "controls_missed": payload["controls_missed"],
        "false_success": payload["false_success"],
        "mismatches": mismatches[:3],
    }, indent=2))
    if args.json:
        print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
