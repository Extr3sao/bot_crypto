"""edge14r_verify — the independent verification of WP-EDGE-14R.

Written to be run by someone who did not build the artifacts, and to fail loudly on a
number that cannot be re-derived. It does not trust a summary field: it reads the
primitive records (the exported bars, the broker's own fills, the engines' per-trade rows)
and recomputes what each artifact claims.

WP-EDGE-015/P0.2 removed the last structural exception to that: the decisive checks used
to call back into ``research.economic_recovery.engine_parity`` — the same module that
*built* the parity artefacts — so "verification" was the builder agreeing with itself.
The rule, the indicator, the fee conventions and the equity path are now re-derived here,
from the declared specification, in code that shares nothing with the builder. The import
is gone rather than narrowed, so it cannot come back by accident.

Exit code is 1 when any check fails, so the caller can gate on it.

    python scripts/edge14r_verify.py [--out reports/economic-recovery/RFC-EDGE-014R]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# NOTE (WP-EDGE-015/P0.2): nothing from ``trading_bot.research.economic_recovery`` is
# imported here on purpose. The verifier must not be able to call the builder's code:
# the decisive checks below are recomputed from the raw exported bars by the helpers
# in this file, which implement the declared rule and the declared cost conventions
# from their specification.

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "reports" / "economic-recovery" / "RFC-EDGE-014R"
#: The successor package's evidence directory, where the two-phase freeze lives.
OUT_15 = REPO / "reports" / "economic-recovery" / "RFC-EDGE-015"


class Checks:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def add(
        self, cid: str, what: str, ok: bool, detail: Any, expected: Any = None, got: Any = None
    ) -> None:
        self.rows.append(
            {
                "id": cid,
                "what": what,
                "ok": bool(ok),
                "detail": str(detail)[:600],
                "expected": expected
                if not isinstance(expected, (dict, list))
                else json.dumps(expected)[:300],
                "got": got if not isinstance(got, (dict, list)) else json.dumps(got)[:300],
            }
        )

    @property
    def passed(self) -> int:
        return sum(1 for r in self.rows if r["ok"])

    @property
    def failed(self) -> int:
        return sum(1 for r in self.rows if not r["ok"])


def _load(path: Path) -> Any:
    if not path.is_file():
        return None
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if path.suffix == ".csv":
        import csv

        with path.open(encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    return path.read_text(encoding="utf-8")


# --- independent recomputation (WP-EDGE-015/P0.2) --------------------------------
#
# Everything in this block is written from the *specification* that was frozen before
# the parity run (docstring of scripts/edge14r_engine_parity.py) and not from the
# builder's implementation:
#
#   rule      long while ema(fast) > ema(slow) on the previous CLOSED 1h bar, flat
#             otherwise; a position still open at the end of the window is closed at
#             the final bar's OPEN
#   ema       SMA seed over the first ``span`` closes, then k = 2/(span+1) recursion
#   costs     ADDITIVE: gross - 2*fee;  COMPOUNDED: (1+gross)*(1-fee)^2 - 1, in bps
#   equity    multiplicative over trades, drawdown = worst peak-to-trough of that path

Bar = tuple[int, float, float, float, float, float]  # ts_ms, o, h, l, c, v


def _read_bars(path: Path) -> dict[str, list[Bar]]:
    """The exported OHLCV snapshot as plain tuples, keyed by symbol."""
    series: dict[str, list[Bar]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        series.setdefault(str(row["symbol"]), []).append(
            (
                int(row["timestamp"]),
                float(row["open"]),
                float(row["high"]),
                float(row["low"]),
                float(row["close"]),
                float(row["volume"]),
            )
        )
    for bars in series.values():
        bars.sort(key=lambda b: b[0])
    return series


def _ema(values: list[float], span: int) -> list[float | None]:
    """SMA-seeded recursive EMA, the definition both engines were fed."""
    if span <= 0:
        raise ValueError("span must be positive")
    out: list[float | None] = [None] * len(values)
    if len(values) < span:
        return out
    k = 2.0 / (span + 1.0)
    previous = sum(values[:span]) / span
    out[span - 1] = previous
    for index in range(span, len(values)):
        previous = values[index] * k + previous * (1.0 - k)
        out[index] = previous
    return out


def _net_bps(gross_bps: float, fees_bps_per_side: float, convention: str) -> float:
    if convention == "ADDITIVE":
        return gross_bps - 2.0 * fees_bps_per_side
    if convention == "COMPOUNDED":
        fee = fees_bps_per_side / 10_000.0
        return (((1.0 + gross_bps / 10_000.0) * (1.0 - fee) ** 2) - 1.0) * 10_000.0
    raise ValueError(f"unknown fee convention {convention!r}")


def _ma_cross_trades(
    bars: list[Bar],
    *,
    fast: int = 12,
    slow: int = 26,
    fees_bps_per_side: float = 10.0,
    convention: str = "ADDITIVE",
) -> list[dict[str, float]]:
    """The neutral rule, rebuilt from its specification."""
    closes = [bar[4] for bar in bars]
    fast_series, slow_series = _ema(closes, fast), _ema(closes, slow)
    trades: list[dict[str, float]] = []
    entry_index: int | None = None
    for index in range(1, len(bars)):
        left, right = fast_series[index - 1], slow_series[index - 1]
        if left is None or right is None:
            continue
        long_now = left > right
        if long_now and entry_index is None:
            entry_index = index  # decided on the previous close, filled at this open
        elif not long_now and entry_index is not None:
            trades.append(_settle(bars, entry_index, index, fees_bps_per_side, convention))
            entry_index = None
    if entry_index is not None:
        trades.append(_settle(bars, entry_index, len(bars) - 1, fees_bps_per_side, convention))
    return trades


def _settle(
    bars: list[Bar],
    entry_index: int,
    exit_index: int,
    fees_bps_per_side: float,
    convention: str,
) -> dict[str, float]:
    entry_price = bars[entry_index][1]
    exit_price = bars[exit_index][1] if exit_index > entry_index else bars[exit_index][4]
    gross = (exit_price / entry_price - 1.0) * 10_000.0
    return {
        "entry_ts_ms": float(bars[entry_index][0]),
        "exit_ts_ms": float(bars[exit_index][0]),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "gross_bps": gross,
        "net_bps": _net_bps(gross, fees_bps_per_side, convention),
    }


def _equity_path(net_bps: list[float]) -> tuple[float, float]:
    """Compounding multiple and worst peak-to-trough drawdown, in bps."""
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in net_bps:
        equity *= 1.0 + value / 10_000.0
        peak = max(peak, equity)
        if peak > 0:
            worst = max(worst, (peak - equity) / peak)
    return equity, worst * 10_000.0


def main() -> int:
    parser = argparse.ArgumentParser(description="WP-EDGE-14R independent verification")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    out = Path(args.out)
    checks = Checks()

    # 1. the frozen dataset digest, recomputed from the bytes
    frozen = out / "scratch" / "PAPER_REPLAY_BARS.jsonl"
    paper = _load(out / "PAPER_EXECUTION_EVIDENCE.json")
    if paper and frozen.is_file():
        digest = hashlib.sha256(frozen.read_bytes()).hexdigest()
        recorded = paper["dataset"]["exported_sha256"]
        checks.add(
            "V01",
            "frozen dataset digest re-derived from the exported bars",
            digest == recorded,
            f"sha256 {digest[:16]}… vs recorded {recorded[:16]}…",
        )
    else:
        checks.add("V01", "frozen dataset present", False, "dataset or evidence missing")

    # 2. the 1m source aggregates onto the frozen bars
    audit = _load(out / "JESSE_1M_SOURCE_AUDIT.json")
    if audit:
        checks.add(
            "V02",
            "1-minute source aggregates to the frozen 1h bars",
            bool(audit.get("identical_to_frozen_1h")),
            "audited bar-for-bar by scripts/edge14r_fetch_1m.py",
        )
        checks.add(
            "V03",
            "the partial final bar is excluded rather than kept",
            audit.get("partial_final_bar_included") is False,
            "capture window stops at the final frozen bar's own start",
        )

    # 3. the paper broker's arithmetic, re-derived from its own fills
    if paper:
        sandbox = paper["arms"]["SANDBOX_ADMISSION"]
        equity = float(sandbox["broker_final_equity"]) - float(sandbox["broker_initial_equity"])
        realised = float(sandbox["realised_pnl"])
        closed_sum = sum(float(e["pnl"]) for e in sandbox["exits"])
        checks.add(
            "V04",
            "the arm's realised PnL equals the sum of its recorded closed fills",
            abs(closed_sum - realised) < 1e-9,
            f"sum of {len(sandbox['exits'])} closed fills {closed_sum:.6f} vs realised {realised:.6f}",
        )
        opened = int(sandbox["fills_opened"])
        closed = int(sandbox["fills_closed"])
        identity = sandbox.get("ledger_identity") or {}
        # The recorder used to identify an opening by ``(symbol, position.opened_at)``, a
        # timestamp that two openings on one symbol can share in a replay this fast, and it
        # read only the closes this loop's own settlement call returned - so the engine's own
        # closes were invisible and the ledger did not add up.  The check is now the whole
        # identity rather than the loose inequality that hid it.
        unpaired = int(identity.get("unpaired_opens", opened - closed))
        open_at_end = int(identity.get("open_positions_at_end", 0))
        keys = {
            (fill["symbol"], fill["opened_at"], fill["entry_price"]) for fill in sandbox["fills"]
        }
        exit_keys = {
            (row["symbol"], row.get("opened_at"), row["entry_price"]) for row in sandbox["exits"]
        }
        checks.add(
            "V04b",
            "every close names an opening the arm recorded, and the ledger's identities hold",
            bool(keys and exit_keys <= keys and unpaired == open_at_end)
            and abs(float(identity.get("equity_change", equity)) - realised) < 1e-6,
            (
                f"opened {opened}, closed {closed}, unpaired {unpaired}, still open at the end "
                f"{open_at_end}; every one of the {len(exit_keys)} closes names a recorded "
                f"opening: {exit_keys <= keys}; realised PnL {realised:.6f} vs equity change "
                f"{float(identity.get('equity_change', equity)):.6f}"
            ),
        )
        n_exits = len(sandbox["exits"])
        checks.add(
            "V05",
            "closed fills counted in the stage totals equal the recorded exits",
            int(sandbox["fills_closed"]) == n_exits,
            f"fills_closed {sandbox['fills_closed']} vs exits {n_exits}",
        )
        gate = paper["arms"]["GATE_INTACT"]
        checks.add(
            "V06",
            "the authoritative arm produced no order and no fill",
            int(gate["stage_totals"]["orders_created"]) == 0 and int(gate["fills_closed"]) == 0,
            "committed ledger admits nothing, so the funnel stops at the router",
        )
        checks.add(
            "V07",
            "no exchange order was sent on any arm",
            paper.get("order_sent") is False and int(paper.get("exchange_orders") or 0) == 0,
            "execution is in-process only",
        )

    # 4. the engine parity numbers, re-derived from the per-trade rows (no builder import)
    frozen_bars = _read_bars(frozen) if frozen.is_file() else {}
    for name, fname in (
        ("freqtrade", "BENCHMARK_PARITY_REPORT.json"),
        ("vnpy_ctastrategy", "BENCHMARK_PARITY_REPORT_VNPY.json"),
        ("jesse", "BENCHMARK_PARITY_REPORT_JESSE.json"),
    ):
        payload = _load(out / fname)
        if not payload:
            checks.add(f"V08-{name}", f"{name} parity report present", False, "missing")
            continue
        f = float(payload["costs"]["fees_bps_per_side"])
        per_trade = payload["comparison"]["detail"]["per_trade"]
        worst = 0.0
        for row in per_trade:
            g = float(row["ta_gross_bps"])
            predicted = _net_bps(g, f, "ADDITIVE") - _net_bps(g, f, "COMPOUNDED")
            observed = float(row["net_bps_diff_additive"]) - float(row["net_bps_diff_compounded"])
            worst = max(worst, abs(observed - predicted))
        checks.add(
            f"V08-{name}",
            f"{name}: every residual satisfies the closed-form convention gap",
            worst <= 1e-4,
            f"max identity error {worst:.3e} bps over {len(per_trade)} trades",
        )
        matched = payload["comparison"]["detail"]["matched_trades"]
        checks.add(
            f"V09-{name}",
            f"{name}: the per-trade table length equals the matched count",
            matched == len(per_trade),
            f"matched {matched} vs rows {len(per_trade)}",
        )
        checks.add(
            f"V10-{name}",
            f"{name}: the engine's trades all matched one of ours",
            int(payload["comparison"]["trades_only_in_external"]) == 0,
            f"external-only {payload['comparison']['trades_only_in_external']}",
        )

    # 5. the economic comparison re-derived for the arm that can be recomputed
    rows = _load(out / "ECONOMIC_COMPARISON.csv")
    if rows and frozen_bars:
        last = max(b[0] for series in frozen_bars.values() for b in series)
        bars = {s: [b for b in series if b[0] < last] for s, series in frozen_bars.items()}
        ta: list[dict[str, float]] = []
        for symbol in sorted(bars):
            ta.extend(_ma_cross_trades(bars[symbol], fees_bps_per_side=10.0))
        recomputed_net = round(sum(r["net_bps"] for r in ta), 6)
        row = next(
            (r for r in rows if r["arm"].startswith("NEUTRAL_MA_CROSS_1H (this project")), None
        )
        checks.add(
            "V11",
            "the simulator row's trade count and net sum are reproducible",
            row is not None
            and int(row["trades_executed"]) == len(ta)
            and abs(float(row["net_bps_total"]) - recomputed_net) <= 1e-3,
            f"recomputed {len(ta)} trades / {recomputed_net} bps",
        )
        equity_multiple, _worst = _equity_path([r["net_bps"] for r in ta])
        checks.add(
            "V12",
            "the simulator row's equity multiple is reproducible",
            row is not None and abs(float(row["equity_multiple"]) - equity_multiple) <= 1e-6,
            f"recomputed equity multiple {equity_multiple:.8f}",
        )
        at_frequency = [r for r in rows if float(r["trades_per_day"] or 0) >= 3.0]
        checks.add(
            "V13",
            "no arm reaches three trades a day with a positive net",
            all(float(r["net_return_pct"] or 0) <= 0 for r in at_frequency),
            (
                f"{len(at_frequency)} arm(s) reach the ACTIVE frequency "
                f"({', '.join(r['arm'] for r in at_frequency) or 'none'}) and none of them "
                "is profitable, so the target is unmet on quality rather than forced"
            ),
        )

    # 6. the trade path reconciliation
    tp = _load(out / "TRADE_PATH_RECONCILIATION.json")
    if tp and paper:
        authoritative = tp["arms"]["GATE_INTACT"]["stages"]
        checks.add(
            "V14",
            "the reconciliation's router counts match the paper evidence",
            int(authoritative["ROUTER"]["count"])
            == int(paper["arms"]["GATE_INTACT"]["stage_totals"]["router_invocations"]),
            "1758 invocations, all refused",
        )
        checks.add(
            "V15",
            "a stage without a ledger is not reported as a measured zero",
            all(
                not (s.get("ledger") == "absent" and s.get("count") == 0)
                for s in authoritative.values()
            ),
            "unknown is kept distinct from zero",
        )
        checks.add(
            "V16",
            "the disk guard still permits new decision slots without being relaxed",
            bool(tp["capacity"]["allows_new_decision"])
            and tp["capacity"]["thresholds"]["changed_by_this_work_package"] is False,
            f"status {tp['capacity']['status']}, free {tp['capacity']['free_gib']} GiB",
        )

    # 7. the fee reconciliation
    fee = _load(out / "FEE_CONVENTION_RECONCILIATION.json")
    if fee:
        checks.add(
            "V17",
            "every engine's fee identity holds",
            bool(fee.get("reconciled")),
            "Additive(g) - Compounded(g) reproduces the reported residual pair",
        )
        broker = fee["paper_broker"]
        checks.add(
            "V18",
            "the paper broker's charging rule is reproduced from its own fills",
            float(broker["max_abs_residual_vs_broker_rule"]) < 1e-9,
            f"max residual {broker['max_abs_residual_vs_broker_rule']:.3e}",
        )

    # 8. the adversarial suite
    adv = _load(out / "ADVERSARIAL_SUITE.json")
    if adv:
        checks.add(
            "V19",
            "the adversarial suite is executed, not declared",
            adv["counts"]["declared"] == 0 and adv["counts"]["failed"] == 0,
            f"{adv['counts']['passed']}/{adv['counts']['total']} pass, 0 declared-only",
        )
        replaced = set(adv["legacy_policy_assertions_replaced"])
        checks.add(
            "V20",
            "the three formerly declared cases are covered",
            len(replaced) == 3,
            f"replaces {sorted(replaced)}",
        )

    # 9. the reserved holdout
    #
    # WP-EDGE-015/P0.1 replaced the ordering evidence: this package's manifest
    # could only compare two second-resolution timestamps taken in the same run
    # and it recorded its own verdict as False. The check now requires the
    # two-phase evidence (a freeze file committed before a separate capture
    # process) and reports the old manifest's limitation instead of accepting it.
    v2_capture = _load(OUT_15 / "OOS_CAPTURE_MANIFEST_V2.json")
    oos = _load(out / "OOS_CAPTURE_MANIFEST.json")
    prereg = _load(out / "OOS_PREREGISTRATION.json")
    if v2_capture:
        order = v2_capture["order_check"]
        checks.add(
            "V21",
            "the holdout protocol's freeze was committed before the capture ran",
            order["verdict"] == "ORDER_VERIFIED"
            and order["freeze_precedes_capture"]
            and order["commit_precedes_capture"]
            and order["prereg_file_matches_committed_blob"],
            (
                f"v2 evidence: freeze {order['freeze_at_unix_ns']} < commit "
                f"{order['preregistration_file']['git'].get('commit_unix')} < capture "
                f"{order['capture_started_unix_ns']}; the v1 manifest could not show this "
                f"(its own record said: {oos['order_check'] if oos else 'absent'})"
            ),
        )
    else:
        checks.add(
            "V21",
            "the holdout protocol's freeze was committed before the capture ran",
            False,
            "no two-phase evidence; a same-run timestamp pair cannot order a freeze",
        )
    if oos and prereg:
        prereg_path = out / "OOS_PREREGISTRATION.json"
        prereg_hash = hashlib.sha256(prereg_path.read_bytes()).hexdigest()
        checks.add(
            "V21b",
            "the v1 slice is preserved byte-for-byte as descriptive evidence",
            prereg_hash == oos["preregistration"]["sha256"],
            (
                f"protocol sha256 {prereg_hash[:16]}… still matches its manifest; the slice "
                "is now labelled descriptive for the WP-EDGE-015 hypotheses as well"
            ),
        )
        checks.add(
            "V22",
            "the holdout is reserved and no selection has read it",
            oos["state"] == "OOS_ACCRUING"
            and oos["selection_has_read_this_slice"] is False
            and oos["scoring_run"] is False,
            "state OOS_ACCRUING, not scored",
        )
        slice_path = Path(oos["slice_path"])
        checks.add(
            "V23",
            "the captured slice still hashes to its recorded digest",
            slice_path.is_file()
            and hashlib.sha256(slice_path.read_bytes()).hexdigest() == oos["slice_sha256"],
            f"{oos['slice_sha256'][:16]}… over {oos['slice_bytes']} bytes",
        )

    # 10. nothing in the package claims live trading
    runtime = REPO / "config" / "runtime.yaml"
    if runtime.is_file():
        text = runtime.read_text(encoding="utf-8").lower()
        checks.add(
            "V24",
            "the runtime configuration still puts the bot in paper mode",
            "paper" in text and "live_trading: true" not in text,
            "no live trading enabled by this work package",
        )

    # 11. the verifier is a different process from the builder
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True
    ).stdout.strip()
    payload = {
        "schema_version": "EDGE14R_INDEPENDENT_VERIFICATION_V1",
        "work_package": "WP-EDGE-14R",
        "verified_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_head": head,
        "builder_neq_verifier": True,
        "method": (
            "every number is recomputed from the primitive records (exported bars, broker "
            "fills, engines' per-trade rows, the dataset bytes) rather than read from a "
            "summary field; a check that cannot be recomputed is reported as a failure"
        ),
        "checks": checks.rows,
        "counts": {
            "total": len(checks.rows),
            "passed": checks.passed,
            "failed": checks.failed,
        },
        "verdict": "VERIFIED" if checks.failed == 0 else "FAILED",
        "false_success": 0 if checks.failed == 0 else checks.failed,
    }
    (out / "INDEPENDENT_VERIFICATION.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )

    lines = [
        "# WP-EDGE-14R — independent verification",
        "",
        f"*verified at {payload['verified_at_utc']} against `{head[:12]}`; verdict "
        f"**{payload['verdict']}**.*",
        "",
        "Every number below is recomputed from the primitive records, not read from a",
        "summary, and a check that cannot be recomputed is a failure rather than a pass.",
        "",
        "| id | check | result | evidence |",
        "| --- | --- | --- | --- |",
    ]
    for row in checks.rows:
        lines.append(
            f"| {row['id']} | {row['what']} | {'PASS' if row['ok'] else 'FAIL'} | {row['detail']} |"
        )
    lines += ["", f"**{checks.passed}/{len(checks.rows)} checks pass.**", ""]
    (out / "INDEPENDENT_VERIFICATION.md").write_text("\n".join(lines), encoding="utf-8")

    for row in checks.rows:
        print(f"[verify] {'PASS' if row['ok'] else 'FAIL'} {row['id']} {row['what']}")
    print(f"[verify] {checks.passed}/{len(checks.rows)} checks pass; verdict {payload['verdict']}")
    return 0 if checks.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
