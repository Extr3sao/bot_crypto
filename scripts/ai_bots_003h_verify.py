"""ai_bots_003h_verify — 003G's byte checks plus the accounting contract of 003H.

This verifier is the 003G one (copied, not modified: that script's output is frozen evidence)
extended with the checks D5 made necessary. It imports **nothing** from ``trading_bot``; the
only import is the 003G verifier itself, which is a sibling script, so a bug in the lane cannot
be checked by the lane.

Added checks:

* every cost and PnL term the run publishes is defined and versioned;
* ``costs_usdt`` still means *realised closed-trade cost*, and equals the legs the CLOSE rows
  carry;
* the entry commissions of positions still open are accrued, published and added to the
  total exactly once — rebuilt from the FILL rows, never read from the summary;
* the marked equity rebuilds from the raw 1-minute close, the entry price and the fee;
* the four instants of a fill (close, receipt, answer, quote) are ordered and their two waits
  (delivery and quote lag) are names for different things;
* a minute stored after the session started was seen at least ``settle_ms`` after its close,
  which is the gate 003G-D2 added.

Exit code 0 only when every check of both generations passes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ai_bots_003g_verify as base

MINUTE_MS = 60_000
TOLERANCE = 1e-6


def _summary(session: Path) -> dict[str, Any]:
    path = session / "SUMMARY.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _final_ledger(session: Path) -> list[dict[str, Any]]:
    """The cumulative ledger of the last cycle, which contains every row before it."""

    cycles = sorted((session / "cycles").glob("cycle-*/ledger.jsonl"))
    if not cycles:
        return []
    return [json.loads(line)["entry"] for line in cycles[-1].read_text(encoding="utf-8").splitlines() if line.strip()]


def _of_kind(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("kind") == kind]


def _close(a: float, b: float, tolerance: float = TOLERANCE) -> bool:
    return abs(float(a) - float(b)) <= tolerance


def _start_ms(start: dict[str, Any]) -> int:
    """The session's start instant, in ms since the epoch, from its ISO stamp."""

    from datetime import UTC, datetime

    stamp = str(start.get("started_at_utc") or "")
    if not stamp:
        return 0
    return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC).timestamp() * 1000)


def _mark_prices(session: Path) -> dict[str, float]:
    """Last stored 1-minute close per symbol, straight from the raw bytes."""

    marks: dict[str, float] = {}
    for path in sorted((session / "market-1m").glob("*.jsonl")):
        if path.name == "EVENTS.jsonl":
            continue  # the hash-chained event log shares the folder, not the schema
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        minutes = [row for row in rows if "close" in row and "open_ms" in row]
        if minutes:
            #: The store names a symbol the way the venue does (``BTCUSDT``); the ledger
            #: names it the way the book does (``BTC/USDT``). Same market, two spellings.
            marks[base._display(str(minutes[-1]["symbol"]))] = float(minutes[-1]["close"])
    return marks


def _accrued_from_ledger(
    fills: list[dict[str, Any]], open_ids: set[str]
) -> tuple[float, list[str]]:
    """Entry commissions already owed by positions that never closed, from FILL rows."""

    notes: list[str] = []
    total = 0.0
    for fill in fills:
        position_id = str(fill.get("position_id") or "")
        if position_id and position_id in open_ids:
            commission = fill.get("entry_commission_usdt")
            if commission is None:
                notes.append(f"{position_id}: FILL row carries no entry_commission_usdt")
                continue
            total += float(commission)
    return round(total, 8), notes


def _lane_summary(rows: list[dict[str, Any]], session: Path) -> dict[str, Any]:
    """The lane's own summary, read from the RUN_END row of the cumulative ledger.

    The session's ``SUMMARY.json`` is a projection of the last cycle; the cheapest raw
    evidence is the row the lane wrote when it stopped. Reading the projection would let a
    truncated projection look like a correct one.
    """

    runs = _of_kind(rows, "RUN_END")
    if runs:
        return dict(runs[-1])
    cycles = sorted((session / "cycles").glob("cycle-*/summary.json"))
    if cycles:
        return json.loads(cycles[-1].read_text(encoding="utf-8"))
    return {}


def verify_003h(session: Path, root: Path) -> base.Report:
    report = base.verify(session, root)
    session_summary = _summary(session)
    rows = _final_ledger(session)
    summary = _lane_summary(rows, session)
    fills = _of_kind(rows, "FILL")
    closes = _of_kind(rows, "CLOSE")
    open_positions = summary.get("open_positions_at_end") or {}
    open_ids = {str(item.get("position_id") or "") for item in open_positions.values()}

    # 1 — the contract is versioned and every term is defined.
    accounting = summary.get("accounting") or {}
    meanings = accounting.get("meanings") or {}
    required = (
        "costs_usdt",
        "costs_realised_usdt",
        "costs_total_usdt",
        "entry_commissions_accrued_open_usdt",
        "pnl_realised_usdt",
        "pnl_unrealised_usdt",
        "pnl_total_usdt",
        "marked_equity_usdt",
    )
    missing_terms = [key for key in required if key not in summary]
    missing_meanings = [key for key in required if not meanings.get(key)]
    ok = (
        accounting.get("schema_version") == "paper-accounting/2"
        and not missing_terms
        and not missing_meanings
    )
    report.add(
        "accounting_contract_is_versioned_and_defined",
        ok,
        f"schema={accounting.get('schema_version')} missing_terms={missing_terms} "
        f"missing_meanings={missing_meanings}",
    )

    # 2 — costs_usdt keeps its 003B meaning: realised legs only.
    realised_legs = round(
        sum(
            float(row.get("entry_commission_usdt") or 0.0)
            + float(row.get("exit_commission_usdt") or 0.0)
            + float(row.get("execution_cost_usdt") or 0.0)
            for row in closes
        ),
        8,
    )
    ok = _close(summary.get("costs_usdt", 0.0), realised_legs, 1e-6) and _close(
        summary.get("costs_realised_usdt", realised_legs), realised_legs, 1e-6
    )
    report.add(
        "costs_usdt_still_means_realised_cost",
        ok,
        f"summary={summary.get('costs_usdt')} rebuilt_from_CLOSE_rows={realised_legs}",
    )

    # 3 — open positions' entry commissions are accrued and counted once.
    accrued, notes = _accrued_from_ledger(fills, open_ids)
    published_accrued = float(summary.get("entry_commissions_accrued_open_usdt") or 0.0)
    total = float(summary.get("costs_total_usdt") or 0.0)
    ok = (
        _close(accrued, published_accrued)
        and _close(total, float(summary.get("costs_usdt") or 0.0) + published_accrued)
        and (bool(open_ids) == (published_accrued > 0))
        and not notes
    )
    report.add(
        "open_position_commissions_are_accrued_once",
        ok,
        f"open_positions={len(open_ids)} accrued_from_fills={accrued} "
        f"published={published_accrued} costs_total={total} notes={notes}",
    )

    # 4 — the marked equity rebuilds from the raw minute, the fill price and the fee.
    marks = _mark_prices(session)
    entry_by_position = {str(row.get("position_id")): row for row in fills}
    unrealised_gross = 0.0
    mark_notes: list[str] = []
    for symbol, position in sorted(open_positions.items()):
        position_id = str(position.get("position_id") or "")
        fill = entry_by_position.get(position_id)
        mark = marks.get(str(symbol))
        if fill is None or mark is None:
            mark_notes.append(f"{symbol}: no FILL row or no mark price")
            continue
        quantity = float(fill["quantity"])
        entry_price = float(fill["entry_price"])
        side = str(fill["side"])
        unrealised_gross += (
            (mark - entry_price) * quantity if side == "buy" else (entry_price - mark) * quantity
        )
    rebuilt_unrealised_net = round(unrealised_gross - published_accrued, 8)
    rebuilt_marked_equity = round(
        float(accounting.get("initial_equity_usdt", 10_000.0) or 10_000.0)
        + float(summary.get("pnl_realised_usdt") or 0.0)
        + rebuilt_unrealised_net,
        8,
    )
    ok = (
        not mark_notes
        and _close(rebuilt_unrealised_net, float(summary.get("pnl_unrealised_usdt") or 0.0), 1e-6)
        and _close(rebuilt_marked_equity, float(summary.get("marked_equity_usdt") or 0.0), 1e-6)
    )
    report.add(
        "marked_equity_rebuilds_from_raw_minutes",
        ok,
        f"marks={ {k: round(v, 4) for k, v in marks.items()} } "
        f"unrealised_gross={round(unrealised_gross, 8)} "
        f"rebuilt_net={rebuilt_unrealised_net} published_net={summary.get('pnl_unrealised_usdt')} "
        f"rebuilt_marked={rebuilt_marked_equity} published={summary.get('marked_equity_usdt')} "
        f"notes={mark_notes}",
    )

    # 5 — no position is on both sides of the book.
    closed_ids = {str(row.get("position_id") or "") for row in closes}
    overlap = sorted(open_ids & closed_ids)
    ok = not overlap and len(fills) == len({str(row.get("position_id") or "") for row in fills})
    report.add(
        "no_position_is_counted_twice",
        ok,
        f"fills={len(fills)} distinct={len({str(r.get('position_id') or '') for r in fills})} "
        f"open_and_closed={overlap}",
    )

    # 6 — the four instants, and the two waits that are not the same wait.
    bad: list[str] = []
    for row in fills:
        received = int(row["received_at_ms"])
        quote_ts = int(row["quote_ts_ms"])
        decision_ts = int(row["decision_ts_ms"])
        if not (received <= quote_ts):
            bad.append(f"{row['position_id']}: quote {quote_ts} before receipt {received}")
        if int(row["quote_lag_ms"]) != quote_ts - received:
            bad.append(f"{row['position_id']}: quote_lag_ms is not quote_ts - received_at")
        if int(row["opinion_age_ms"]) != quote_ts - decision_ts:
            bad.append(f"{row['position_id']}: opinion_age_ms is not quote_ts - decision_ts")
    ok = not bad
    report.add(
        "fill_instants_are_ordered_and_named",
        ok,
        f"fills={len(fills)} problems={bad}",
    )

    # 7 — every minute that arrived live waited for the venue to settle it.
    start = json.loads((session / "SESSION_START.json").read_text(encoding="utf-8"))
    config = start.get("config") or {}
    settle_ms = int(config.get("settle_ms") or 0)
    session_start_ms = _start_ms(start)
    live_problems: list[str] = []
    checked = 0
    for path in sorted((session / "market-1m").glob("*.jsonl")):
        if path.name == "EVENTS.jsonl":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            minute = json.loads(line)
            if "close_ms" not in minute or int(minute["open_ms"]) < session_start_ms:
                continue
            checked += 1
            waited = int(minute["received_at_ms"]) - int(minute["close_ms"])
            if settle_ms and waited < settle_ms:
                live_problems.append(
                    f"{minute['symbol']} {minute['open_utc']}: waited {waited} ms < settle {settle_ms}"
                )
    report.add(
        "live_minutes_were_seen_after_they_settled",
        not live_problems,
        f"settle_ms={settle_ms} live_minutes_checked={checked} problems={live_problems[:5]}",
    )

    # 8 — the session projection does not soften the ledger it summarises.
    projected = session_summary.get("accounting") or {}
    keys = (
        "costs_usdt",
        "costs_realised_usdt",
        "costs_total_usdt",
        "entry_commissions_accrued_open_usdt",
        "pnl_realised_usdt",
        "pnl_unrealised_usdt",
        "pnl_total_usdt",
        "marked_equity_usdt",
    )
    disagreements = [
        key
        for key in keys
        if summary.get(key) is not None
        and projected.get(key) is not None
        and not _close(summary[key], projected[key], 1e-6)
    ]
    ok = (
        not disagreements
        and projected.get("schema_version") == accounting.get("schema_version")
        and bool(projected)
    )
    report.add(
        "session_summary_matches_the_lane_ledger",
        ok,
        f"schema={projected.get('schema_version')} disagreements={disagreements} "
        f"projected_keys={sorted(projected)}",
    )
    return report


def render_003h(report: base.Report, session: Path) -> str:
    """The 003G table, relabelled: these are the 003G checks *plus* the 003H ones."""

    text = base.render(report, session)
    return text.replace(
        "# Independent verification — RFC-TAP-AI-BOTS-003G",
        "# Independent verification — RFC-TAP-AI-BOTS-003H\n\n"
        "> Checks 1-25 are the 003G byte checks, imported from\n"
        "> `scripts/ai_bots_003g_verify.py` and unmodified; checks 26-33 are the 003H\n"
        "> accounting, timestamp, settle and projection checks.",
        1,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--json-out", default=None)
    #: Where the markdown goes. Default is the session itself; pass it when the session is
    #: frozen evidence that must not be written into.
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args(argv)

    session = Path(args.session)
    out_dir = Path(args.out_dir) if args.out_dir else session
    out_dir.mkdir(parents=True, exist_ok=True)
    report = verify_003h(session, Path(args.root))
    text = render_003h(report, session)
    print(text)
    (out_dir / "VERIFICATION_003H.md").write_text(text, encoding="utf-8", newline="\n")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(
                {
                    "schema_version": "AI_BOTS_003H_VERIFICATION_V1",
                    "session": str(session),
                    "passed": sum(1 for check in report.checks if check["ok"]),
                    "failed": sum(1 for check in report.checks if not check["ok"]),
                    "checks": report.checks,
                },
                indent=1,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return 0 if all(check["ok"] for check in report.checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
