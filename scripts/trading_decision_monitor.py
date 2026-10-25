"""Trading Decision Monitor — read-only PAPER panel (RFC-TAP-OBS-001).

Starts a local, read-only HTTP server that projects the artifacts the autonomous
PAPER runtime already writes (``traces.jsonl``, ``RUN_REPORT.json``,
``heartbeat.json``) into a candlestick chart with decision markers, a reason
timeline and a ``DecisionTrace`` drilldown.

    uv run python scripts/trading_decision_monitor.py
    uv run python scripts/trading_decision_monitor.py --runs-root reports/autonomous-paper --port 8770

What it can never do: place an order, change risk/sizing, enable LIVE, mutate a
strategy or write to a run directory. Only ``GET``/``HEAD`` are served.

Candles come from public OHLCV through the project's existing ``ccxt``
dependency. If the host is offline the API answers ``503 CANDLES_UNAVAILABLE``
and the UI says so; the decision timeline still works because it is built from
persisted evidence, not from market data.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from trading_bot.monitor.api import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
