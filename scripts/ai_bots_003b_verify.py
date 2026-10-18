"""ai_bots_003b_verify — verificador independiente del motor de ejecución causal.

``BUILDER != VERIFIER``. Este script **no importa** ``trading_bot``: vuelve a implementar
la cadena de hashes del ledger y todas las identidades económicas desde cero, con la
biblioteca estándar. Si compartiera el código del carril, un error de criterio en el
carril se reproduciría aquí y el verificador diría que todo está bien.

Qué comprueba, y por qué cada una es una condición y no un adorno:

* **PIT de la cotización** — cada relleno pagó un precio que existía en o después de la
  respuesta del modelo, y dentro de la ventana de la opinión. Es el defecto B-01.
* **Resolución** — el precio pagado es una apertura de vela declarada como tal; no hay
  precios inventados dentro de una vela (B-02).
* **Stops** — una salida por stop nunca se acredita mejor que su nivel; una salida por
  objetivo nunca se acredita peor que la entrada (B-03/B-04).
* **Identidades netas** — PnL, costes, caja, curva y la equidad del motor de riesgo
  cierran entre sí, y cada fila CLOSE reconstruye su propio neto (B-05).
* **Nada se pierde en silencio** — toda decisión operable tiene exactamente una fila
  terminal (relleno, desenlace o rechazo), y ningún ``position_id`` se reutiliza.

Uso:

    python scripts/ai_bots_003b_verify.py --ledger <ruta> --summary <ruta.json> --out <ruta.json>

Salida: códigos reales. ``0`` sólo si **todas** las comprobaciones pasan; ``1`` si alguna
falla; ``2`` si faltan artefactos (no es un aprobado).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GENESIS = "0" * 64
TOLERANCE = 1e-6
ACTIONABLE = {"OPEN_LONG", "OPEN_SHORT", "CLOSE"}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""

    def to_row(self) -> dict[str, Any]:
        return {"name": self.name, "status": "PASS" if self.ok else "FAIL", "detail": self.detail}


@dataclass
class Verdict:
    checks: list[Check] = field(default_factory=list)

    @property
    def failures(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.ok]

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name=name, ok=bool(ok), detail=detail))

    def to_row(self) -> dict[str, Any]:
        return {
            "checks": [check.to_row() for check in self.checks],
            "passed": sum(1 for check in self.checks if check.ok),
            "failed": len(self.failures),
            "verdict": "PASS" if not self.failures else "FAIL",
        }


# -- the chain, reimplemented ---------------------------------------------------


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def line_hash(seq: int, prev_sha256: str, entry: dict[str, Any]) -> str:
    return hashlib.sha256(
        canonical({"seq": seq, "prev_sha256": prev_sha256, "entry": entry}).encode()
    ).hexdigest()


def load_rows(path: Path | str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for raw in handle:
            if raw.strip():
                rows.append(json.loads(raw))
    return rows


def reseal(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recompute the chain after a deliberate edit.

    Used by the mutation tests: a tampered row must be caught by the *economic* check, so
    the chain is resealed to stop the hash check from masking which rule was violated.
    A verifier that only caught edits by hash would not verify anything about the numbers.
    """

    sealed: list[dict[str, Any]] = []
    previous = GENESIS
    for index, row in enumerate(rows):
        entry = dict(row["entry"])
        digest = line_hash(index + 1, previous, entry)
        sealed.append(
            {"seq": index + 1, "prev_sha256": previous, "entry": entry, "sha256": digest}
        )
        previous = digest
    return sealed


def rows_of(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [row["entry"] for row in rows if row["entry"].get("kind") == kind]


# -- the checks -----------------------------------------------------------------


def verify_rows(rows: list[dict[str, Any]], summary: dict[str, Any]) -> Verdict:
    verdict = Verdict()
    fills = rows_of(rows, "FILL")
    closes = rows_of(rows, "CLOSE")
    #: A DECISION's own ``seq`` lives on the chain line, not inside the entry; the fills and
    #: outcomes point at it through ``decision_seq``, so the two must be joined explicitly.
    decisions = [
        dict(row["entry"], ledger_seq=row.get("seq"))
        for row in rows
        if row["entry"].get("kind") == "DECISION"
    ]
    outcomes = rows_of(rows, "DECISION_OUTCOME")
    rejects = rows_of(rows, "GUARD_REJECT")
    runs = rows_of(rows, "RUN")
    run = runs[0] if runs else {}
    lane = run.get("lane") or {}
    max_age = int(lane.get("max_opinion_age_ms") or 0)

    # 1. the chain itself
    previous = GENESIS
    broken: list[str] = []
    for position, row in enumerate(rows, start=1):
        if row.get("seq") != position:
            broken.append(f"seq {row.get('seq')} at line {position}")
        if row.get("prev_sha256") != previous:
            broken.append(f"prev mismatch at seq {row.get('seq')}")
        expected = line_hash(int(row.get("seq", 0)), str(row.get("prev_sha256")), row["entry"])
        if row.get("sha256") != expected:
            broken.append(f"hash mismatch at seq {row.get('seq')}")
        previous = str(row.get("sha256"))
    verdict.add("ledger_hash_chain", not broken, "; ".join(broken[:5]))

    # 2. the run declared its execution conventions
    required = {
        "execution_quote": "bar_open",
        "gap_policy": "open_on_gap",
        "stop_coverage": "entry_at_open_full_bar",
    }
    declared = lane and all(lane.get(key) == value for key, value in required.items())
    verdict.add(
        "run_declares_execution_conventions",
        bool(declared) and max_age > 0,
        f"lane={ {k: lane.get(k) for k in required} } max_opinion_age_ms={max_age}",
    )

    # 3-7. the fill quote
    early = [f for f in fills if f.get("quote_ts_ms", 0) < f.get("received_at_ms", 0)]
    verdict.add(
        "fill_quote_at_or_after_answer",
        not early and bool(fills),
        f"{len(early)} fills paid a price that predates the answer",
    )

    before_decision = [f for f in fills if f.get("quote_ts_ms", 0) < f.get("decision_ts_ms", 0)]
    verdict.add(
        "fill_quote_at_or_after_decision",
        not before_decision,
        f"{len(before_decision)} fills predate the decision instant",
    )

    lag_wrong = [
        f
        for f in fills
        if f.get("quote_lag_ms") != f.get("quote_ts_ms", 0) - f.get("received_at_ms", 0)
    ]
    verdict.add(
        "fill_quote_lag_is_measured",
        not lag_wrong,
        f"{len(lag_wrong)} fills carry a lag that is not quote_ts - received_at",
    )

    bad_source = [
        f
        for f in fills
        if f.get("quote_source") != "bar_open"
        or f.get("quote_ts_ms") != f.get("ts_ms")
        or float(f.get("quote_price") or 0) <= 0
    ]
    verdict.add(
        "fill_quote_is_a_declared_bar_open",
        not bad_source,
        f"{len(bad_source)} fills are not a bar open from the declared dataset",
    )

    stale = [
        f
        for f in fills
        if max_age > 0 and f.get("quote_ts_ms", 0) - f.get("decision_ts_ms", 0) > max_age
    ]
    verdict.add(
        "fill_quote_within_opinion_window",
        not stale,
        f"{len(stale)} fills are older than max_opinion_age_ms={max_age}",
    )

    # 8-9. exits relative to their entry, and how precisely the instant is known
    late_exit = [
        c
        for c in closes
        if c.get("entry_quote_ts_ms") is None or c.get("ts_ms", 0) < c.get("entry_quote_ts_ms", 0)
    ]
    verdict.add(
        "exit_not_before_entry_quote",
        not late_exit,
        f"{len(late_exit)} closes precede the quote that opened them or lack provenance",
    )

    window_wrong = [
        c
        for c in closes
        if c.get("exit_ts_resolution") != "bar"
        or not (c.get("exit_ts_lower_bound_ms", 0) <= c.get("ts_ms", 0) <= c.get("exit_ts_upper_bound_ms", 0))
    ]
    verdict.add(
        "exit_window_is_declared",
        not window_wrong,
        f"{len(window_wrong)} closes do not declare the bar window they happened in",
    )

    # 10-11. stop and target prices are not credited better than provable
    bad_stop: list[str] = []
    for close in closes:
        exit_price = float(close.get("exit_price") or 0)
        stop = close.get("stop_loss_price")
        if close.get("exit_reason") != "stop_loss":
            continue
        if stop is None:
            bad_stop.append(f"{close.get('trade_id')} stop without a level")
            continue
        level = float(stop)
        # A protective stop is directional: a long must not be credited above its stop and
        # a short must not be credited below it. Both are "better than the order allowed".
        if close.get("side") == "buy" and exit_price > level * (1 + 1e-9):
            bad_stop.append(
                f"{close.get('trade_id')} long exited at {exit_price} above its stop {level}"
            )
        if close.get("side") == "sell" and exit_price < level * (1 - 1e-9):
            bad_stop.append(
                f"{close.get('trade_id')} short exited at {exit_price} below its stop {level}"
            )
    verdict.add(
        "stop_never_credited_better_than_its_level",
        not bad_stop,
        "; ".join(bad_stop[:3]),
    )

    bad_direction: list[str] = []
    for close in closes:
        entry = float(close.get("entry_price") or 0)
        exit_price = float(close.get("exit_price") or 0)
        reason = close.get("exit_reason")
        profitable = exit_price > entry if close.get("side") == "buy" else exit_price < entry
        if reason == "take_profit" and not profitable:
            bad_direction.append(f"{close.get('trade_id')} take_profit without a gain")
        if reason == "stop_loss" and profitable:
            # A protective stop cannot close in profit: that would be a claim about a
            # price the protective order was designed to prevent.
            bad_direction.append(f"{close.get('trade_id')} stop_loss booked as a gain")
    verdict.add(
        "success_is_backed_by_its_own_prices",
        not bad_direction,
        "; ".join(bad_direction[:3]),
    )

    # 12-15. the economic identities
    pnl_broken: list[str] = []
    for close in closes:
        rebuilt = (
            float(close.get("reference_gross_pnl_usdt") or 0)
            - float(close.get("execution_cost_usdt") or 0)
            - float(close.get("entry_commission_usdt") or 0)
            - float(close.get("exit_commission_usdt") or 0)
        )
        if abs(rebuilt - float(close.get("pnl_net_usdt") or 0)) > TOLERANCE:
            pnl_broken.append(f"{close.get('trade_id')}: {rebuilt} != {close.get('pnl_net_usdt')}")
    verdict.add(
        "net_pnl_nets_every_named_cost",
        not pnl_broken,
        "; ".join(pnl_broken[:3]),
    )

    reconciliation = summary.get("reconciliation") or {}
    initial = float(reconciliation.get("initial_equity_usdt") or 0)
    final = float(reconciliation.get("final_equity_usdt") or 0)
    realised = sum(float(c.get("pnl_net_usdt") or 0) for c in closes)
    verdict.add(
        "cash_rebuilds_from_realised_pnl",
        abs(final - (initial + realised)) <= 1e-5,
        f"{initial} + {realised} != {final}",
    )

    marked = float(reconciliation.get("marked_equity_usdt") or 0)
    risk_equity = float(summary.get("risk_equity_usdt") or 0)
    verdict.add(
        "risk_equity_matches_marked_equity",
        abs(risk_equity - marked) <= 1e-5,
        f"risk={risk_equity} marked={marked}",
    )

    curve_end = reconciliation.get("curve_end_equity_usdt")
    verdict.add(
        "curve_ends_at_marked_equity",
        curve_end is not None and abs(float(curve_end) - marked) <= 1e-5,
        f"curve={curve_end} marked={marked}",
    )

    # 16-18. bookkeeping: nothing dropped, nothing reused
    verdict.add(
        "counters_match_rows",
        int(summary.get("fills", -1)) == len(fills)
        and int(summary.get("closed_trades", -1)) == len(closes),
        f"summary fills={summary.get('fills')} rows={len(fills)}; "
        f"summary closes={summary.get('closed_trades')} rows={len(closes)}",
    )

    #: A decision is resolved by its risk outcome row, its fill, or a rejection. It may
    #: legitimately own a verdict *and* a fill (approval, then execution), so the check is
    #: "at least one terminal row" here and "at most one fill" below.
    terminal: set[int] = set()
    for row in [*fills, *outcomes, *rejects]:
        seq = row.get("decision_seq")
        if seq is not None:
            terminal.add(int(seq))
    unresolved = [
        d.get("ledger_seq")
        for d in decisions
        if d.get("intent") in ACTIONABLE
        and int(d.get("ledger_seq") or -1) not in terminal
    ]
    verdict.add(
        "every_actionable_decision_is_resolved",
        not unresolved,
        f"{len(unresolved)} actionable decisions have no terminal row: {unresolved[:5]}",
    )

    fills_per_decision: dict[int, int] = {}
    for fill in fills:
        seq = fill.get("decision_seq")
        if seq is not None:
            fills_per_decision[int(seq)] = fills_per_decision.get(int(seq), 0) + 1
    double = [seq for seq, count in fills_per_decision.items() if count > 1]
    verdict.add(
        "one_decision_executes_at_most_once",
        not double,
        f"decisions filled more than once: {double[:5]}",
    )

    filled_ids = [f.get("position_id") for f in fills]
    closed_ids = [c.get("position_id") for c in closes]
    duplicates = {value for value in filled_ids if filled_ids.count(value) > 1}
    orphan_closes = [value for value in closed_ids if value not in set(filled_ids)]
    verdict.add(
        "position_ids_are_unique_and_owned",
        not duplicates and not orphan_closes,
        f"duplicates={sorted(str(value) for value in duplicates)[:3]} "
        f"orphan_closes={orphan_closes[:3]}",
    )

    kinds = [row["entry"].get("kind") for row in rows]
    verdict.add(
        "ledger_is_bracketed_by_run_and_run_end",
        bool(kinds) and kinds[0] == "RUN" and kinds[-1] == "RUN_END",
        f"first={kinds[0] if kinds else None} last={kinds[-1] if kinds else None} rows={len(kinds)}",
    )

    return verdict


def relative(path: Path, root: Path) -> str:
    try:
        return Path(os.path.relpath(path, root)).as_posix()
    except ValueError:  # different drive on Windows
        return path.name


def absolute_paths(value: Any) -> list[str]:
    """Every string in a JSON blob that looks like a machine-specific path."""

    found: list[str] = []
    if isinstance(value, str):
        cleaned = value.replace("\\", "/")
        if cleaned.startswith("/") or (len(cleaned) > 2 and cleaned[1] == ":"):
            found.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(absolute_paths(key))
            found.extend(absolute_paths(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(absolute_paths(item))
    return found


def verify_run(
    ledger_path: Path | str,
    summary: dict[str, Any],
    *,
    root: Path | None = None,
) -> Verdict:
    rows = load_rows(ledger_path)
    verdict = verify_rows(rows, summary)
    leaked = [path for path in absolute_paths(summary) if not path.startswith("http")]
    verdict.add(
        "summary_is_portable_between_roots",
        not leaked,
        f"absolute paths in the summary: {leaked[:5]}",
    )
    return verdict


def mutations(rows: list[dict[str, Any]], summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Reintroduce each defect in the data and require the verifier to notice.

    Each mutation is applied to a deep copy and the chain is resealed, so the hash check
    cannot be the thing that catches it: what must fail is the rule the defect broke.
    """

    def resealed(edit: Any) -> list[dict[str, Any]]:
        copy = json.loads(json.dumps(rows))
        edit(copy)
        return reseal(copy)

    def first(copy: list[dict[str, Any]], kind: str) -> dict[str, Any]:
        return next(row["entry"] for row in copy if row["entry"].get("kind") == kind)

    def fill_before_answer(copy: list[dict[str, Any]]) -> None:
        entry = first(copy, "FILL")
        entry["quote_ts_ms"] = entry["received_at_ms"] - 1

    def fill_before_decision(copy: list[dict[str, Any]]) -> None:
        entry = first(copy, "FILL")
        entry["quote_ts_ms"] = entry["decision_ts_ms"] - 1

    def lag_lie(copy: list[dict[str, Any]]) -> None:
        entry = first(copy, "FILL")
        entry["quote_lag_ms"] = entry["quote_lag_ms"] + 60_000

    def invented_price(copy: list[dict[str, Any]]) -> None:
        entry = first(copy, "FILL")
        entry["quote_source"] = "interpolated"

    def stale_opinion(copy: list[dict[str, Any]]) -> None:
        entry = first(copy, "FILL")
        entry["quote_ts_ms"] = entry["decision_ts_ms"] + 10 * 3_600_000
        entry["ts_ms"] = entry["quote_ts_ms"]

    def pnl_edit(copy: list[dict[str, Any]]) -> None:
        entry = first(copy, "CLOSE")
        entry["pnl_net_usdt"] = float(entry["pnl_net_usdt"]) + 1.0

    def stop_credit(copy: list[dict[str, Any]]) -> None:
        for row in copy:
            entry = row["entry"]
            if (
                entry.get("kind") == "CLOSE"
                and entry.get("exit_reason") == "stop_loss"
                and entry.get("stop_loss_price")
            ):
                level = float(entry["stop_loss_price"])
                # Credit the exit 1 % better than the protective order allowed: above the
                # stop for a long, below it for a short.
                entry["exit_price"] = level * (1.01 if entry.get("side") == "buy" else 0.99)
                return

    def exit_before_entry(copy: list[dict[str, Any]]) -> None:
        entry = first(copy, "CLOSE")
        entry["ts_ms"] = entry["entry_quote_ts_ms"] - 1

    def dropped_terminal(copy: list[dict[str, Any]]) -> None:
        target = first(copy, "FILL")["decision_seq"]
        copy[:] = [
            row
            for row in copy
            if not (
                row["entry"].get("kind") in {"FILL", "DECISION_OUTCOME"}
                and row["entry"].get("decision_seq") == target
            )
        ]

    def duplicated_position(copy: list[dict[str, Any]]) -> None:
        fill = next(row for row in copy if row["entry"].get("kind") == "FILL")
        copy.append(json.loads(json.dumps(fill)))

    cases: list[tuple[str, str, Any]] = [
        ("M-01", "fill_quote_at_or_after_answer", fill_before_answer),
        ("M-02", "fill_quote_at_or_after_decision", fill_before_decision),
        ("M-03", "fill_quote_lag_is_measured", lag_lie),
        ("M-04", "fill_quote_is_a_declared_bar_open", invented_price),
        ("M-05", "fill_quote_within_opinion_window", stale_opinion),
        ("M-06", "net_pnl_nets_every_named_cost", pnl_edit),
        ("M-07", "stop_never_credited_better_than_its_level", stop_credit),
        ("M-08", "exit_not_before_entry_quote", exit_before_entry),
        ("M-09", "every_actionable_decision_is_resolved", dropped_terminal),
        ("M-10", "position_ids_are_unique_and_owned", duplicated_position),
    ]
    report: list[dict[str, Any]] = []
    for code, expected, edit in cases:
        verdict = verify_rows(resealed(edit), summary)
        failing = [check.name for check in verdict.checks if not check.ok]
        report.append(
            {
                "mutation": code,
                "expected_check": expected,
                "failing_checks": failing,
                "caught": expected in failing,
            }
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an AI-BOTS-003 paper run")
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--root", default=None, help="root used to make paths relative")
    parser.add_argument(
        "--mutations",
        action="store_true",
        help="reintroduce each defect and require this verifier to reject it",
    )
    args = parser.parse_args(argv)

    ledger = Path(args.ledger)
    summary_path = Path(args.summary)
    if not ledger.exists() or not summary_path.exists():
        print(
            json.dumps(
                {
                    "verdict": "BLOCKED",
                    "reason": "ARTIFACTS_MISSING",
                    "ledger": ledger.name,
                    "summary": summary_path.name,
                }
            )
        )
        return 2

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if args.mutations:
        rows = load_rows(ledger)
        cases = mutations(rows, summary)
        report = {
            "tool": "ai_bots_003b_verify",
            "mode": "mutations",
            "mutations": cases,
            "caught": sum(1 for case in cases if case["caught"]),
            "total": len(cases),
            "verdict": "PASS" if all(case["caught"] for case in cases) else "FAIL",
        }
        if args.out:
            Path(args.out).write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["verdict"] == "PASS" else 1

    verdict = verify_run(ledger, summary, root=Path(args.root) if args.root else None)
    report = {
        "tool": "ai_bots_003b_verify",
        "verifier": "independent (no trading_bot import)",
        "ledger": relative(ledger, Path(args.root or Path.cwd())),
        "summary": relative(summary_path, Path(args.root or Path.cwd())),
        **verdict.to_row(),
    }
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not verdict.failures else 1


if __name__ == "__main__":
    sys.exit(main())
