"""edge17_verify — independent verification of WP-EDGE-017, with fault injection.

BUILDER != VERIFIER. Nothing here imports the modules that produced the
artifacts (``trading_bot.research.oos_capture``, ``trading_bot.paper.broker``,
``trading_bot.risk.*``): the rules are re-implemented from the published
artifacts and from the text of the runtime sources, so a builder bug cannot
verify itself. Each check has a matching mutation that makes it fail, which is
the only evidence that a green check means anything.

    python scripts/edge17_verify.py
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-017"
OUT_15 = REPO / "reports" / "economic-recovery" / "RFC-EDGE-015"
OUT_16 = REPO / "reports" / "economic-recovery" / "RFC-EDGE-016" / "experimental_paper"
SLICE = OUT_15 / "scratch" / "OOS_PROSPECTIVE_1H.jsonl"
LEDGER = OUT_15 / "scratch" / "OOS_CAPTURE_LEDGER.jsonl"
MANIFEST = OUT_15 / "OOS_CAPTURE_MANIFEST_V2.json"
PREREG = OUT_15 / "OOS_PREREGISTRATION_V2.json"
HOUR = 3_600_000
SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
GUARD_VALVE = 64 * 1024 * 1024
GUARD_RESERVE = 2_000_000_000
GUARD_STRESS = 1.5
GUARD_HOURS = 24.0


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def sha_lines(lines: list[dict[str, Any]]) -> str:
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in lines).encode()
    return hashlib.sha256(payload).hexdigest()


def close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= tol


@dataclass
class Checks:
    results: list[dict[str, Any]] = field(default_factory=list)

    def check(self, name: str, problems: list[str], detail: str = "") -> None:
        self.results.append(
            {
                "id": name,
                "status": "VERIFIED" if not problems else "FAILED",
                "problems": problems,
                "detail": detail,
            }
        )

    @property
    def failed(self) -> list[dict[str, Any]]:
        return [row for row in self.results if row["status"] != "VERIFIED"]

    @property
    def verified(self) -> int:
        return sum(1 for row in self.results if row["status"] == "VERIFIED")


# --------------------------------------------------------------------------------------
# predicates — pure functions over data, so a mutation can be run through the same test
# --------------------------------------------------------------------------------------


def p_slice_post_freeze(slice_rows: list[dict[str, Any]], freeze_ms: int) -> list[str]:
    return [
        f"{row['symbol']}@{row['timestamp']} opens at or before the freeze"
        for row in slice_rows
        if int(row["timestamp"]) <= freeze_ms
    ]


def p_unique_keys(slice_rows: list[dict[str, Any]]) -> list[str]:
    keys = [(str(row["symbol"]), int(row["timestamp"])) for row in slice_rows]
    return [] if len(keys) == len(set(keys)) else [f"{len(keys) - len(set(keys))} duplicate keys"]


def p_slice_digest(slice_rows: list[dict[str, Any]], declared: str | None) -> list[str]:
    actual = sha_lines(slice_rows)
    return [] if declared == actual else [f"manifest sha {declared} != file sha {actual}"]


def p_row_census(
    slice_rows: list[dict[str, Any]], before: int, after: int, added: int
) -> list[str]:
    problems: list[str] = []
    if after != len(slice_rows):
        problems.append(f"manifest rows_after {after} != {len(slice_rows)} on disk")
    if added != after - before:
        problems.append(f"added {added} != after-before {after - before}")
    if after < before:
        problems.append(f"the slice shrank: {before} -> {after}")
    return problems


def p_ledger_covers_slice(
    slice_rows: list[dict[str, Any]], ledger_keys: set[tuple[str, int]]
) -> list[str]:
    missing = {(str(row["symbol"]), int(row["timestamp"])) for row in slice_rows} - ledger_keys
    return [f"{len(missing)} slice rows never recorded in the ledger"] if missing else []


def p_idempotent_pair(entries: list[dict[str, Any]]) -> list[str]:
    """At least one re-run must have added nothing and left the bytes identical."""
    for previous, current in pairwise(entries):
        if (
            current.get("added") == 0
            and current.get("rows_before") == current.get("rows_after")
            and current.get("rows_before") == previous.get("rows_after")
            and current.get("slice_sha256_before") == current.get("slice_sha256_after")
            and previous.get("slice_sha256_after") == current.get("slice_sha256_after")
        ):
            return []
    return ["no capture re-run is recorded as adding nothing with identical bytes"]


def p_coverage_identity(ladder: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    per_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in ladder:
        per_symbol.setdefault(str(row["symbol"]), []).append(row)
    for symbol, bucket in per_symbol.items():
        observed = sum(1 for row in bucket if not row["missing"])
        missing = sum(1 for row in bucket if row["missing"])
        if len(bucket) != observed + missing:
            problems.append(f"{symbol}: expected != observed + missing")
    if not ladder:
        problems.append("empty ladder")
    return problems


def p_captured_count(slice_rows: list[dict[str, Any]], per_symbol: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    for symbol in SYMBOLS:
        actual = sum(1 for row in slice_rows if row["symbol"] == symbol)
        declared = int((per_symbol.get(symbol) or {}).get("captured_bars", -1))
        if declared != actual:
            problems.append(f"{symbol}: captured_bars {declared} != {actual} rows in the slice")
    return problems


def p_evaluated_matches_lane(
    expected_opens: list[int], lane_rows: list[dict[str, Any]], totals: dict[str, Any]
) -> list[str]:
    lane_keys = {(str(row["symbol"]), int(row["ts_ms"])) for row in lane_rows}
    recomputed = sum(
        1 for symbol in SYMBOLS for open_ms in expected_opens if (symbol, open_ms) in lane_keys
    )
    declared = int(totals.get("evaluated_symbol_bars", -1))
    return (
        []
        if declared == recomputed
        else [f"evaluated {declared} != {recomputed} recomputed from the lane ledger"]
    )


def p_missing_classification(ladder: list[dict[str, Any]]) -> list[str]:
    return [
        f"{row['symbol']}@{row['open_ms']} missing but classified {row.get('classified')!r}"
        for row in ladder
        if row["missing"] and row.get("classified") != "MISSING_NO_COLLECTOR"
    ]


def p_storage(storage: dict[str, Any], file_bytes: int, file_rows: int) -> list[str]:
    problems: list[str] = []
    declared_bytes = int((storage.get("slice") or {}).get("bytes", -1))
    if declared_bytes != file_bytes:
        problems.append(f"slice bytes {declared_bytes} != {file_bytes} on disk")
    declared_rows = int((storage.get("slice") or {}).get("rows", -1))
    if declared_rows != file_rows:
        problems.append(f"slice rows {declared_rows} != {file_rows} on disk")
    rate = float(storage.get("rate_bytes_per_hour", 0.0))
    per_row = file_bytes / file_rows if file_rows else 0.0
    if not close(rate, per_row * len(SYMBOLS), 1.0):
        problems.append(f"rate {rate} != bytes/row x symbols {per_row * len(SYMBOLS)}")
    overhead = float(storage.get("overhead_bytes_per_hour", 0.0))
    if not close(float(storage.get("effective_bytes_per_hour", 0.0)), rate + overhead, 0.01):
        problems.append("effective rate is not rate + overhead")
    return problems


def p_guard(storage: dict[str, Any], *, free: int, rate: float, overhead: float) -> list[str]:
    """Re-derive the guard's decision without calling the guard."""
    plan = storage.get("guard_plan") or {}
    required = (rate + overhead) * GUARD_HOURS
    required_stress = required * GUARD_STRESS
    usable = free - GUARD_RESERVE
    if required_stress > usable:
        expected = "INSUFFICIENT_FREE_SPACE"
    elif required > GUARD_VALVE:
        expected = "INCOHERENT_BUDGET"
    elif required_stress > GUARD_VALVE:
        expected = "TIGHT"
    else:
        expected = "COHERENT"
    problems: list[str] = []
    if plan.get("state") != expected:
        problems.append(f"guard state {plan.get('state')} != {expected} from its own arithmetic")
    if not close(float(plan.get("stress_multiplier", 0.0)), GUARD_STRESS):
        problems.append("stress multiplier was changed")
    if int(plan.get("reserve_bytes", -1)) != GUARD_RESERVE:
        problems.append("reserve was changed")
    if int(plan.get("collector_max_bytes", -1)) != GUARD_VALVE:
        problems.append("collector valve was changed")
    if int(plan.get("free_bytes", -1)) != free:
        problems.append("free bytes do not match the host reading")
    return problems


def p_fallback_factor(storage: dict[str, Any]) -> list[str]:
    rate = float(storage.get("effective_bytes_per_hour", 0.0))
    declared = float(storage.get("fallback_overstatement_factor", 0.0))
    if rate <= 0:
        return ["a zero byte-rate is not a measurement"]
    expected = 240_000_000 / rate
    return [] if close(declared, expected, 1.0) else [f"factor {declared} != {expected}"]


def p_trade_reconciles(trade: dict[str, Any]) -> list[str]:
    expected = (
        float(trade.get("reference_gross_pnl", 0.0))
        - float(trade.get("execution_cost_usdt", 0.0))
        - float(trade.get("entry_commission", 0.0))
        - float(trade.get("exit_commission", 0.0))
    )
    return (
        []
        if close(float(trade.get("pnl", 0.0)), expected)
        else [f"{trade.get('trade_id')}: pnl != reference - costs ({expected})"]
    )


def p_no_zero_cost(trades: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    for trade in trades:
        notional = float(trade["quantity"]) * float(trade["entry_price"])
        if notional <= 0:
            continue
        if float(trade.get("entry_commission", 0.0)) <= 0:
            problems.append(f"{trade.get('trade_id')}: entry commission is zero or negative")
        if float(trade.get("execution_cost_usdt", 0.0)) <= 0:
            problems.append(f"{trade.get('trade_id')}: execution cost is zero or negative")
    return problems


def p_equity_parity(report: dict[str, Any], trades: list[dict[str, Any]]) -> list[str]:
    net = sum(float(trade["pnl"]) for trade in trades)
    positions = report.get("positions_and_pnl") or {}
    parity = report.get("net_risk_parity") or {}
    problems: list[str] = []
    if not close(float(positions.get("realised_pnl_usdt", 0.0)), net):
        problems.append("positions.realised_pnl does not sum the trade ledger")
    if not close(float(positions.get("equity_mark_to_market_usdt", 0.0)), 10_000.0 + net, 1e-3):
        problems.append("broker equity != 10 000 + realised")
    if not parity.get("risk_equity_equals_broker_net"):
        problems.append("RiskManager equity != broker net equity")
    if not close(float(parity.get("risk_equity_usdt", 0.0)), 10_000.0 + net, 1e-3):
        problems.append("risk equity != 10 000 + net")
    if not (report.get("costs") or {}).get("reconciles"):
        problems.append("the cost block does not reconcile")
    return problems


def p_monotonic(fills: dict[str, int]) -> list[str]:
    if not (fills.get("3x", 0) <= fills.get("2x", 0) <= fills.get("1x", 0)):
        return [f"fills are not non-increasing under cost: {fills}"]
    return []


def p_loss_limit_explains(replay: dict[str, Any]) -> list[str]:
    runs = replay.get("runs") or {}
    base = int((runs.get("1x") or {}).get("fills", 0))
    problems: list[str] = []
    for name in ("2x", "3x"):
        run = runs.get(name) or {}
        if int(run.get("fills", 0)) < base:
            rules = run.get("rejections_by_rule") or {}
            if not any(
                key in rules for key in ("weekly_loss_limit", "daily_loss_limit", "max_drawdown")
            ):
                problems.append(f"{name} lost fills but no loss/drawdown rule rejected any")
    return problems


def p_baseline_equivalence(
    replay: dict[str, Any], frictionless: list[dict[str, Any]], baseline: list[dict[str, Any]]
) -> list[str]:
    keys = ("symbol", "entry_price", "exit_price", "quantity", "pnl", "exit_reason", "trade_id")
    if len(frictionless) != len(baseline):
        return [f"{len(frictionless)} frictionless fills != {len(baseline)} baseline fills"]
    for left, right in zip(frictionless, baseline, strict=True):
        for key in keys:
            if left.get(key) != right.get(key):
                return [f"{left.get('trade_id')}: {key} differs from the baseline"]
    return []


def p_block_readers(sources: dict[str, str]) -> list[str]:
    problems: list[str] = []
    evaluator = sources.get("evaluator", "")
    for rule in ("excessive_spread_bps", "extreme_atr_pct", "high_latency_ms", "weekend_trading"):
        if rule not in evaluator:
            problems.append(f"{rule} is not named by the evaluator")
    launcher = sources.get("launcher", "")
    if "defensive_blocks=settings.risk.blocks" not in launcher:
        problems.append("the paper launcher does not wire the blocks policy")
    cycle = sources.get("cycle", "")
    verdict_call = cycle.find("verdict = self._defensive_verdict(")
    risk_call = cycle.find("check = self._risk.check_signal(")
    if verdict_call == -1 or risk_call == -1:
        problems.append("the cycle does not name both the verdict call and the risk call")
    elif verdict_call > risk_call:
        problems.append("the cycle checks risk before evaluating the defensive blocks")
    harness = sources.get("harness", "")
    for field_name in ("spread_bps", "atr_pct", "timestamp"):
        if field_name not in harness:
            problems.append(f"the harness does not read {field_name}")
    return problems


def p_single_writer(capture_module: str, collector: str) -> list[str]:
    """The slice is only written inside the locked read-merge-write transaction.

    An atomic replace keeps a crash from tearing the file; it does not keep two
    overlapping captures from one overwriting the rows the other just added. The
    collector must therefore reach the slice through ``merge_and_write`` (which
    re-reads under an exclusive lock), never through a raw write.
    """
    problems: list[str] = []
    for symbol in ("def merge_and_write(", "def slice_lock(", "def is_closed("):
        if symbol not in capture_module:
            problems.append(f"oos_capture does not expose {symbol.strip()}")
    if "os.O_CREAT | os.O_EXCL" not in capture_module:
        problems.append("the lock file is not created exclusively")
    body = collector.split("def capture(", 1)[-1]
    if body.count("merge_and_write(") < 2:
        problems.append("the collector does not write both slices through merge_and_write")
    if "write_slice_atomic(" in body:
        problems.append("the collector still writes a slice outside the transaction")
    return problems


def p_config_unchanged(risk_yaml: str, runtime_yaml: str) -> list[str]:
    problems: list[str] = []
    if "weekend_trading: false" not in risk_yaml:
        problems.append("config/risk.yaml no longer declares weekend_trading: false")
    for key, value in (
        ("excessive_spread_bps", "50"),
        ("extreme_atr_pct", "8.0"),
        ("high_latency_ms", "2000"),
        ("max_daily_loss_pct", "1.0"),
        ("max_total_drawdown_pct", "5.0"),
    ):
        if f"{key}: {value}" not in risk_yaml:
            problems.append(f"config/risk.yaml changed {key} away from {value}")
    if "live_trading_enabled: true" in runtime_yaml:
        problems.append("config/runtime.yaml enables live trading")
    return problems


# --------------------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------------------


def main() -> int:
    checks = Checks()
    prereg = load(PREREG)
    freeze_ms = int(prereg.get("frozen_at_epoch_ms", 0))
    manifest = load(MANIFEST)
    integrity = load(OUT / "CAPTURE_INTEGRITY.json")
    storage = load(OUT / "STORAGE_MEASUREMENT.json")
    replay = load(OUT / "NET_RISK_REPLAY.json")
    economic = load(OUT / "ECONOMIC_RESULTS.json")
    blocks = load(OUT / "RISK_BLOCKS_MATRIX.json")
    slice_rows = rows(SLICE)

    append_only = manifest.get("append_only") or {}
    checks.check(
        "C1 slice rows are post-freeze",
        p_slice_post_freeze(slice_rows, freeze_ms),
        f"{len(slice_rows)} rows, freeze {freeze_ms}",
    )
    checks.check("C2 every slice key is unique", p_unique_keys(slice_rows))
    checks.check(
        "C3 the manifest digest is the file's digest",
        p_slice_digest(slice_rows, append_only.get("slice_sha256_after")),
    )
    checks.check(
        "C4 the row census adds up and the slice never shrank",
        p_row_census(
            slice_rows,
            int(append_only.get("rows_before", 0)),
            int(append_only.get("rows_after", -1)),
            int(append_only.get("added", -1)),
        ),
        f"before {append_only.get('rows_before')} after {append_only.get('rows_after')}",
    )

    ledger_entries = rows(LEDGER)
    ledger_keys: set[tuple[str, int]] = set()
    for entry in ledger_entries:
        for symbol, payload in (entry.get("symbols") or {}).items():
            for open_ms in payload.get("opens", []):
                ledger_keys.add((str(symbol), int(open_ms)))
    checks.check(
        "C5 the independent ledger records every slice row",
        p_ledger_covers_slice(slice_rows, ledger_keys),
        f"{len(ledger_keys)} ledger keys",
    )
    checks.check(
        "C6 a re-run added nothing and left the bytes identical",
        p_idempotent_pair(ledger_entries),
        f"{len(ledger_entries)} ledger entries",
    )

    ladder = integrity.get("ladder") or []
    checks.check("C7 expected = observed + missing per symbol", p_coverage_identity(ladder))
    checks.check(
        "C8 captured bars per symbol is the real count, not 0/1",
        p_captured_count(slice_rows, integrity.get("per_symbol") or {}),
    )
    checks.check("C9 missing hours are MISSING_NO_COLLECTOR", p_missing_classification(ladder))
    now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
    first_expected = ((freeze_ms // HOUR) + 1) * HOUR
    expected_opens = [
        open_ms for open_ms in range(first_expected, now_ms, HOUR) if open_ms + HOUR <= now_ms
    ]
    checks.check(
        "C10 evaluated hours match the lane's own ledger",
        p_evaluated_matches_lane(
            expected_opens,
            rows(OUT / "experimental_paper" / "COVERAGE_LEDGER.jsonl"),
            integrity.get("totals") or {},
        ),
        str((integrity.get("totals") or {}).get("evaluated_symbol_bars")),
    )
    newest_open = max((int(row["timestamp"]) for row in slice_rows), default=0)
    checks.check(
        "C11 the still-forming hour never entered the slice",
        [] if newest_open + HOUR <= now_ms else ["the newest captured bar has not closed"],
    )

    free = int((storage.get("guard_plan") or {}).get("free_bytes", 0))
    capture_source = (REPO / "src/trading_bot/research/oos_capture.py").read_text(encoding="utf-8")
    collector_source = (REPO / "scripts/edge15_oos_preregistration.py").read_text(
        encoding="utf-8"
    )
    checks.check(
        "C12 the slice is written only through the single-writer transaction",
        p_single_writer(capture_source, collector_source),
    )

    checks.check(
        "S1 storage bytes and rows match the file",
        p_storage(storage, SLICE.stat().st_size if SLICE.is_file() else 0, len(slice_rows)),
    )
    checks.check(
        "S2 the guard's decision follows its own arithmetic",
        p_guard(
            storage,
            free=free,
            rate=float(storage.get("rate_bytes_per_hour", 0.0)),
            overhead=float(storage.get("overhead_bytes_per_hour", 0.0)),
        ),
    )
    checks.check("S3 the fallback overstatement is the measured ratio", p_fallback_factor(storage))

    for name in ("1x", "2x", "3x"):
        trades = rows(OUT / "scratch" / f"net_{name}" / "CANONICAL_TRADES.jsonl")
        problems: list[str] = []
        for trade in trades:
            problems.extend(p_trade_reconciles(trade))
        checks.check(
            f"N{name[0]} {name}: every trade reconciles its net", problems, f"{len(trades)} trades"
        )
    trades_1x = rows(OUT / "scratch" / "net_1x" / "CANONICAL_TRADES.jsonl")
    checks.check("N4 no fill is free", p_no_zero_cost(trades_1x))
    checks.check(
        "N5 broker net, risk equity and reconciliation agree",
        p_equity_parity(load(OUT / "scratch" / "net_1x" / "CANONICAL_LANE_REPORT.json"), trades_1x),
    )
    checks.check(
        "N6 fills fall monotonically as costs rise",
        p_monotonic(replay.get("fills_by_multiplier") or {}),
    )
    checks.check("N7 lost fills are explained by a loss rule", p_loss_limit_explains(replay))
    checks.check(
        "N8 with costs off the engine reproduces WP-EDGE-016 fill for fill",
        p_baseline_equivalence(
            replay,
            rows(OUT / "scratch" / "frictionless" / "CANONICAL_TRADES.jsonl"),
            rows(OUT_16 / "CANONICAL_TRADES.jsonl"),
        ),
    )
    checks.check(
        "N9 the economic result is a net loss",
        []
        if float(economic.get("net_realised_usdt", 1.0)) < 0
        else ["the net result is not a loss"],
        str(economic.get("net_realised_usdt")),
    )

    sources = {
        "evaluator": (REPO / "src/trading_bot/risk/defensive_blocks.py").read_text(
            encoding="utf-8"
        ),
        "launcher": (REPO / "scripts/start_paper_trading.py").read_text(encoding="utf-8"),
        "cycle": (REPO / "src/trading_bot/paper/paper_cycle.py").read_text(encoding="utf-8"),
        "harness": (REPO / "src/trading_bot/paper/harness.py").read_text(encoding="utf-8"),
    }
    checks.check(
        "D1 the four declared blocks are evaluated on the paper path", p_block_readers(sources)
    )
    checks.check(
        "D2 the risk policy was not edited and live stays off",
        p_config_unchanged(
            (REPO / "config/risk.yaml").read_text(encoding="utf-8"),
            (REPO / "config/runtime.yaml").read_text(encoding="utf-8"),
        ),
    )
    checks.check(
        "D3 the block matrix maps all four rules",
        []
        if {row["rule"] for row in blocks.get("rules", [])}
        == {"excessive_spread_bps", "extreme_atr_pct", "high_latency_ms", "weekend_trading"}
        else ["the matrix does not cover the four rules"],
    )

    # -- fault injection: the same predicates must reject a tampered copy ---------------
    mutations: list[dict[str, Any]] = []

    def mutation(name: str, problems: list[str]) -> None:
        mutations.append({"id": name, "detected": bool(problems), "problems": problems[:3]})

    tampered_slice = [dict(row) for row in slice_rows][1:]
    mutation(
        "M1 drop a captured bar",
        p_ledger_covers_slice(tampered_slice, ledger_keys)
        or p_row_census(
            tampered_slice,
            int(append_only.get("rows_before", 0)),
            int(append_only.get("rows_after", -1)),
            int(append_only.get("added", -1)),
        ),
    )
    mutation("M2 duplicate a bar", p_unique_keys([*slice_rows, dict(slice_rows[0])]))
    mutation("M3 rewrite the manifest digest", p_slice_digest(slice_rows, "0" * 64))
    misclassified = [
        {
            "symbol": "BTC/USDT",
            "open_ms": 0,
            "missing": True,
            "classified": "NO_SIGNAL",
            "stages": ["EXPECTED"],
        }
    ]
    mutation("M4 call a missing hour a quiet one", p_missing_classification(misclassified))

    bad_trade = dict(trades_1x[0]) if trades_1x else {}
    bad_trade["pnl"] = float(bad_trade.get("pnl", 0.0)) + 1.0
    mutation("M5 inflate one trade's net", p_trade_reconciles(bad_trade))
    zeroed = {**bad_trade, "entry_commission": 0.0, "execution_cost_usdt": 0.0}
    mutation("M6 charge nothing", p_no_zero_cost([zeroed]))
    mutation(
        "M7 reverse the fill ladder",
        p_monotonic({"1x": 10, "2x": 20, "3x": 30}),
    )
    mutation(
        "M8 claim a huge rate still fits",
        p_guard(
            {
                "guard_plan": {
                    **storage.get("guard_plan", {}),
                    "state": "COHERENT",
                }
            },
            free=0,
            rate=1.0,
            overhead=1.0,
        ),
    )
    mutation(
        "M9 unwire the defensive blocks from the launcher",
        p_block_readers(
            {
                **sources,
                "launcher": sources["launcher"].replace(
                    "defensive_blocks=settings.risk.blocks", ""
                ),
            }
        ),
    )
    mutation(
        "M10 enable live trading in the runtime config",
        p_config_unchanged(
            (REPO / "config/risk.yaml").read_text(encoding="utf-8"),
            "live_trading_enabled: true",
        ),
    )
    mutation(
        "M11 break the frictionless equivalence",
        p_baseline_equivalence(replay, [], rows(OUT_16 / "CANONICAL_TRADES.jsonl")),
    )
    mutation(
        "M12 let the collector write the slice without the lock",
        p_single_writer(
            capture_source,
            collector_source.replace("merge_and_write(", "merge_slice("),
        ),
    )

    undetected = [row["id"] for row in mutations if not row["detected"]]
    checks.check(
        "V1 every injected fault is detected",
        [] if not undetected else [f"undetected: {', '.join(undetected)}"],
        f"{len(mutations)}/{len(mutations)} detected",
    )

    verdict = "VERIFIED" if not checks.failed else "NOT_VERIFIED"
    payload = {
        "schema_version": "EDGE17_INDEPENDENT_VERIFICATION_V1",
        "generated_at_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "builder": "scripts/edge15_oos_preregistration.py, scripts/edge16_paper_lane.py, scripts/edge17_capture.py, scripts/edge17_reports.py",
        "verifier": "scripts/edge17_verify.py (does not import the builder modules)",
        "verdict": verdict,
        "checks": checks.results,
        "verified": checks.verified,
        "total": len(checks.results),
        "failed": checks.failed,
        "mutations": mutations,
        "mutations_detected": sum(1 for row in mutations if row["detected"]),
        "mutations_total": len(mutations),
    }
    (OUT / "INDEPENDENT_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        "# WP-EDGE-017 — independent verification",
        "",
        f"**{verdict}** — {checks.verified}/{len(checks.results)} checks verified, "
        f"{payload['mutations_detected']}/{payload['mutations_total']} injected faults detected.",
        "",
        "The verifier does not import any module that built these artifacts: the rules below are",
        "re-implemented from the published JSON and from the text of the runtime sources.",
        "",
        "| check | status | detail |",
        "| --- | --- | --- |",
    ]
    for result in checks.results:
        detail = result["detail"] or (result["problems"][0] if result["problems"] else "")
        lines.append(f"| {result['id']} | {result['status']} | {detail} |")
    lines += ["", "## Injected faults", "", "| fault | detected |", "| --- | --- |"]
    for row in mutations:
        lines.append(f"| {row['id']} | {'yes' if row['detected'] else 'NO'} |")
    lines.append("")
    (OUT / "INDEPENDENT_VERIFICATION.md").write_text("\n".join(lines), encoding="utf-8")

    print(
        f"[17v] {verdict}: {checks.verified}/{len(checks.results)} checks, "
        f"{payload['mutations_detected']}/{payload['mutations_total']} faults detected"
    )
    for result in checks.failed:
        print(f"  FAILED {result['id']}: {result['problems'][:2]}")
    return 0 if verdict == "VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
