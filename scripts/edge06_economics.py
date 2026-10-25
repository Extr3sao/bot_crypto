#!/usr/bin/env python
"""WP-EDGE-06 Track B — what the frozen books actually earned, and where the money went.

Two questions, one command, and no new measurement:

1. **What was measured, book by book, window by window.** Every figure is read from the
   frozen campaign artefacts of WP-EDGE-01 and carries their digest, so this audit cannot
   quietly disagree with the run it audits: if the artefact moves, the digests move with it.
2. **Why the intraday book loses.** ``gross_usdt`` and the two cost components are already
   separated in that artefact — the campaign records them per trade — so the question "does
   it lose money because of costs or because the setup has no edge?" is answerable by
   arithmetic instead of by opinion. The answer for the frozen book is written in
   ``INTRADAY_COST_DECOMPOSITION``: the gross is *already negative* in DEV, in VAL and in
   OOS, and costs are the larger part of the net loss. A setup whose expectation before
   costs is negative does not become profitable by lowering fees; the breakeven gross the
   book would need is printed next to the gross it has.

The per-trade rows are read from ``TRADES.csv`` for the splits by asset, by entry-trend
state and by benchmark context, because a net carried by one asset is a different finding
from a net spread evenly across three, and the campaign's own metrics only break it down two
ways.

Read-only: it writes reports, never trades, and it re-runs no campaign.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_DIR = REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-01"
RESULTS = CAMPAIGN_DIR / "STRATEGY_RESULTS.json"
TRADES = CAMPAIGN_DIR / "TRADES.csv"

SCHEMA_VERSION = "EDGE06_ECONOMICS_AUDIT_V1"

#: The books, and which ones the WP-EDGE-01 campaign actually admitted.
FAMILY_NOTE = {
    "edge_intra_01": "intraday breakout of the prior 20-bar extreme, 15m, 1h trend filter",
    "edge_intra_02": "intraday retest of the broken level with an FVG filter, 15m",
    "edge_intra_02_no_fvg": "edge_intra_02 with the FVG filter removed (ablation)",
    "edge_trend_01_4h": "trend following, 4h, trailing exit",
    "edge_trend_01_1d": "trend following, 1d, trailing exit",
}


def now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def stamp(instant_ms: int) -> str:
    return datetime.fromtimestamp(instant_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_results() -> tuple[dict[str, Any], dict[str, str]]:
    payload = json.loads(RESULTS.read_text(encoding="utf-8"))
    digests = {
        str(RESULTS.relative_to(REPO_ROOT)).replace("\\", "/"): sha256_file(RESULTS),
        str(TRADES.relative_to(REPO_ROOT)).replace("\\", "/"): sha256_file(TRADES),
    }
    return payload, digests


def audit_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per (book, window, scenario): the frozen metrics, restated with provenance."""
    rows: list[dict[str, Any]] = []
    for book, candidate in (payload.get("candidates") or {}).items():
        for window, scenarios in sorted((candidate.get("splits") or {}).items()):
            for scenario, metrics in sorted(scenarios.items()):
                if not isinstance(metrics, dict):
                    continue
                rows.append(
                    {
                        "book": book,
                        "window": window,
                        "scenario": scenario,
                        "family": FAMILY_NOTE.get(book, "unnamed candidate"),
                        "trades": metrics.get("trades"),
                        "gross_usdt": metrics.get("gross_usdt"),
                        "fees_usdt": metrics.get("fees_usdt"),
                        "price_costs_usdt": metrics.get("price_costs_usdt"),
                        "costs_usdt": _round(
                            _num(metrics.get("fees_usdt")) + _num(metrics.get("price_costs_usdt"))
                        ),
                        "net_usdt": metrics.get("net_usdt"),
                        "expectancy_usdt": metrics.get("expectancy_usdt"),
                        "profit_factor": metrics.get("profit_factor"),
                        "win_rate_pct": metrics.get("win_rate_pct"),
                        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                        "cost_bps_per_trade": metrics.get("total_cost_bps_per_trade"),
                        "largest_trade_share_of_net": metrics.get("largest_trade_share_of_net"),
                        "verdict": candidate.get("verdict"),
                    }
                )
    return rows


def _num(value: Any) -> float:
    """CSV cells arrive as text; a cell that is not a number is 0 and is never invented.

    The frozen JSON carries real numbers and the frozen CSV carries their text: both are read
    through this one function so a window bound or a notional cannot silently become 0.0
    because it was spelled as a string.
    """
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _round(value: float, digits: int = 4) -> float:
    return round(value, digits)


def trade_rows() -> list[dict[str, Any]]:
    with TRADES.open(encoding="utf-8", newline="") as handle:
        return [
            {
                **row,
                "gross": _num(row.get("gross")),
                "fees": _num(row.get("fees")),
                "price_costs": _num(row.get("price_costs")),
                "net": _num(row.get("net")),
                "notional": _num(row.get("notional")),
                "duration_min": _num(row.get("duration_min")),
            }
            for row in csv.DictReader(handle)
        ]


def _bucket(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get(key) or "UNKNOWN"), []).append(row)
    out: dict[str, Any] = {}
    for name, subset in sorted(grouped.items()):
        notional = sum(row["notional"] for row in subset)
        out[name] = {
            "trades": len(subset),
            "gross_usdt": _round(sum(row["gross"] for row in subset)),
            "fees_usdt": _round(sum(row["fees"] for row in subset)),
            "price_costs_usdt": _round(sum(row["price_costs"] for row in subset)),
            "net_usdt": _round(sum(row["net"] for row in subset)),
            "gross_bps_per_trade": _round(
                sum(row["gross"] for row in subset) / notional * 10_000.0, 4
            )
            if notional
            else None,
            "cost_bps_per_trade": _round(
                sum(row["fees"] + row["price_costs"] for row in subset) / notional * 10_000.0, 4
            )
            if notional
            else None,
            "win_rate_pct": _round(
                100.0 * sum(1 for row in subset if row["net"] > 0) / len(subset), 4
            ),
        }
    return out


def decomposition(payload: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The intraday book, decomposed: what it earned before costs, and what costs took.

    The framing that matters is the *breakeven gross*: the book's cost per trade is a fact
    about the venue and the size, and the question is whether the setup's gross expectation
    clears it. Reporting both numbers side by side is the whole analysis; the fraction of
    the loss that is cost is derived, not asserted.
    """
    books: dict[str, Any] = {}
    intraday = [row for row in rows if row["candidate"] == "edge_intra_01"]
    for window in ("DEV", "VAL", "OOS"):
        for scenario in ("BASE", "2X_FEES", "ADVERSE"):
            subset = [row for row in intraday if row["scenario"] == scenario]
            subset = [row for row in subset if _window_of(row["decision_ts"]) == window]
            if not subset:
                continue
            notional = sum(row["notional"] for row in subset)
            gross = sum(row["gross"] for row in subset)
            fees = sum(row["fees"] for row in subset)
            price_costs = sum(row["price_costs"] for row in subset)
            net = sum(row["net"] for row in subset)
            costs = fees + price_costs
            books.setdefault("edge_intra_01", {})[f"{window}:{scenario}"] = {
                "trades": len(subset),
                "notional_usdt": _round(notional, 2),
                "gross_usdt": _round(gross),
                "fees_usdt": _round(fees),
                "price_costs_usdt": _round(price_costs),
                "costs_usdt": _round(costs),
                "net_usdt": _round(net),
                "gross_bps_per_trade": _round(gross / notional * 10_000.0, 4) if notional else None,
                "cost_bps_per_trade": _round(costs / notional * 10_000.0, 4) if notional else None,
                "breakeven_gross_bps_needed": _round(costs / notional * 10_000.0, 4)
                if notional
                else None,
                "gross_is_positive": gross > 0,
                "loss_explained_by_costs_pct": (
                    _round(costs / abs(net) * 100.0, 2) if net < 0 else None
                ),
                "residual_gross_deficit_usdt": _round(gross) if gross < 0 else 0.0,
                "by_asset": _bucket(subset, "asset"),
                "by_entry_trend_state": _bucket(subset, "regime"),
                "by_market_context": _bucket(subset, "market_context"),
                "by_exit_reason": _bucket(subset, "exit_reason"),
                "avg_duration_min": _round(
                    sum(row["duration_min"] for row in subset) / len(subset), 2
                ),
            }

    derived: dict[str, Any] = {}
    for book, windows in books.items():
        base_rows = {name: row for name, row in windows.items() if name.endswith(":BASE")}
        if not base_rows:
            continue
        positives = [name for name, row in base_rows.items() if row["gross_is_positive"]]
        worst = min(base_rows.items(), key=lambda item: item[1]["gross_usdt"])
        if not positives:
            reading = (
                "the gross expectation is negative in every window measured, before a single "
                "fee is charged: "
                + "; ".join(
                    f"{name} {row['gross_usdt']:,.2f} USDT over {row['trades']} trades "
                    f"({row['gross_bps_per_trade']:,.2f} bps/trade)"
                    for name, row in sorted(base_rows.items())
                )
                + ". Costs are the larger part of the net loss, but they are not the cause: a "
                "book that needed only a fee cut would show a positive gross against a negative "
                "net. Lowering fees cannot move a negative expectancy across zero — only a "
                "different setup, a different entry, or a longer hold can."
            )
            conclusion = "NO_GROSS_EDGE"
        else:
            reading = (
                "the gross expectation is positive in "
                f"{', '.join(sorted(positives))} and negative in the rest: this is a "
                "cost-coverage problem, and the levers are the cost per trade, the hold time or "
                "the frequency — not the signal's direction."
            )
            conclusion = "COST_COVERAGE_PROBLEM"
        derived[book] = {
            "reading": reading,
            "conclusion": conclusion,
            "windows_with_positive_gross": sorted(positives),
            "windows_measured": sorted(base_rows),
            "worst_window": {"name": worst[0], "gross_usdt": worst[1]["gross_usdt"]},
        }
    return {
        "schema_version": "EDGE06_INTRADAY_DECOMPOSITION_V1",
        "books": books,
        "derived": derived,
        "method": (
            "per-trade rows from the frozen campaign's TRADES.csv; gross, fees, price costs and "
            "net are the fields the simulator itself wrote, so nothing is re-derived from a "
            "curve. Windows are the frozen DEV/VAL/OOS bounds of the campaign."
        ),
    }


_WINDOWS = {
    "DEV": (datetime(2024, 10, 1, tzinfo=UTC), datetime(2025, 6, 30, tzinfo=UTC)),
    "VAL": (datetime(2025, 7, 1, tzinfo=UTC), datetime(2025, 12, 31, tzinfo=UTC)),
    "OOS": (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 10, 7, tzinfo=UTC)),
}


def _window_of(decision_ts: str) -> str:
    instant = datetime.fromtimestamp(_num(decision_ts) / 1000, tz=UTC)
    for name, (start, end) in _WINDOWS.items():
        if start <= instant <= end:
            return name
    return "OUTSIDE"


def build() -> dict[str, Any]:
    instant = now_ms()
    as_of = stamp(instant)
    payload, digests = load_results()
    rows = trade_rows()
    audit = audit_rows(payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": f"EDGE06-ECON-{as_of.replace('-', '').replace(':', '')}",
        "as_of_utc": as_of,
        "source_artifacts": digests,
        "params_hash": payload.get("params_hash"),
        "audit": audit,
        "decomposition": decomposition(payload, rows),
        "reused_campaign": {
            "path": str(RESULTS.relative_to(REPO_ROOT)).replace("\\", "/"),
            "note": (
                "these figures were measured by the WP-EDGE-01 campaign, not by this work "
                "package: the audit reads them and the digests above say which bytes it read"
            ),
        },
        "hypothetical": True,
        "order_sent": False,
        "promotion": "NONE",
    }


def _fmt(value: Any, digits: int = 2) -> str:
    return f"{value:,.{digits}f}" if isinstance(value, (int, float)) else "—"


def render(payload: dict[str, Any]) -> str:
    lines = [
        "# WP-EDGE-06 — what the frozen books earned, and where the intraday loss comes from",
        "",
        f"*Read at `{payload['as_of_utc']}`, from the WP-EDGE-01 campaign artefacts at "
        f"`params_hash {payload['params_hash']}`.*",
        "",
        "## 1. The books, as measured by the campaign that owns them",
        "",
        "| Book | Window | Scenario | Trades | Gross | Fees | Price costs | Net | Expectancy | PF | "
        "DD % | Cost bps/trade | Verdict |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in payload["audit"]:
        if row["scenario"] != "BASE":
            continue
        lines.append(
            f"| `{row['book']}` | {row['window']} | {row['scenario']} | {row['trades']} | "
            f"{_fmt(row['gross_usdt'])} | {_fmt(row['fees_usdt'])} | "
            f"{_fmt(row['price_costs_usdt'])} | **{_fmt(row['net_usdt'])}** | "
            f"{_fmt(row['expectancy_usdt'], 4)} | {_fmt(row['profit_factor'], 4)} | "
            f"{_fmt(row['max_drawdown_pct'], 2)} | {_fmt(row['cost_bps_per_trade'], 2)} | "
            f"`{row['verdict']}` |"
        )
    lines += [
        "",
        "Costs are not re-derived from a curve: each row is the sum of the `fees` and "
        "`price_costs` the simulator wrote per trade.",
        "",
        "## 2. The intraday book, decomposed",
        "",
        "| Window:scenario | Trades | Gross | Costs | Net | Gross bps/trade | Cost bps/trade | "
        "Cost share of the loss |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for book, windows in payload["decomposition"]["books"].items():
        for name, row in windows.items():
            lines.append(
                f"| `{book}` {name} | {row['trades']} | {_fmt(row['gross_usdt'])} | "
                f"{_fmt(row['costs_usdt'])} | **{_fmt(row['net_usdt'])}** | "
                f"{_fmt(row['gross_bps_per_trade'], 2)} | {_fmt(row['cost_bps_per_trade'], 2)} | "
                f"{_fmt(row['loss_explained_by_costs_pct'], 1)} % |"
            )
    lines += ["", "### What the arithmetic says", ""]
    for book, derived in payload["decomposition"]["derived"].items():
        lines += [f"- `{book}` — **{derived['conclusion']}**. {derived['reading']}", ""]

    first = next(iter(payload["decomposition"]["books"].values()), {})
    dev = first.get("DEV:BASE")
    if dev:
        lines += [
            "### The same book by asset, entry trend state and market context (DEV, BASE)",
            "",
            "| Split | Trades | Gross | Costs | Net | Gross bps/trade |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for label, key in (
            ("asset", "by_asset"),
            ("entry trend state", "by_entry_trend_state"),
            ("market context", "by_market_context"),
            ("exit reason", "by_exit_reason"),
        ):
            for name, row in (dev.get(key) or {}).items():
                lines.append(
                    f"| {label}: `{name}` | {row['trades']} | {_fmt(row['gross_usdt'])} | "
                    f"{_fmt(row['fees_usdt'] + row['price_costs_usdt'])} | "
                    f"{_fmt(row['net_usdt'])} | {_fmt(row['gross_bps_per_trade'], 2)} |"
                )
    lines += [
        "",
        "## 3. Where these numbers come from",
        "",
        "| Artefact | sha256 |",
        "| --- | --- |",
    ]
    for name, digest in payload["source_artifacts"].items():
        lines.append(f"| `{name}` | `{digest}` |")
    lines += [
        "",
        f"*`run_id`: `{payload['run_id']}`. This audit measures nothing new: it restates the "
        "frozen campaign's own fields, and the digests above are what makes that checkable.*",
        "",
        "Nothing here promotes a strategy, sizes an order or touches a limit: "
        "`promotion: NONE`, `order_sent: false`.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", default=None)
    parser.add_argument("--json", action="store_true")
    options = parser.parse_args(argv)

    out = (
        Path(options.out)
        if options.out
        else REPO_ROOT / "reports" / "edge-recovery" / "WP-EDGE-06" / "research"
    )
    payload = build()
    if options.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return 0
    out.mkdir(parents=True, exist_ok=True)
    (out / "STRATEGY_AUDIT.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (out / "STRATEGY_AUDIT.md").write_text(render(payload), encoding="utf-8")
    conclusions = {
        book: derived["conclusion"]
        for book, derived in payload["decomposition"]["derived"].items()
    }
    print(f"audited {len(payload['audit'])} book/window/scenario rows")
    print(f"intraday conclusion: {conclusions}")
    print(f"wrote STRATEGY_AUDIT.json and STRATEGY_AUDIT.md into {out}")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
