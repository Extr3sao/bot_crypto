"""ai_bots_003c_verify — verificador independiente de la causalidad de la apertura.

``BUILDER != VERIFIER``. Este script **no importa** ``trading_bot``: vuelve a implementar
la cadena de hashes, el calendario UTC (día y semana ISO) y las identidades económicas con
la biblioteca estándar. Un verificador que comparte el criterio del carril reproduce sus
errores de criterio y dice que todo está bien.

Qué comprueba, y por qué cada una es una condición y no un adorno:

* **El stop de apertura se liquida antes de que esa apertura acepte riesgo** — es el P0 de
  BLOCK-C. La comprobación es de *orden dentro del ledger*: ningún relleno ni desenlace de
  riesgo con instante mayor o igual al de un cierre por hueco puede llevar un ``seq``
  anterior al del cierre.
* **El instante del hueco es exacto y su precio es la apertura** — ``OPEN_GAP`` con límites
  iguales y ``gap_price_source=bar_open``; un precio que no está en la serie no se acepta.
* **El stop nunca se acredita mejor que su nivel** — direccional, para largo y para corto.
* **La cotización del relleno existía en o después de la respuesta** — y un precio de una
  vela ausente sólo se acepta con cobertura de una fuente independiente que se nombra.
* **Nada se pierde en silencio** — toda decisión operable tiene fila terminal, y los
  contadores cuadran con las filas.
* **El riesgo recibe la pérdida completa y en la ventana correcta** — ``risk_equity_after``
  = ``risk_equity_before`` + PnL, y el acumulado diario/semanal se recalcula desde cero
  con el calendario de la biblioteca estándar.

Uso:

    python scripts/ai_bots_003c_verify.py --ledger L --summary S.json [--out R.json]
    python scripts/ai_bots_003c_verify.py --ledger L --summary S.json --mutations

Salida: ``0`` sólo si **todas** las comprobaciones pasan; ``1`` si alguna falla; ``2`` si
faltan artefactos (no es un aprobado).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

GENESIS = "0" * 64
TOLERANCE = 1e-6
ACTIONABLE = {"OPEN_LONG", "OPEN_SHORT", "CLOSE"}
KNOWN_RESOLUTIONS = {"OPEN_GAP", "BAR_WINDOW", "QUOTE"}
#: The only price source this replay can prove it had. Anything else must come with a
#: coverage proof that names it, or the row is claiming a venue nobody observed.
REPLAY_BAR_OPEN = "bar_open"
OPEN_PHASE_ORDER = "gap_close>mark>entries>intrabar"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""

    def to_row(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": "PASS" if self.ok else "FAIL",
            "detail": self.detail,
        }


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

    A mutation must be caught by the *rule* it broke, so the hash is repaired first.
    A verifier that only caught edits by hash would verify nothing about the economics.
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
    """Entries of one kind, each carrying the ``seq`` of the line it was written on.

    ``seq`` lives on the chain line, not inside the entry, and the ordering *within* one
    instant is exactly what this verifier checks. Reading an entry without its seq makes
    every order comparison compare 0 with 0, which is how a vacuous check looks like a
    passing one.
    """

    return [
        dict(row["entry"], seq=row.get("seq"))
        for row in rows
        if row["entry"].get("kind") == kind
    ]


# -- the calendar, reimplemented ------------------------------------------------


def day_of(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC).strftime("%Y-%m-%d")


def week_of(ms: int) -> str:
    moment = datetime.fromtimestamp(int(ms) / 1000.0, tz=UTC)
    monday = moment - timedelta(days=moment.weekday())
    return monday.strftime("%Y-%m-%d")


# -- the checks -----------------------------------------------------------------


def verify_rows(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    *,
    coverage: list[dict[str, Any]] | None = None,
    scenario: str | None = None,
) -> Verdict:
    verdict = Verdict()
    fills = rows_of(rows, "FILL")
    closes = rows_of(rows, "CLOSE")
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
    interval = int(lane.get("bar_interval_ms") or 0)
    max_age = int(lane.get("max_opinion_age_ms") or 0)

    # 1. the chain itself, recomputed here
    previous = GENESIS
    broken: list[str] = []
    for position, row in enumerate(rows, start=1):
        if row.get("seq") != position:
            broken.append(f"seq {row.get('seq')} at line {position}")
        if row.get("prev_sha256") != previous:
            broken.append(f"prev mismatch at seq {row.get('seq')}")
        expected = line_hash(
            int(row.get("seq", 0)), str(row.get("prev_sha256")), row["entry"]
        )
        if row.get("sha256") != expected:
            broken.append(f"hash mismatch at seq {row.get('seq')}")
        previous = str(row.get("sha256"))
    verdict.add("ledger_hash_chain", not broken, "; ".join(broken[:5]))

    # 2. the run declares the phase order and the failure policy
    declared = (
        lane.get("open_phase_order") == OPEN_PHASE_ORDER
        and lane.get("data_gap_policy") == "fail_closed_unless_independent_coverage"
        and set(lane.get("exit_ts_resolutions") or []) == KNOWN_RESOLUTIONS
        and lane.get("gap_policy") == "open_on_gap"
        and lane.get("stop_coverage") == "entry_at_open_full_bar"
    )
    verdict.add(
        "run_declares_open_phase_doctrine",
        bool(declared) and max_age > 0 and interval > 0,
        f"phase_order={lane.get('open_phase_order')} gap_policy={lane.get('data_gap_policy')} "
        f"resolutions={lane.get('exit_ts_resolutions')} max_age={max_age}",
    )

    # 3. P0: an open-gap loss is handed over before any risk approval from that instant on
    gap_closes = [c for c in closes if c.get("exit_ts_resolution") == "OPEN_GAP"]
    late_risk: list[str] = []
    for close in gap_closes:
        stamp = int(close.get("ts_ms") or 0)
        seq = int(close.get("seq") or 0)
        for row in [*fills, *outcomes]:
            if int(row.get("ts_ms") or 0) >= stamp and int(row.get("seq") or 0) < seq:
                late_risk.append(
                    f"{row.get('kind')} seq {row.get('seq')} at {row.get('ts_ms')} precedes "
                    f"the gap loss seq {seq} at {stamp}"
                )
    #: ``seq`` lives on the chain line, so the rows are re-joined with it.
    if not gap_closes:
        verdict.add(
            "open_gap_settled_before_new_risk",
            True,
            "no OPEN_GAP row in this ledger: the ordering is not exercised here",
        )
    else:
        verdict.add(
            "open_gap_settled_before_new_risk",
            not late_risk,
            "; ".join(late_risk[:3]),
        )

    # 4. the gap instant is exact and its price is the observable open
    gap_wrong: list[str] = []
    for close in gap_closes:
        stamp = int(close.get("ts_ms") or 0)
        lower = int(close.get("exit_ts_lower_bound_ms") or 0)
        upper = int(close.get("exit_ts_upper_bound_ms") or 0)
        price = float(close.get("exit_reference_price") or 0)
        opened = close.get("gap_open_price")
        if lower != stamp or upper != stamp:
            gap_wrong.append(f"{close.get('trade_id')} window {lower}..{upper} != {stamp}")
        if close.get("gap_price_source") != "bar_open":
            gap_wrong.append(f"{close.get('trade_id')} source={close.get('gap_price_source')}")
        if opened is None or float(opened) <= 0:
            gap_wrong.append(f"{close.get('trade_id')} has no positive gap open")
        elif abs(price - float(opened)) > max(1e-6, abs(float(opened)) * 1e-8):
            gap_wrong.append(f"{close.get('trade_id')} paid {price} but the open was {opened}")
    verdict.add(
        "open_gap_is_an_exact_instant_at_the_observable_open",
        not gap_wrong,
        "; ".join(gap_wrong[:3]),
    )

    # 5. a protective stop is never credited better than the order allowed
    bad_stop: list[str] = []
    for close in closes:
        if close.get("exit_reason") != "stop_loss":
            continue
        level = close.get("stop_loss_price")
        reference = float(close.get("exit_reference_price") or 0)
        if level is None:
            bad_stop.append(f"{close.get('trade_id')} stop without a level")
            continue
        level = float(level)
        if close.get("side") == "buy" and reference > level * (1 + 1e-9):
            bad_stop.append(f"{close.get('trade_id')} long exited at {reference} above {level}")
        if close.get("side") == "sell" and reference < level * (1 - 1e-9):
            bad_stop.append(f"{close.get('trade_id')} short exited at {reference} below {level}")
    verdict.add(
        "stop_never_credited_better_than_its_level",
        not bad_stop,
        "; ".join(bad_stop[:3]),
    )

    # 6. every exit declares how precisely its instant is known
    window_wrong: list[str] = []
    for close in closes:
        resolution = close.get("exit_ts_resolution")
        lower = int(close.get("exit_ts_lower_bound_ms") or 0)
        upper = int(close.get("exit_ts_upper_bound_ms") or 0)
        stamp = int(close.get("ts_ms") or 0)
        if resolution not in KNOWN_RESOLUTIONS:
            window_wrong.append(f"{close.get('trade_id')} resolution={resolution!r}")
            continue
        if not (lower <= stamp <= upper):
            window_wrong.append(f"{close.get('trade_id')} {stamp} outside {lower}..{upper}")
        if resolution in {"OPEN_GAP", "QUOTE"} and (lower != stamp or upper != stamp):
            window_wrong.append(f"{close.get('trade_id')} exact instant declared as a window")
        if resolution == "BAR_WINDOW" and interval > 0 and upper - lower != interval:
            window_wrong.append(
                f"{close.get('trade_id')} window {upper - lower} != interval {interval}"
            )
    verdict.add("exit_instant_resolution_is_declared", not window_wrong, "; ".join(window_wrong[:3]))

    # 7. the fill price existed at or after the answer, and never before the decision
    early = [f for f in fills if int(f.get("quote_ts_ms") or 0) < int(f.get("received_at_ms") or 0)]
    verdict.add(
        "fill_quote_at_or_after_answer",
        not early and bool(fills),
        f"{len(early)} fills paid a price that predates the answer",
    )
    before_decision = [
        f for f in fills if int(f.get("quote_ts_ms") or 0) < int(f.get("decision_ts_ms") or 0)
    ]
    verdict.add(
        "fill_quote_at_or_after_decision",
        not before_decision,
        f"{len(before_decision)} fills predate the decision instant",
    )
    lag_wrong = [
        f
        for f in fills
        if int(f.get("quote_lag_ms") or 0)
        != int(f.get("quote_ts_ms") or 0) - int(f.get("received_at_ms") or 0)
    ]
    verdict.add(
        "fill_quote_lag_is_measured",
        not lag_wrong,
        f"{len(lag_wrong)} fills carry a lag that is not quote_ts - received_at",
    )
    stale = [
        f
        for f in fills
        if max_age > 0 and int(f.get("quote_ts_ms") or 0) - int(f.get("decision_ts_ms") or 0) > max_age
    ]
    verdict.add(
        "fill_quote_within_opinion_window",
        not stale,
        f"{len(stale)} fills are older than max_opinion_age_ms={max_age}",
    )

    # 8. a price is the replay's own bar open, or it comes from the named feed that
    #    covered the hole it was paid in — never from the bars it is replacing
    bad_source: list[str] = []
    for fill in fills:
        covered = fill.get("data_gap_covered_by")
        source = fill.get("quote_source")
        if covered:
            if str(covered) == REPLAY_BAR_OPEN or covered != source:
                bad_source.append(
                    f"{fill.get('position_id')} claims coverage {covered!r} for price "
                    f"source {source!r}"
                )
            missing = fill.get("data_gap_missing_bar_open_ms")
            if missing is None or not (0 < int(missing) < int(fill.get("quote_ts_ms") or 0)):
                bad_source.append(
                    f"{fill.get('position_id')} covered a gap without naming the missing bar"
                )
        elif source != REPLAY_BAR_OPEN:
            bad_source.append(f"{fill.get('position_id')} quote_source={source!r} unproven")
    verdict.add(
        "fill_price_has_a_declared_source",
        not bad_source,
        "; ".join(bad_source[:3]),
    )

    # 9. a hole is refused by default: the rejection must be terminal for its decision
    gap_rejects = [row for row in rejects if row.get("code") == "DATA_GAP"]
    unresolved_gaps: list[str] = []
    for row in gap_rejects:
        decision_seq: int | None = row.get("decision_seq")
        if decision_seq is None:
            unresolved_gaps.append(f"seq {row.get('seq')} names no decision")
            continue
        if int(row.get("missing_bar_open_ms") or 0) <= 0:
            unresolved_gaps.append(f"seq {row.get('seq')} does not name the missing bar")
        if int(row.get("missing_bars") or 0) < 1:
            unresolved_gaps.append(f"seq {row.get('seq')} counts no missing bar")
        if [f for f in fills if f.get("decision_seq") == decision_seq]:
            unresolved_gaps.append(f"decision {decision_seq} met a hole and still filled")
    verdict.add(
        "data_gap_is_terminal_and_named",
        not unresolved_gaps,
        "; ".join(unresolved_gaps[:3]),
    )

    # 10. the risk engine moves by exactly the net PnL of each close
    hand_off: list[str] = []
    for close in closes:
        before = close.get("risk_equity_before")
        after = close.get("risk_equity_after")
        if before is None or after is None:
            hand_off.append(f"{close.get('trade_id')} without a risk hand-off")
            continue
        delta = float(after) - float(before)
        if abs(delta - float(close.get("pnl_net_usdt") or 0)) > TOLERANCE:
            hand_off.append(
                f"{close.get('trade_id')} moved risk equity by {delta} for pnl "
                f"{close.get('pnl_net_usdt')}"
            )
    verdict.add("risk_engine_receives_each_close", not hand_off, "; ".join(hand_off[:3]))

    # 11. the calendar windows, recomputed from the rows with the stdlib clock
    calendar_wrong: list[str] = []
    daily = 0.0
    weekly = 0.0
    current_day: str | None = None
    current_week: str | None = None
    for close in closes:
        #: The instant whose risk window the loss lands in is the bar's open, which is
        #: the lower bound for an intrabar exit and the exact instant for the others.
        instant = int(close.get("exit_ts_lower_bound_ms") or close.get("ts_ms") or 0)
        day = day_of(instant)
        week = week_of(instant)
        if day != current_day:
            daily = 0.0
            current_day = day
        if week != current_week:
            weekly = 0.0
            current_week = week
        daily += float(close.get("pnl_net_usdt") or 0)
        weekly += float(close.get("pnl_net_usdt") or 0)
        if close.get("day_utc") != day:
            calendar_wrong.append(
                f"{close.get('trade_id')} declares day {close.get('day_utc')}, rows say {day}"
            )
        if abs(float(close.get("risk_daily_pnl_after") or 0) - daily) > TOLERANCE:
            calendar_wrong.append(
                f"{close.get('trade_id')} daily {close.get('risk_daily_pnl_after')} != {daily}"
            )
        if abs(float(close.get("risk_weekly_pnl_after") or 0) - weekly) > TOLERANCE:
            calendar_wrong.append(
                f"{close.get('trade_id')} weekly {close.get('risk_weekly_pnl_after')} != {weekly}"
            )
    verdict.add(
        "calendar_windows_rebuilt_from_the_rows",
        not calendar_wrong,
        "; ".join(calendar_wrong[:3]),
    )

    # 12. the economic identity of every close
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
    verdict.add("net_pnl_nets_every_named_cost", not pnl_broken, "; ".join(pnl_broken[:3]))

    # 13. the published reconciliation agrees with the rows
    reconciliation = summary.get("reconciliation") or {}
    initial = float(reconciliation.get("initial_equity_usdt") or 0)
    realised = sum(float(c.get("pnl_net_usdt") or 0) for c in closes)
    final = float(reconciliation.get("final_equity_usdt") or 0)
    verdict.add(
        "cash_rebuilds_from_realised_pnl",
        abs(final - (initial + realised)) <= 1e-5,
        f"{initial} + {realised} != {final}",
    )
    identities = reconciliation.get("identities") or {}
    verdict.add(
        "reconciliation_identities_all_true",
        bool(identities) and all(bool(value) for value in identities.values()),
        json.dumps(identities),
    )
    time_machines = [
        c.get("trade_id")
        for c in closes
        if c.get("entry_quote_ts_ms") is None
        or int(c.get("ts_ms") or 0) < int(c.get("entry_quote_ts_ms") or 0)
    ]
    verdict.add(
        "every_close_after_its_entry_quote",
        not time_machines,
        f"{len(time_machines)} closes precede the quote that opened them or lack provenance",
    )

    # 14. nothing dropped, nothing reused
    verdict.add(
        "counters_match_rows",
        int(summary.get("fills", -1)) == len(fills)
        and int(summary.get("closed_trades", -1)) == len(closes)
        and int((summary.get("execution") or {}).get("gap_exits", -1)) == len(gap_closes),
        f"summary fills={summary.get('fills')} rows={len(fills)}; "
        f"closes={summary.get('closed_trades')} rows={len(closes)}; "
        f"gap_exits={(summary.get('execution') or {}).get('gap_exits')} rows={len(gap_closes)}",
    )

    terminal: set[int] = set()
    for row in [*fills, *outcomes, *rejects]:
        owner: int | None = row.get("decision_seq")
        if owner is not None:
            terminal.add(int(owner))
    unresolved = [
        d.get("ledger_seq")
        for d in decisions
        if d.get("intent") in ACTIONABLE and int(d.get("ledger_seq") or -1) not in terminal
    ]
    verdict.add(
        "every_actionable_decision_is_resolved",
        not unresolved,
        f"{len(unresolved)} actionable decisions have no terminal row: {unresolved[:5]}",
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
        "one_ledger_holds_exactly_one_run",
        bool(kinds)
        and kinds[0] == "RUN"
        and kinds[-1] == "RUN_END"
        and kinds.count("RUN") == 1
        and kinds.count("RUN_END") == 1,
        f"first={kinds[0] if kinds else None} last={kinds[-1] if kinds else None} "
        f"runs={kinds.count('RUN')} run_ends={kinds.count('RUN_END')}",
    )

    # 15. the published coverage file matches the ledger it describes
    if coverage is not None:
        scoped = [row for row in coverage if scenario is None or row.get("scenario") == scenario]
        missing_by_symbol: dict[str, set[int]] = {}
        for row in scoped:
            missing = {int(value) for value in row.get("missing_bar_opens_ms") or []}
            symbol = str(row.get("symbol"))
            missing_by_symbol.setdefault(symbol, set()).update(missing)
        unmatched = [
            (row.get("symbol"), row.get("missing_bar_open_ms"))
            for row in gap_rejects
            if int(row.get("missing_bar_open_ms") or 0)
            not in missing_by_symbol.get(str(row.get("symbol")), set())
        ]
        declared_missing = {
            (str(row.get("symbol")), int(bar))
            for row in scoped
            for bar in [row.get("removed_bar_open_ms")]
            if bar
        }
        observed = {
            (str(row.get("symbol")), int(row.get("missing_bar_open_ms") or 0))
            for row in gap_rejects
        }
        verdict.add(
            "published_coverage_matches_the_rows",
            not unmatched and not (declared_missing - observed),
            f"unmatched={unmatched[:3]} declared_but_unreacted={sorted(declared_missing - observed)[:3]}",
        )

    return verdict


def relative(path: Path, root: Path) -> str:
    try:
        return Path(os.path.relpath(path, root)).as_posix()
    except ValueError:  # different drive on Windows
        return path.name


def absolute_paths(value: Any) -> list[str]:
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
    coverage: list[dict[str, Any]] | None = None,
    scenario: str | None = None,
) -> Verdict:
    rows = load_rows(ledger_path)
    verdict = verify_rows(rows, summary, coverage=coverage, scenario=scenario)
    leaked = [path for path in absolute_paths(summary) if not path.startswith("http")]
    verdict.add(
        "summary_is_portable_between_roots",
        not leaked,
        f"absolute paths in the summary: {leaked[:5]}",
    )
    return verdict


def mutations(
    rows: list[dict[str, Any]], summary: dict[str, Any]
) -> list[dict[str, Any]]:
    """Reintroduce each defect and require this verifier to notice.

    Every edit is applied to a deep copy and the chain is resealed, so the hash check
    cannot be what catches it: what must fail is the rule the defect broke. Mutations
    that cannot be applied to a ledger without the row they need are reported as
    SKIPPED, never as caught.
    """

    def resealed(edit: Any) -> list[dict[str, Any]]:
        clone = json.loads(json.dumps(rows))
        edit(clone)
        return reseal(clone)

    def first(copy_rows: list[dict[str, Any]], kind: str, **match: Any) -> dict[str, Any] | None:
        for row in copy_rows:
            entry: dict[str, Any] = row["entry"]
            if entry.get("kind") == kind and all(
                entry.get(key) == value for key, value in match.items()
            ):
                return entry
        return None

    def open_gap_copy(copy_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        found: dict[str, Any] | None = first(copy_rows, "CLOSE", exit_ts_resolution="OPEN_GAP")
        return found

    applied: list[dict[str, Any]] = []

    def case(code: str, expected: str, edit: Any, *, needs: str | None = None) -> None:
        if needs == "open_gap" and first(rows, "CLOSE", exit_ts_resolution="OPEN_GAP") is None:
            applied.append(
                {
                    "mutation": code,
                    "expected_check": expected,
                    "status": "SKIPPED",
                    "reason": "this ledger has no OPEN_GAP row",
                    "caught": False,
                }
            )
            return
        edited = resealed(edit)
        verdict = verify_rows(edited, summary)
        failing = [check.name for check in verdict.checks if not check.ok]
        applied.append(
            {
                "mutation": code,
                "expected_check": expected,
                "status": "APPLIED",
                "failing_checks": failing,
                "caught": expected in failing,
            }
        )

    def delay_gap_past_the_entry(copy_rows: list[dict[str, Any]]) -> None:
        """The P0 itself: the loss is recorded after the entry it should block."""
        index = next(
            position
            for position, row in enumerate(copy_rows)
            if row["entry"].get("kind") == "CLOSE"
            and row["entry"].get("exit_ts_resolution") == "OPEN_GAP"
        )
        close = copy_rows.pop(index)
        stamp = int(close["entry"].get("ts_ms") or 0)
        after = next(
            position
            for position, row in enumerate(copy_rows)
            if row["entry"].get("kind") in {"FILL", "DECISION_OUTCOME"}
            and int(row["entry"].get("ts_ms") or 0) >= stamp
        )
        #: Inserted *after* the row it should have preceded: the loss is now recorded
        #: once the entry it was supposed to veto has already been approved.
        copy_rows.insert(after + 1, close)

    def widen_the_gap_window(copy_rows: list[dict[str, Any]]) -> None:
        close = open_gap_copy(copy_rows)
        if close is not None:
            close["exit_ts_lower_bound_ms"] = int(close["ts_ms"]) - int(
                (summary.get("execution") or {}).get("bar_interval_ms") or 3_600_000
            )

    def credit_the_stop_level(copy_rows: list[dict[str, Any]]) -> None:
        close = open_gap_copy(copy_rows)
        if close is not None:
            close["exit_reference_price"] = float(close["stop_loss_price"])

    def credit_a_short_better_than_allowed(copy_rows: list[dict[str, Any]]) -> None:
        close = first(copy_rows, "CLOSE", exit_reason="stop_loss", side="sell") or open_gap_copy(
            copy_rows
        )
        if close is not None:
            close["exit_reference_price"] = float(close["stop_loss_price"]) * 0.99
            close["side"] = "sell"

    def fill_before_the_answer(copy_rows: list[dict[str, Any]]) -> None:
        fill = first(copy_rows, "FILL")
        if fill is not None:
            fill["quote_ts_ms"] = int(fill["received_at_ms"]) - 1

    def cover_the_hole_with_its_own_bars(copy_rows: list[dict[str, Any]]) -> None:
        fill = first(copy_rows, "FILL")
        if fill is not None:
            fill["data_gap_covered_by"] = "bar_open"
            fill["data_gap_missing_bar_open_ms"] = int(fill["ts_ms"]) - 3_600_000

    def break_the_risk_hand_off(copy_rows: list[dict[str, Any]]) -> None:
        close = first(copy_rows, "CLOSE")
        if close is not None:
            close["risk_equity_after"] = float(close["risk_equity_after"]) + 1.0

    def break_the_calendar_window(copy_rows: list[dict[str, Any]]) -> None:
        close = first(copy_rows, "CLOSE")
        if close is not None:
            close["risk_daily_pnl_after"] = float(close["risk_daily_pnl_after"]) - 0.01

    def invent_a_resolution(copy_rows: list[dict[str, Any]]) -> None:
        close = first(copy_rows, "CLOSE")
        if close is not None:
            close["exit_ts_resolution"] = "tick_exact"

    def break_the_net_identity(copy_rows: list[dict[str, Any]]) -> None:
        close = first(copy_rows, "CLOSE")
        if close is not None:
            close["pnl_net_usdt"] = float(close["pnl_net_usdt"]) + 1.0

    def drop_a_terminal_row(copy_rows: list[dict[str, Any]]) -> None:
        fill = first(copy_rows, "FILL")
        if fill is None:
            return
        target = fill["decision_seq"]
        copy_rows[:] = [
            row
            for row in copy_rows
            if not (
                row["entry"].get("kind") in {"FILL", "DECISION_OUTCOME"}
                and row["entry"].get("decision_seq") == target
            )
        ]

    def duplicate_a_position(copy_rows: list[dict[str, Any]]) -> None:
        fill = next(row for row in copy_rows if row["entry"].get("kind") == "FILL")
        copy_rows.append(copy.deepcopy(fill))

    def summary_case(code: str, expected: str, edit: Any) -> None:
        """A mutation of the published summary rather than of the ledger."""
        edited = json.loads(json.dumps(summary))
        edit(edited)
        verdict = verify_rows(rows, edited)
        failing = [check.name for check in verdict.checks if not check.ok]
        applied.append(
            {
                "mutation": code,
                "expected_check": expected,
                "status": "APPLIED",
                "failing_checks": failing,
                "caught": expected in failing,
            }
        )

    def misreport_the_counters(edit_summary: dict[str, Any]) -> None:
        edit_summary["fills"] = int(edit_summary.get("fills") or 0) + 1

    case("M-01", "open_gap_settled_before_new_risk", delay_gap_past_the_entry, needs="open_gap")
    case(
        "M-02",
        "open_gap_is_an_exact_instant_at_the_observable_open",
        widen_the_gap_window,
        needs="open_gap",
    )
    #: Crediting a gapped stop at its level instead of at the open is caught by the rule
    #: that pins the paid price to the observable open: directionally, "at the level" is
    #: not "better than the level", so the directional rule alone cannot see it.
    case(
        "M-03",
        "open_gap_is_an_exact_instant_at_the_observable_open",
        credit_the_stop_level,
        needs="open_gap",
    )
    case(
        "M-04",
        "stop_never_credited_better_than_its_level",
        credit_a_short_better_than_allowed,
    )
    case("M-05", "fill_quote_at_or_after_answer", fill_before_the_answer)
    case("M-06", "fill_price_has_a_declared_source", cover_the_hole_with_its_own_bars)
    case("M-07", "risk_engine_receives_each_close", break_the_risk_hand_off)
    case("M-08", "calendar_windows_rebuilt_from_the_rows", break_the_calendar_window)
    case("M-09", "exit_instant_resolution_is_declared", invent_a_resolution)
    case("M-10", "net_pnl_nets_every_named_cost", break_the_net_identity)
    case("M-11", "every_actionable_decision_is_resolved", drop_a_terminal_row)
    case("M-12", "position_ids_are_unique_and_owned", duplicate_a_position)
    summary_case("M-13", "counters_match_rows", misreport_the_counters)

    return applied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an AI-BOTS-003C paper run")
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--coverage", default=None, help="DATA_COVERAGE_LEDGER.jsonl")
    parser.add_argument("--scenario", default=None, help="scenario name inside the coverage file")
    parser.add_argument("--out", default=None)
    parser.add_argument("--mutations", action="store_true")
    parser.add_argument("--root", default=None, help="root used to make paths relative")
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
    coverage = None
    if args.coverage and Path(args.coverage).exists():
        coverage = load_rows(args.coverage)

    if args.mutations:
        cases = mutations(load_rows(ledger), summary)
        applied = [case for case in cases if case["status"] == "APPLIED"]
        report = {
            "tool": "ai_bots_003c_verify",
            "mode": "mutations",
            "ledger": ledger.name,
            "mutations": cases,
            "applied": len(applied),
            "skipped": len(cases) - len(applied),
            "caught": sum(1 for case in applied if case["caught"]),
            "verdict": "PASS"
            if applied and all(case["caught"] for case in applied)
            else "FAIL",
        }
        if args.out:
            Path(args.out).write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report["verdict"] == "PASS" else 1

    verdict = verify_run(
        ledger,
        summary,
        coverage=coverage,
        scenario=args.scenario,
    )
    report = {
        "tool": "ai_bots_003c_verify",
        "verifier": "independent (no trading_bot import)",
        "ledger": relative(ledger, Path(args.root or Path.cwd())),
        "summary": relative(summary_path, Path(args.root or Path.cwd())),
        "scenario": args.scenario,
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
