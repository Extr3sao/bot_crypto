"""WP-EDGE-08 — artefact helpers, so every document in this package is rendered the same way.

Two rules, both learned from earlier work packages:

* **one reading per document.** A JSON artefact is the payload a Markdown document is rendered
  from, never a second computation, so the two cannot disagree;
* **deterministic bytes.** JSON is written with sorted keys and a trailing newline, and a CSV's
  column order is declared, so re-running a script on unchanged inputs produces an identical file
  and a diff that shows nothing.
"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = ["TRADE_COLUMNS", "stamp", "stamp_ms", "write_json", "write_trades_csv"]

TRADE_COLUMNS: tuple[str, ...] = (
    "arm",
    "track",
    "window",
    "scenario",
    "asset",
    "decision_ts_utc",
    "entry_ts_utc",
    "exit_ts_utc",
    "duration_min",
    "regime",
    "market_context",
    "notional",
    "gross",
    "fees",
    "price_costs",
    "net",
    "exit_reason",
    "expected_gross_bps",
    "expected_cost_bps",
    "expected_net_bps",
)


def stamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp_ms(instant_ms: int | float | None) -> str | None:
    if not instant_ms:
        return None
    return datetime.fromtimestamp(float(instant_ms) / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def write_trades_csv(
    path: Path, rows: list[dict[str, Any]], *, extra_columns: tuple[str, ...] = ()
) -> Path:
    """One row per trade, with the columns every trade in this package is read by."""
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = TRADE_COLUMNS + extra_columns
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "arm": row.get("arm"),
                    "track": row.get("track"),
                    "window": row.get("window"),
                    "scenario": row.get("scenario"),
                    "asset": row.get("asset"),
                    "decision_ts_utc": stamp_ms(row.get("decision_ts")),
                    "entry_ts_utc": stamp_ms(row.get("entry_ts")),
                    "exit_ts_utc": stamp_ms(row.get("exit_ts")),
                    "duration_min": row.get("duration_min"),
                    "regime": row.get("regime"),
                    "market_context": row.get("market_context"),
                    "notional": row.get("notional"),
                    "gross": row.get("gross"),
                    "fees": row.get("fees"),
                    "price_costs": row.get("price_costs"),
                    "net": row.get("net"),
                    "exit_reason": row.get("exit_reason"),
                    "expected_gross_bps": row.get("expected_gross_bps"),
                    "expected_cost_bps": row.get("expected_cost_bps"),
                    "expected_net_bps": row.get("expected_net_bps"),
                    **{column: row.get(column) for column in extra_columns},
                }
            )
    return path
