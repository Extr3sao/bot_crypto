#!/usr/bin/env python
"""verify_quote_gap — the independent side of WP-PAPER-QUOTE-GAP-002.

This script does not import ``trading_bot``. Everything it asserts is recomputed from the
published artifacts with its own arithmetic:

* the stop and take-profit prices come from the entry and the percentages in the *session-1
  book*, never from the close row that is being checked;
* the minute that proves an exit comes from the minute table the recovery published, and
  the level has to fall inside that minute's high/low;
* ``pnl = gross - entry_commission - exit_commission`` and
  ``equity = initial + sum(closed pnl)`` are recomputed, not read;
* the exemptions the lab declares are compared against the verifier's own allow-list, so a
  report cannot exempt a field it wants the verifier to ignore.

The negative controls mutate a copy of the report until it claims something false and then
expect a failure. A verifier that passes its own controls has shown that it can say no.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

MINUTE_MS = 60_000
TOLERANCE = 1e-6

#: The only body paths a continuous book and a holed resume are allowed to disagree on,
#: stated here rather than trusted from the artifact.
ALLOWED_PATHS = {
    "barrier/bars_committed": "the holed arm never committed the missing bar",
    "closed_digest": "it hashes closed_at, which the reconstruction observes at the minute",
    "risk/last_loss_ms": "derived from the exit instant",
    "state_digest": "digest over the body, including the paths listed here",
    "integrity_digest": "digest over the body, including the paths listed here",
    "session_id": "process lineage",
    "session_index": "process lineage",
    "session_ids": "process lineage",
}
ALLOWED_PREFIXES = {
    "contract/dataset": "the holed dataset has one fewer bar under the barrier",
    "session": "process lineage",
    "counters": "per-process action counters",
    "calls": "per-process provider calls",
    "spend_usd": "per-process provider spend",
    "marks": "mark cache, rewritten by the next bar",
    "entry_provenance": "per-position notes",
    "pending": "orders in flight",
    "stop_reason": "process stop condition",
    "closed_trades[0]/closed_at": "the reconstruction knows the minute, not the bar close",
}


def _check(checks: list[dict[str, Any]], name: str, ok: bool, detail: str = "") -> bool:
    checks.append({"check": name, "ok": bool(ok), "detail": detail})
    return bool(ok)


def _level(side: str, entry: float, pct: float, *, take: bool) -> float:
    """The broker's formulas, written again: a verifier may not reuse the code under test."""
    sign = 1.0 if take else -1.0
    if side == "buy":
        return entry * (1.0 + sign * pct / 100.0)
    return entry * (1.0 - sign * pct / 100.0)


def _walk(left: Any, right: Any, path: str, out: list[dict[str, Any]]) -> None:
    if path in ALLOWED_PATHS:
        return
    for prefix in ALLOWED_PREFIXES:
        if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "["):
            return
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            child = f"{path}/{key}" if path else key
            if key not in left or key not in right:
                out.append({"path": child, "a": left.get(key), "b": right.get(key)})
            else:
                _walk(left[key], right[key], child, out)
        return
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            out.append({"path": path, "a": len(left), "b": len(right)})
            return
        for index, (a, b) in enumerate(zip(left, right, strict=False)):
            _walk(a, b, f"{path}[{index}]", out)
        return
    if isinstance(left, float) or isinstance(right, float):
        try:
            if abs(float(left) - float(right)) <= TOLERANCE:
                return
        except (TypeError, ValueError):
            pass
    if left != right:
        out.append({"path": path, "a": left, "b": right})


def _closes(arm: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in (arm.get("closes") or []) if row.get("kind", "CLOSE") == "CLOSE"]


def _minutes(gap: dict[str, Any]) -> list[dict[str, Any]]:
    return list(gap.get("minutes") or [])


def _touches(minute: dict[str, Any], side: str, level: float, *, stop: bool) -> bool:
    if side == "buy":
        return minute["low"] <= level if stop else minute["high"] >= level
    return minute["high"] >= level if stop else minute["low"] <= level


def _verify_scenario(name: str, scenario: dict[str, Any], checks: list[dict[str, Any]]) -> None:
    arm_a = scenario.get("A") or {}
    arm_b = scenario.get("B") or {}
    session_1 = scenario.get("session_1") or {}
    gap = (arm_b.get("recovery") or {}).get("gap") or {}
    table = _minutes(gap)

    if name in {"both", "partial"}:
        expected = {
            "both": "GAP_EXIT_AMBIGUOUS",
            "partial": "GAP_NOT_COVERED",
        }[name]
        _check(
            checks,
            f"{name}.blocked",
            arm_b.get("status") == "BLOCKED" and arm_b.get("code") == expected,
            f"status={arm_b.get('status')} code={arm_b.get('code')}",
        )
        _check(
            checks,
            f"{name}.no_fill",
            _closes(arm_b) == [] and not (arm_b.get("fills") or []),
            f"{len(_closes(arm_b))} close(s), {len(arm_b.get('fills') or [])} fill(s)",
        )
        _check(
            checks,
            f"{name}.no_resume",
            (arm_b.get("recovery") or {}).get("resume_from_ms") is None,
            f"resume_from_ms={(arm_b.get('recovery') or {}).get('resume_from_ms')}",
        )
        if name == "both":
            touches = gap.get("positions") or []
            _check(
                checks,
                "both.ambiguous_minute_really_holds_both",
                bool(touches)
                and touches[0].get("stop_touch")
                and touches[0].get("take_profit_touch")
                and touches[0]["stop_touch"]["minute_ms"]
                == touches[0]["take_profit_touch"]["minute_ms"],
                str(
                    [row.get("ambiguous_minute_ms") for row in touches]
                ),
            )
        else:
            evidence = (gap.get("evidence") or {}).get("symbols") or {}
            observed = sum(int(item.get("minutes_observed") or 0) for item in evidence.values())
            expected_minutes = int((gap.get("window") or {}).get("minutes_expected") or 0)
            _check(
                checks,
                "partial.coverage_is_short",
                bool(evidence) and observed < expected_minutes,
                f"{observed}/{expected_minutes} minutes observed",
            )
        return

    # -- a resumed arm that ran ------------------------------------------------
    _check(
        checks,
        f"{name}.resumed",
        arm_b.get("status") == "RAN",
        f"status={arm_b.get('status')} code={arm_b.get('code')}",
    )
    if name == "quiet":
        _check(
            checks,
            "quiet.no_reconstruction",
            [row for row in _closes(arm_b) if row.get("phase") == "GAP_RECONSTRUCTION"] == [],
            "a quiet hole must not invent an exit",
        )
        for position in (session_1.get("book") or {}).get("open_positions") or []:
            stop = _level(
                position["side"], position["entry_price"], position["stop_loss_pct"], take=False
            )
            take = _level(
                position["side"],
                position["entry_price"],
                position["take_profit_pct"],
                take=True,
            )
            for side in ("stop", "take"):
                level = stop if side == "stop" else take
                touched = [
                    minute
                    for minute in table
                    if minute["symbol"] == position["symbol"]
                    and _touches(minute, position["side"], level, stop=side == "stop")
                ]
                _check(
                    checks,
                    f"quiet.{side}_not_touched",
                    not touched,
                    f"{len(touched)} minute(s) contain {level:.8f}",
                )

    if name in {"stop", "take"}:
        closes = _closes(arm_b)
        _check(checks, f"{name}.one_close", len(closes) == 1, f"{len(closes)} close(s)")
        if len(closes) == 1:
            close = closes[0]
            position = ((session_1.get("book") or {}).get("open_positions") or [{}])[0]
            stop = _level(
                position["side"], position["entry_price"], position["stop_loss_pct"], take=False
            )
            take = _level(
                position["side"],
                position["entry_price"],
                position["take_profit_pct"],
                take=True,
            )
            expected_reason = "stop_loss" if name == "stop" else "take_profit"
            expected_price = stop if name == "stop" else take
            _check(
                checks,
                f"{name}.reason",
                close.get("exit_reason") == expected_reason,
                f"{close.get('exit_reason')} != {expected_reason}",
            )
            #: ``exit_price`` es el precio *pagado*, después del coste de cruce; la barrera
            #: que el broker sostiene está en ``reference_exit_price``. Comparar el pagado
            #: con la barrera mezclararía el modelo de costes con el nivel.
            _check(
                checks,
                f"{name}.price_is_the_level",
                abs(float(close["exit_reference_price"]) - expected_price) <= TOLERANCE,
                f"{close['exit_reference_price']} vs {expected_price:.8f} derived from "
                "entry/pct",
            )
            _check(
                checks,
                f"{name}.price_from_session_1",
                abs(float(close["exit_reference_price"]) - expected_price) <= TOLERANCE
                and abs(float(position["entry_price"]) - float(close["entry_price"])) <= TOLERANCE,
                "the level and the entry both come from the book session 1 wrote",
            )
            window = gap.get("window") or {}
            _check(
                checks,
                f"{name}.exit_inside_the_hole",
                int(window.get("barrier_ms") or 0)
                < int(close["exit_ts_lower_bound_ms"])
                <= int(close["exit_ts_upper_bound_ms"])
                <= int(window.get("resume_ms") or 0),
                f"exit [{close['exit_ts_lower_bound_ms']}, {close['exit_ts_upper_bound_ms']}] "
                f"hole ({window.get('barrier_ms')}, {window.get('resume_ms')})",
            )
            proving = [
                minute
                for minute in table
                if int(minute["ts_ms"]) == int(close["exit_ts_lower_bound_ms"])
                and minute["symbol"] == close["symbol"]
            ]
            _check(
                checks,
                f"{name}.proving_minute_present",
                len(proving) == 1,
                f"{len(proving)} minute(s) at {close['exit_ts_lower_bound_ms']}",
            )
            if proving:
                minute = proving[0]
                _check(
                    checks,
                    f"{name}.level_inside_the_minute",
                    _touches(
                        minute,
                        close["side"],
                        expected_price,
                        stop=name == "stop",
                    ),
                    f"minute H/L {minute['high']}/{minute['low']} vs level {expected_price:.8f}",
                )
            _check(
                checks,
                f"{name}.no_other_close",
                len(arm_a.get("closes") or []) == 1,
                f"A closed {len(arm_a.get('closes') or [])} time(s)",
            )
            if arm_a.get("closes"):
                continuous = arm_a["closes"][0]
                _check(
                    checks,
                    f"{name}.same_economics_as_continuous",
                    abs(float(continuous["pnl_net_usdt"]) - float(close["pnl_net_usdt"])) <= TOLERANCE
                    and abs(float(continuous["exit_price"]) - float(close["exit_price"]))
                    <= TOLERANCE
                    and abs(
                        float(continuous["exit_reference_price"])
                        - float(close["exit_reference_price"])
                    )
                    <= TOLERANCE,
                    f"pnl {continuous['pnl_net_usdt']} vs {close['pnl_net_usdt']}",
                )

    # -- invariants that hold for any arm --------------------------------------
    for label, arm in (("A", arm_a), ("B", arm_b)):
        if arm.get("status") != "RAN":
            continue
        book = arm.get("book") or {}
        closed = book.get("closed_trades") or []
        ids = [row.get("position_id") for row in closed]
        _check(
            checks,
            f"{name}.{label}.no_duplicate_close",
            len(ids) == len(set(ids)),
            f"{len(ids)} closed row(s), {len(set(ids))} unique position(s)",
        )
        open_ids = {row["position_id"] for row in book.get("open_positions") or []}
        _check(
            checks,
            f"{name}.{label}.open_and_closed_are_disjoint",
            not (open_ids & set(ids)),
            f"overlap {sorted(open_ids & set(ids))}",
        )
        initial = float(book.get("equity") or 0.0) - sum(float(row["pnl"]) for row in closed)
        _check(
            checks,
            f"{name}.{label}.equity_finances_itself",
            abs(initial + sum(float(row["pnl"]) for row in closed) - float(book.get("equity") or 0.0))
            <= TOLERANCE,
            f"initial {initial:.8f} + pnl {sum(float(row['pnl']) for row in closed):.8f} "
            f"vs equity {book.get('equity')}",
        )
        for row in closed:
            net = (
                float(row["gross_pnl"])
                - float(row["entry_commission"])
                - float(row["exit_commission"])
            )
            _check(
                checks,
                f"{name}.{label}.pnl_identity",
                abs(net - float(row["pnl"])) <= TOLERANCE,
                f"{net:.8f} vs {row['pnl']}",
            )
            cost = float(row["reference_gross_pnl"]) - float(row["gross_pnl"])
            _check(
                checks,
                f"{name}.{label}.cost_identity",
                abs(cost - float(row["execution_cost_usdt"])) <= 1e-9,
                f"{cost:.8f} vs {row['execution_cost_usdt']}",
            )

    comparison = scenario.get("book_comparison")
    if comparison is not None:
        claimed = set(comparison.get("exempt") or {}) | set(
            comparison.get("exempt_prefixes") or {}
        )
        extra = sorted(claimed - set(ALLOWED_PATHS) - set(ALLOWED_PREFIXES))
        _check(
            checks,
            f"{name}.exemptions_are_known",
            not extra,
            f"the lab exempted paths the verifier does not accept: {extra}",
        )
        differences: list[dict[str, Any]] = []
        _walk(arm_a.get("book"), arm_b.get("book"), "", differences)
        _check(
            checks,
            f"{name}.bodies_agree",
            not differences,
            json.dumps(differences[:3]),
        )


def verify(report: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    scenarios = report.get("scenarios") or {}
    for name in ("split", "quiet", "stop", "take", "both", "partial"):
        if name not in scenarios:
            _check(checks, f"{name}.present", False, "scenario missing")
            continue
        _verify_scenario(name, scenarios[name], checks)

    corrupt = report.get("corrupt_feed") or {}
    _check(
        checks,
        "corrupt_feed.refused",
        corrupt.get("status") == "REFUSED_AT_LOAD",
        f"status={corrupt.get('status')}",
    )
    concurrent = report.get("concurrent_writer") or {}
    _check(
        checks,
        "concurrent_writer.refused",
        concurrent.get("status") == "REFUSED",
        f"status={concurrent.get('status')}",
    )

    saves = report.get("kill_while_saving") or {}
    outcomes = saves.get("outcomes") or []
    _check(
        checks,
        "kill_save.every_book_readable",
        bool(outcomes) and all(row.get("status") == "READABLE" for row in outcomes),
        str([row.get("status") for row in outcomes]),
    )
    _check(
        checks,
        "kill_save.a_kill_really_happened",
        any(row.get("killed") for row in outcomes),
        f"{sum(1 for row in outcomes if row.get('killed'))} killed of {len(outcomes)}",
    )

    resumes = report.get("kill_while_resuming") or {}
    attempts = resumes.get("attempts") or []
    _check(
        checks,
        "kill_resume.a_kill_really_happened",
        any(row.get("killed") for row in attempts),
        f"{sum(1 for row in attempts if row.get('killed'))} killed of {len(attempts)}",
    )
    _check(
        checks,
        "kill_resume.no_double_close",
        all(
            row.get("closed_after", 0) in {0, 1} and row.get("closed_before", 0) in {0, 1}
            for row in attempts
        ),
        json.dumps([[row.get("closed_before"), row.get("closed_after")] for row in attempts]),
    )
    _check(
        checks,
        "kill_resume.settles_on_one_trade",
        resumes.get("final_closed") == 1 and resumes.get("final_open") == 0,
        f"closed={resumes.get('final_closed')} open={resumes.get('final_open')}",
    )
    _check(
        checks,
        "kill_resume.equity_matches_the_reference",
        abs(
            float(resumes.get("final_equity") or 0.0)
            - float(resumes.get("reference_equity") or 0.0)
        )
        <= TOLERANCE,
        f"{resumes.get('final_equity')} vs {resumes.get('reference_equity')}",
    )
    differences: list[dict[str, Any]] = []
    _walk(
        {"closed": resumes.get("final_closed"), "open": resumes.get("final_open")},
        {"closed": 1, "open": 0},
        "kill_resume",
        differences,
    )
    _check(checks, "kill_resume.state_is_terminal", not differences, json.dumps(differences))

    #: La coherencia del veredicto global se recalcula: un informe que dice ``ok`` mientras
    #: un control falla es exactamente el falso PASS que este script existe para detectar.
    failed = [check["check"] for check in checks if not check["ok"]]
    recomputed = not failed
    claimed = bool(report.get("ok"))
    _check(
        checks,
        "report.ok_matches_its_own_evidence",
        claimed == recomputed,
        f"report says ok={claimed}, recomputed {recomputed}",
    )
    failed = [check["check"] for check in checks if not check["ok"]]
    return {
        "checks": checks,
        "passed": sum(1 for check in checks if check["ok"]),
        "failed": failed,
        "ok": not failed,
        "false_success": int(claimed and not recomputed),
        "digest": hashlib.sha256(
            json.dumps(checks, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


# -- negative controls ----------------------------------------------------------


def _first_reconstruction(report: dict[str, Any]) -> dict[str, Any]:
    return (report["scenarios"]["stop"]["B"]["closes"] or [])[0]


def _mutations() -> dict[str, Any]:
    def inflate_pnl(report: dict[str, Any]) -> None:
        _first_reconstruction(report)["pnl_net_usdt"] += 0.01

    def invent_exit_price(report: dict[str, Any]) -> None:
        _first_reconstruction(report)["exit_price"] += 0.05

    def move_exit_out_of_the_hole(report: dict[str, Any]) -> None:
        _first_reconstruction(report)["exit_ts_lower_bound_ms"] -= 10 * MINUTE_MS
        _first_reconstruction(report)["exit_ts_upper_bound_ms"] -= 10 * MINUTE_MS

    def fake_coverage(report: dict[str, Any]) -> None:
        gap = report["scenarios"]["partial"]["B"]["recovery"]["gap"]
        for item in (gap.get("evidence") or {}).get("symbols", {}).values():
            item["minutes_observed"] = item["minutes_expected"]

    def clean_ambiguity(report: dict[str, Any]) -> None:
        scenario = report["scenarios"]["both"]
        scenario["B"]["status"] = "RAN"
        scenario["B"]["code"] = None
        scenario["B"]["closes"] = [dict(_first_reconstruction(report))]

    def inflate_equity(report: dict[str, Any]) -> None:
        report["scenarios"]["quiet"]["B"]["book"]["equity"] += 100.0

    def duplicate_close(report: dict[str, Any]) -> None:
        book = report["scenarios"]["stop"]["B"]["book"]
        book["closed_trades"].append(dict(book["closed_trades"][0]))

    def hide_the_kill(report: dict[str, Any]) -> None:
        for row in report["kill_while_resuming"]["attempts"]:
            row["killed"] = False

    def claim_false_ok(report: dict[str, Any]) -> None:
        report["ok"] = True
        report["scenarios"]["partial"]["B"]["status"] = "RAN"

    def exempt_a_path(report: dict[str, Any]) -> None:
        report["scenarios"]["quiet"]["book_comparison"]["exempt"]["closed_trades[0]/pnl"] = "x"

    return {
        "pnl_inflado": inflate_pnl,
        "precio_de_salida_inventado": invent_exit_price,
        "salida_fuera_del_hueco": move_exit_out_of_the_hole,
        "cobertura_falsa": fake_coverage,
        "ambiguedad_limpiada": clean_ambiguity,
        "equity_inventada": inflate_equity,
        "cierre_duplicado": duplicate_close,
        "kill_oculto": hide_the_kill,
        "falso_ok": claim_false_ok,
        "exencion_inventada": exempt_a_path,
    }


def negative_controls(report: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name, mutate in _mutations().items():
        candidate = copy.deepcopy(report)
        mutate(candidate)
        outcome = verify(candidate)
        results.append(
            {
                "control": name,
                "detected": not outcome["ok"],
                "first_failure": outcome["failed"][0] if outcome["failed"] else None,
            }
        )
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args(argv)

    report = json.loads(args.lab.read_text(encoding="utf-8"))
    outcome = verify(report)
    controls = negative_controls(report) if args.negative_controls else []
    undetected = [item["control"] for item in controls if not item["detected"]]
    payload = {
        "schema": "QUOTE_GAP_VERIFICATION_V1",
        "lab": str(args.lab),
        "lab_sha256": hashlib.sha256(args.lab.read_bytes()).hexdigest(),
        "checks": outcome["checks"],
        "passed": outcome["passed"],
        "failed": outcome["failed"],
        "ok": outcome["ok"],
        "false_success": 0 if outcome["ok"] else 1,
        "negative_controls": controls,
        "negative_controls_ok": bool(controls) and not undetected,
        "negative_controls_undetected": undetected,
        "independent_of": "scripts/quote_gap_lab.py and trading_bot.vision.gap_recovery",
    }
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "ok": payload["ok"],
                "passed": payload["passed"],
                "failed": payload["failed"],
                "negative_controls": payload["negative_controls"],
                "negative_controls_ok": payload["negative_controls_ok"],
            },
            indent=2,
        )
    )
    return 0 if payload["ok"] and payload["negative_controls_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
