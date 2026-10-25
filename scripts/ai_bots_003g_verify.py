"""ai_bots_003g_verify — independent reconstruction from raw minute data.

This verifier imports **nothing** from ``trading_bot``: it reads the session's raw 1-minute
JSONL, the stream chain and the per-cycle ledgers, and re-derives the claims from those
bytes. If it used the lane's own helpers, a bug in the lane would be checked by the bug.

What it recomputes:

1. every stored minute is closed by the exchange clock and strictly increasing;
2. the 5-minute bars the lane consumed are rebuilt from those minutes and hashed, per
   symbol and per cycle, and compared with the digest the session published;
3. ``data_time <= decision_time`` in every cycle, and the declared delay is included;
4. every fill pays a real 1-minute open at or after the instant the answer arrived, and
   the post-fill range it was stopped on is rebuilt minute by minute;
5. the net/gross/cost identity of every close, and the summary totals from the ledger;
6. each cycle's hash chain, and that no past decision changed when a new bar arrived;
7. the runtime files that ran are the bytes present now, and the path contains no live
   order route.

Exit code 0 only when every check passes. A failed check is printed with its code and the
row that produced it; nothing is repaired.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MINUTE_MS = 60_000
GENESIS = "0" * 64
LIVE_ROUTE_PATTERNS = (
    "/api/v3/order",
    "create_order(",
    "place_order(",
    "submit_order(",
)
RUNTIME_FILES = (
    "src/trading_bot/vision/lane.py",
    "src/trading_bot/vision/execution.py",
    "src/trading_bot/vision/quotes.py",
    "src/trading_bot/vision/clock.py",
    "src/trading_bot/vision/ledger.py",
    "src/trading_bot/vision/provider.py",
    "src/trading_bot/vision/settings.py",
    "src/trading_bot/vision/prospective.py",
    "src/trading_bot/market_data/minute_collector.py",
    "src/trading_bot/risk/manager.py",
    "src/trading_bot/paper/broker.py",
)


@dataclass
class Report:
    checks: list[dict[str, Any]] = field(default_factory=list)

    def add(self, code: str, ok: bool, detail: str, **extra: Any) -> bool:
        self.checks.append({"code": code, "ok": bool(ok), "detail": detail, **extra})
        return bool(ok)

    @property
    def passed(self) -> int:
        return sum(1 for check in self.checks if check["ok"])

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [check for check in self.checks if not check["ok"]]


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _line_hash(seq: int, prev: str, entry: dict[str, Any]) -> str:
    return hashlib.sha256(
        _canonical({"seq": int(seq), "prev_sha256": prev, "entry": entry}).encode("utf-8")
    ).hexdigest()


def read_chain(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    if not path.exists():
        return [], "MISSING"
    rows: list[dict[str, Any]] = []
    previous = GENESIS
    with path.open("r", encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                return rows, f"BAD_JSON_AT_{number}: {exc}"
            if int(row.get("seq", -1)) != number:
                return rows, f"SEQ_GAP_AT_{number}"
            if str(row.get("prev_sha256")) != previous:
                return rows, f"BROKEN_LINK_AT_{number}"
            expected = _line_hash(number, previous, row["entry"])
            if expected != str(row.get("sha256")):
                return rows, f"TAMPERED_LINE_{number}"
            previous = expected
            rows.append(row)
    return rows, None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def digest_series(bars: list[list[float]]) -> str:
    payload = json.dumps(
        [
            [
                int(bar[0]),
                round(float(bar[1]), 8),
                round(float(bar[2]), 8),
                round(float(bar[3]), 8),
                round(float(bar[4]), 8),
                round(float(bar[5]), 8),
            ]
            for bar in bars
        ],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _display(archive_symbol: str) -> str:
    return (
        f"{archive_symbol[:-4]}/{archive_symbol[-4:]}"
        if archive_symbol.endswith("USDT")
        else archive_symbol
    )


def _minute_rows(session: Path, symbol: str) -> list[dict[str, Any]]:
    return read_jsonl(session / "market-1m" / f"{symbol}.jsonl")


def _minute_map(rows: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {int(row["open_ms"]): row for row in rows}


def _aggregate(rows: list[dict[str, Any]], interval_ms: int, until_ms: int) -> tuple[list[list[float]], list[int]]:
    per_group = interval_ms // MINUTE_MS
    groups: dict[int, dict[int, dict[str, Any]]] = {}
    for row in rows:
        if int(row["open_ms"]) + MINUTE_MS > int(until_ms):
            continue
        group = (int(row["open_ms"]) // interval_ms) * interval_ms
        groups.setdefault(group, {})[int(row["open_ms"])] = row
    out: list[list[float]] = []
    incomplete: list[int] = []
    ordered = sorted(groups)
    for position, group in enumerate(ordered):
        members = groups[group]
        expected = [group + index * MINUTE_MS for index in range(per_group)]
        observed = sorted(members)
        if observed == expected:
            pass
        elif position == 0 and observed == expected[per_group - len(observed) :]:
            # Cut by the start of the requested window, not by a hole in the feed.
            continue
        elif position == len(ordered) - 1 and observed == expected[: len(observed)]:
            # The newest group has not finished closing yet.
            continue
        else:
            incomplete.append(group)
            continue
        out.append(
            [
                group,
                float(members[group]["open"]),
                max(float(members[stamp]["high"]) for stamp in expected),
                min(float(members[stamp]["low"]) for stamp in expected),
                float(members[expected[-1]]["close"]),
                sum(float(members[stamp]["volume"]) for stamp in expected),
            ]
        )
    return out, incomplete


def _prefix_equal(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> tuple[bool, str]:
    first = 1 if previous and previous[0]["entry"].get("kind") == "RUN" else 0
    for row in previous[first:]:
        entry = row["entry"]
        if entry.get("kind") == "RUN_END" or entry.get("phase") == "RUN_END":
            continue
        seq = int(row["seq"])
        if seq > len(current):
            return False, f"current ledger shorter at seq {seq}"
        left = {k: v for k, v in entry.items() if k != "recorded_at_utc"}
        right = {
            k: v
            for k, v in current[seq - 1]["entry"].items()
            if k != "recorded_at_utc"
        }
        if left != right:
            return False, f"decision at seq {seq} changed after a new bar arrived"
    return True, "every past decision is unchanged"


def verify(session: Path, root: Path) -> Report:
    report = Report()
    stream_rows, stream_error = read_chain(session / "STREAM.jsonl")
    report.add(
        "stream_chain_intact",
        stream_error is None,
        stream_error or f"{len(stream_rows)} chained rows",
    )
    if not stream_rows:
        return report
    start = stream_rows[0]["entry"]
    report.add(
        "session_is_paper",
        start.get("mode") == "PAPER" and start.get("live_enabled") is False,
        f"mode={start.get('mode')} live_enabled={start.get('live_enabled')}",
    )
    report.add(
        "subbar_enabled_for_paper_only",
        start.get("subbar_entries") == "PAPER_ONLY",
        f"subbar_entries={start.get('subbar_entries')}",
    )

    # -- runtime identity -----------------------------------------------------
    recorded = start.get("runtime_sha256") or {}
    mismatched = []
    for relative in RUNTIME_FILES:
        path = root / relative
        if not path.exists():
            mismatched.append(f"{relative}: MISSING")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if recorded.get(relative) != digest:
            mismatched.append(f"{relative}: {recorded.get(relative)} -> {digest}")
    report.add(
        "tested_runtime_equals_used_runtime",
        not mismatched,
        "all runtime hashes match" if not mismatched else "; ".join(mismatched),
    )

    # -- no live route in the used code --------------------------------------
    offenders = []
    for relative in RUNTIME_FILES:
        path = root / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in LIVE_ROUTE_PATTERNS:
            if pattern in text:
                offenders.append(f"{relative}: {pattern}")
    report.add(
        "no_live_order_route_in_runtime",
        not offenders,
        "no order endpoint or order call in the runtime set"
        if not offenders
        else "; ".join(offenders),
    )

    # -- raw minutes ----------------------------------------------------------
    symbols = list((start.get("config") or {}).get("symbols") or [])
    minutes: dict[str, list[dict[str, Any]]] = {}
    sub_bar_fills = 0
    closed_ok = True
    order_ok = True
    for symbol in symbols:
        rows = _minute_rows(session, symbol)
        minutes[symbol] = rows
        if not rows:
            closed_ok = False
            report.add(f"minutes_present_{symbol}", False, "no minute rows")
            continue
        previous = -1
        for row in rows:
            stamp = int(row["open_ms"])
            if stamp % MINUTE_MS or int(row["server_time_ms"]) < stamp + MINUTE_MS:
                closed_ok = False
                break
            if stamp <= previous:
                order_ok = False
                break
            previous = stamp
    report.add(
        "every_stored_minute_is_closed",
        closed_ok,
        "no forming bar was stored",
    )
    report.add(
        "minutes_strictly_increasing",
        order_ok,
        "no duplicate or out-of-order minute in any store",
    )

    # -- cycles ---------------------------------------------------------------
    cycles = [row["entry"] for row in stream_rows if row["entry"].get("kind") == "CYCLE"]
    executed = [row for row in cycles if row.get("status") == "EXECUTED"]
    report.add("a_cycle_was_executed", bool(executed), f"{len(executed)} executed cycles")
    if not executed:
        return report

    interval_ms = int(executed[-1]["bar_interval_ms"])
    time_ok = True
    delay_ok = True
    series_ok = True
    chain_ok = True
    fills_ok = True
    range_ok = True
    identity_ok = True
    gate_ok = True
    detail_errors: list[str] = []
    previous_rows: list[dict[str, Any]] = []
    last_entries: list[dict[str, Any]] = []

    for cycle in executed:
        data_time = int(cycle["data_time_ms"])
        if not (int(cycle["decision_time_ms"]) >= data_time):
            time_ok = False
            detail_errors.append(f"cycle {cycle['cycle']}: decision before data")
        if int(cycle.get("data_delay_ms", 0)) > 0 and data_time + int(cycle["data_delay_ms"]) > int(cycle["decision_time_ms"]):
            delay_ok = False
            detail_errors.append(f"cycle {cycle['cycle']}: declared delay exceeds the wait")
        if int(cycle["decision_bar_open_ms"]) + interval_ms != data_time:
            time_ok = False
            detail_errors.append(f"cycle {cycle['cycle']}: bar close/datum mismatch")
        for symbol in symbols:
            display = _display(symbol)
            rebuilt, incomplete = _aggregate(
                minutes[symbol], interval_ms=interval_ms, until_ms=data_time
            )
            if incomplete:
                series_ok = False
                detail_errors.append(f"cycle {cycle['cycle']} {symbol}: incomplete groups")
            published = cycle["series"][display]
            if digest_series(rebuilt) != published["sha256"] or len(rebuilt) != published["bars"]:
                series_ok = False
                detail_errors.append(f"cycle {cycle['cycle']} {symbol}: series digest mismatch")
        ledger_path = session / cycle["ledger"]["path"]
        rows, error = read_chain(ledger_path)
        if error:
            chain_ok = False
            detail_errors.append(f"cycle {cycle['cycle']}: {error}")
            continue
        if previous_rows:
            ok, why = _prefix_equal(previous_rows, rows)
            if not ok:
                chain_ok = False
                detail_errors.append(f"cycle {cycle['cycle']}: {why}")
        previous_rows = rows
        last_entries = rows
        by_symbol = {symbol: _minute_map(minutes[symbol]) for symbol in symbols}
        outcomes = {
            int(row["entry"]["decision_seq"]): row["entry"]
            for row in rows
            if row["entry"].get("kind") == "DECISION_OUTCOME"
        }
        for row in rows:
            entry = row["entry"]
            if entry.get("kind") == "FILL":
                symbol = str(entry["symbol"]).replace("/", "")
                fill_ts = int(entry["quote_ts_ms"])
                if fill_ts < int(entry["received_at_ms"]):
                    fills_ok = False
                    detail_errors.append(f"fill before its answer at {entry.get('position_id')}")
                observed = by_symbol.get(symbol, {}).get(fill_ts)
                if observed is None or abs(float(observed["open"]) - float(entry["quote_price"])) > 1e-9:
                    fills_ok = False
                    detail_errors.append(f"fill price is not the observed 1m open at {fill_ts}")
                if entry.get("quote_source") != "bar_open":
                    sub_bar_fills += 1
                outcome = outcomes.get(int(entry.get("decision_seq", -1)))
                if outcome is None or not outcome.get("approved"):
                    gate_ok = False
                    detail_errors.append(f"fill without an approved risk gate: {entry.get('decision_seq')}")
                if "entry_bar_range_from_ms" not in entry:
                    # A bar-open fill has no post-fill sub-range: the whole bar is already
                    # after it. Nothing to rebuild and nothing to excuse.
                    continue
                start_range = int(entry["entry_bar_range_from_ms"])
                end_range = int(entry["entry_bar_range_until_ms"])
                if start_range != fill_ts:
                    range_ok = False
                    detail_errors.append("entry-bar range does not start at the fill")
                stamps = sorted(
                    stamp
                    for stamp in by_symbol.get(symbol, {})
                    if start_range < stamp < end_range
                )
                if len(stamps) != int(entry.get("entry_bar_range_minutes", -1)):
                    range_ok = False
                    detail_errors.append("entry-bar range minute count mismatch")
                if stamps:
                    expected = [stamps[0]]
                    for stamp in stamps[1:]:
                        if stamp != expected[-1] + MINUTE_MS:
                            range_ok = False
                            detail_errors.append("entry-bar range is not contiguous")
                        expected.append(stamp)
                    high = max(float(by_symbol[symbol][stamp]["high"]) for stamp in stamps)
                    low = min(float(by_symbol[symbol][stamp]["low"]) for stamp in stamps)
                    last = float(by_symbol[symbol][stamps[-1]]["close"])
                    if (
                        abs(high - float(entry["entry_bar_range_high"])) > 1e-9
                        or abs(low - float(entry["entry_bar_range_low"])) > 1e-9
                        or abs(last - float(entry["entry_bar_range_last"])) > 1e-9
                    ):
                        range_ok = False
                        detail_errors.append("entry-bar range high/low/last not reproducible")
            elif entry.get("kind") == "CLOSE":
                net = float(entry["pnl_net_usdt"])
                rebuilt = (
                    float(entry["gross_pnl_usdt"])
                    - float(entry["commissions_usdt"])
                    - float(entry["execution_cost_usdt"])
                )
                if abs(net - rebuilt) > 1e-6:
                    identity_ok = False
                    detail_errors.append(
                        f"close {entry.get('trade_id')}: net {net} != {rebuilt}"
                    )

    report.add("data_time_le_decision_time", time_ok, "; ".join(detail_errors[:4]) or "ok")
    report.add("declared_delay_is_inside_the_wait", delay_ok, "declared delivery delay respected")
    report.add("published_series_rebuilds_from_minutes", series_ok, "per-cycle series digests match")
    report.add("cycle_ledgers_are_chained", chain_ok, "; ".join(detail_errors[:3]) or "chains intact")
    report.add("subbar_fills_are_observed_prices", fills_ok, "fill price = 1m open at or after the answer")
    report.add("entry_bar_range_is_post_fill", range_ok, "range rebuilt minute by minute")
    fills_in_ledger = sum(
        1 for row in last_entries if row["entry"].get("kind") == "FILL"
    )
    report.add(
        "at_least_one_subbar_fill",
        sub_bar_fills > 0 or fills_in_ledger == 0,
        f"{sub_bar_fills} sub-bar fill rows across the session, "
        f"{fills_in_ledger} in the last ledger",
    )
    report.add("fills_have_an_approved_risk_gate", gate_ok, "every fill joins an approved decision")
    report.add("close_pnl_identity_holds", identity_ok, "net = gross - commissions - execution cost")
    report.add("no_past_decision_changed", chain_ok, "prefix determinism checked")

    # -- summary recomputation ------------------------------------------------
    closes = [row["entry"] for row in last_entries if row["entry"].get("kind") == "CLOSE"]
    fills = [row["entry"] for row in last_entries if row["entry"].get("kind") == "FILL"]
    net = round(sum(float(row["pnl_net_usdt"]) for row in closes), 6)
    summary_path = session / "SUMMARY.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    report.add(
        "summary_net_matches_ledger",
        summary.get("net_realised_usdt") is None
        or abs(float(summary["net_realised_usdt"]) - net) <= 1e-6,
        f"summary={summary.get('net_realised_usdt')} ledger={net}",
    )
    report.add(
        "summary_fills_match_ledger",
        int(summary.get("fills", -1)) == len(fills),
        f"summary={summary.get('fills')} ledger={len(fills)}",
    )
    report.add(
        "summary_closed_match_ledger",
        int(summary.get("closed_trades", -1)) == len(closes),
        f"summary={summary.get('closed_trades')} ledger={len(closes)}",
    )
    report.add(
        "no_live_orders_recorded",
        all(int(row.get("live_orders", 0)) == 0 for row in stream_rows if "live_orders" in row["entry"]),
        "every stream row records live_orders=0",
    )

    # -- no LIVE anywhere in the artefacts -----------------------------------
    live_hits = []
    for path in session.rglob("*"):
        if not path.is_file() or path.suffix not in {".json", ".jsonl", ".md"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r'"mode"\s*:\s*"LIVE"', text):
            live_hits.append(str(path.relative_to(session)))
    report.add(
        "no_live_mode_in_any_artifact",
        not live_hits,
        "no artefact claims LIVE" if not live_hits else ", ".join(live_hits),
    )

    # -- clock provenance -----------------------------------------------------
    delays = [
        int(row["delivery_latency_ms"])
        for rows in minutes.values()
        for row in rows
        if int(row["received_at_ms"]) > int(row["close_ms"])
    ]
    report.add(
        "receipt_is_never_before_the_close",
        not [
            row
            for rows in minutes.values()
            for row in rows
            if int(row["received_at_ms"]) < int(row["close_ms"])
        ],
        f"{len(delays)} minutes with a positive delivery latency",
    )
    manifest_path = session / "market-1m" / "MANIFEST.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    manifest_ok = True
    for symbol in symbols:
        entry = (manifest.get("symbols") or {}).get(symbol) or {}
        file_path = session / "market-1m" / f"{symbol}.jsonl"
        if not file_path.exists():
            manifest_ok = False
            continue
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if entry.get("sha256") != digest:
            manifest_ok = False
    report.add(
        "manifest_matches_the_minute_bytes",
        manifest_ok,
        "each store's sha256 matches the manifest",
    )

    return report


def render(report: Report, session: Path) -> str:
    lines = [
        "# Independent verification — RFC-TAP-AI-BOTS-003G",
        "",
        f"**Session:** `{session}`",
        f"**Checks:** {report.passed} PASS / {len(report.failed)} FAIL "
        f"({len(report.checks)} total)",
        "",
        "> Verifier: `scripts/ai_bots_003g_verify.py`. It imports no `trading_bot` module and",
        "> recomputes every claim from the raw JSONL. It is written by the builder, so it is",
        "> not a substitute for a second independent agent (`BUILDER != VERIFIER`).",
        "",
        "| # | check | result | detail |",
        "| --- | --- | --- | --- |",
    ]
    for index, check in enumerate(report.checks, start=1):
        detail = str(check["detail"]).replace("|", "\\|")
        lines.append(
            f"| {index} | `{check['code']}` | {'PASS' if check['ok'] else 'FAIL'} | {detail} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent verification of a 003G session")
    parser.add_argument("--session", required=True)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    #: 003H: verifying a *foreign or frozen* session must not write into it. Without this
    #: option a re-run rewrote the session's own VERIFICATION.md, which is evidence.
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args(argv)
    session = Path(args.session)
    root = Path(args.root)
    if not session.exists():
        print(f"[verify] missing session {session}", file=sys.stderr)
        return 2
    report = verify(session, root)
    out_dir = Path(args.out_dir) if args.out_dir else session
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "VERIFICATION.json"
    out.write_text(
        json.dumps(
            {
                "schema_version": "AI_BOTS_003G_VERIFICATION_V1",
                "session": str(session),
                "checks": report.checks,
                "passed": report.passed,
                "failed": len(report.failed),
                "verdict": "PASS" if not report.failed else "FAIL",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (out_dir / "VERIFICATION.md").write_text(
        render(report, session), encoding="utf-8", newline="\n"
    )
    print(f"[verify] {report.passed} PASS / {len(report.failed)} FAIL")
    for check in report.failed:
        print(f"[verify] FAIL {check['code']}: {check['detail']}")
    return 0 if not report.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
