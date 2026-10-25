"""G-7: the canonical PAPER stack consumes a replay capture and survives restart."""

from __future__ import annotations

import asyncio
from pathlib import Path

from scripts.audit.g7_real_paper import _run_replay, _settings

REPO = Path(__file__).resolve().parents[2]
BASE = 1_792_900_000_000
TF_MS = 300_000


def _bars(asset: str, count: int = 140) -> list[list[float]]:
    symbol_bias = {"BTC": 0.0, "ETH": 30.0, "SOL": 60.0}[asset]
    return [
        [
            BASE + index * TF_MS,
            100.0 + symbol_bias + index,
            101.0 + symbol_bias + index,
            99.0 + symbol_bias + index,
            100.5 + symbol_bias + index,
            10.0,
        ]
        for index in range(count)
    ]


def _capture() -> dict[str, object]:
    return {
        "schema_version": "g7-public-capture/v1",
        "provider": "binance-public-rest",
        "timeframe": "5m",
        "captured_at_ms": BASE + 200 * TF_MS,
        "symbols": {
            f"{asset}/USDT": {
                "bars": _bars(asset),
                "received_at_ms": BASE + 200 * TF_MS,
                "quote": {"volume_24h_usdt": 50_000_000.0, "spread_bps": 1.0},
            }
            for asset in ("BTC", "ETH", "SOL")
        },
    }


def test_replay_is_no_trade_and_restart_does_not_duplicate(tmp_path) -> None:
    capture = _capture()
    assets = ["BTC", "ETH", "SOL"]
    result = asyncio.run(
        _run_replay(
            capture=capture,
            settings=_settings(assets, "5m"),
            out_dir=tmp_path,
            ledger_path=REPO / "config" / "strategy_admission.json",
            assets=assets,
            timeframe="5m",
        )
    )

    assert len(result["sessions"]) == 3
    assert result["blocked"] == []
    assert all(session["orders_created"] == 0 for session in result["sessions"])
    assert all(session["cycle"]["router_no_trade"] == 3 for session in result["sessions"])
    assert all(
        session["broker_calls"] == {"execute_signal": 0, "close_position": 0}
        for session in result["sessions"]
    )
    assert all(snapshot["validation_status"] == "OK" for snapshot in result["snapshots"])
    assert result["restart"] is not None
    assert result["restart"]["reconciliation"]["status"] == "RECOVERED"
    assert result["restart"]["orders_created"] == 0
    assert result["state"]["orders"] == []
    assert result["state"]["sent_intents"] == 0
    assert result["eligibility"]
    assert all(not report["selected"] for report in result["eligibility"])
    assert all(report["counts"].get("NOT_APPLICABLE", 0) == 18 for report in result["eligibility"])
