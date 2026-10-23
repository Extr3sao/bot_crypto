"""ARP-002 §3 — determinism, contract and ARP-001 compatibility tests.

TEST_TARGET == RUNTIME_TARGET: these tests drive
``trading_bot.research.strategy_failure_diagnostics`` directly, the same module the
campaign driver runs. Nothing here depends on the gitignored ``reports/`` corpus;
the fixture is built in ``tmp_path``.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.strategy_failure_diagnostics import (  # noqa: E402
    DiagnosticsInputs,
    canonical_payload,
    compute_diagnostics,
    write_document,
)

TRADE_FIELDS = [
    "family",
    "window",
    "asset",
    "side",
    "entry_ts",
    "exit_ts",
    "duration_min",
    "entry",
    "exit",
    "reason",
    "mfe_pct",
    "mae_pct",
    "notional",
    "gross",
    "fees",
    "net",
]
START_TS = 1_772_323_200_000
STEP_MS = 300_000


def _bars(n: int = 40) -> list[dict[str, float]]:
    out = []
    price = 100.0
    for i in range(n):
        price += 0.1 if i % 3 else -0.05
        out.append(
            {
                "ts": START_TS + i * STEP_MS,
                "open": price - 0.02,
                "high": price + 0.05,
                "low": price - 0.05,
                "close": price,
                "volume": 10.0 + i,
            }
        )
    return out


def _fixture(root: Path) -> DiagnosticsInputs:
    corpus = root / "corpus"
    corpus.mkdir()
    (corpus / "BTCUSDT_W1_2026-03.json").write_text(json.dumps(_bars()), encoding="utf-8")
    results = root / "results"
    results.mkdir()
    (results / "MULTI_FAMILY_RESULTS_trend.json").write_text(
        json.dumps(
            {"trend": {"BASE": {"totals": {"net": 1.0, "trades": 3}, "DEV_W1_W4": {"net": 1.0}}}}
        ),
        encoding="utf-8",
    )
    trades = root / "trades.csv"
    with trades.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=TRADE_FIELDS)
        writer.writeheader()
        for k in range(6):
            writer.writerow(
                {
                    "family": "trend" if k % 2 == 0 else "momentum",
                    "window": "W1_2026-03",
                    "asset": "BTC",
                    "side": "buy",
                    "entry_ts": START_TS + k * STEP_MS,
                    "exit_ts": START_TS + (k + 4) * STEP_MS,
                    "duration_min": 20.0,
                    "entry": 100.0 + k,
                    "exit": 100.5 + k,
                    "reason": "tp" if k % 3 == 0 else "stop",
                    "mfe_pct": 0.5,
                    "mae_pct": 0.2,
                    "notional": 500.0,
                    "gross": 2.5 if k % 2 == 0 else -1.5,
                    "fees": 0.5,
                    "net": 2.0 if k % 2 == 0 else -2.0,
                }
            )
    return DiagnosticsInputs(
        trades=trades, corpus=corpus, results_dir=results, out=root / "out.json"
    )


def test_determinism_hash_run1_equals_run2(tmp_path: Path) -> None:
    inputs = _fixture(tmp_path)
    doc1 = compute_diagnostics(inputs, enrich=True)
    doc2 = compute_diagnostics(inputs, enrich=True)
    hash1 = write_document(doc1, tmp_path / "r1.json")
    hash2 = write_document(doc2, tmp_path / "r2.json")
    assert hash1 == hash2
    assert canonical_payload(doc1) == canonical_payload(doc2)


def test_contract_fields_present_in_enriched_schema(tmp_path: Path) -> None:
    doc = compute_diagnostics(_fixture(tmp_path), enrich=True)
    assert doc["schema_version_document"] == "arp002-strategy-failure-diagnostics-v2"
    fam = doc["families"]["trend"]
    required = {
        "signals",
        "eligible_signals",
        "drawdown_bps",
        "by_timeframe",
        "by_asset",
        "by_regime",
        "forward_returns",
        "cost_stress",
        "concentration",
        "expectancy_gross_bps",
        "expectancy_net_bps",
        "win_rate",
        "avg_win_usd",
        "avg_loss_usd",
        "profit_factor",
        "payoff",
        "avg_mfe_pct",
        "avg_mae_pct",
        "avg_duration_min",
        "signal_ledger_semantics",
    }
    assert required <= set(fam)
    assert set(fam["forward_returns"]) == {"+1bars", "+3bars", "+6bars", "+12bars", "+24bars"}
    assert set(fam["cost_stress"]) == {"0.5x", "1.0x", "1.25x", "1.5x", "2.0x"}


def test_base_schema_has_no_enrichment_keys(tmp_path: Path) -> None:
    doc = compute_diagnostics(_fixture(tmp_path), enrich=False)
    assert doc["schema_version"] == "arp001-strategy-failure-diagnostics-v1"
    assert "schema_version_document" not in doc
    assert "signals" not in doc["families"]["trend"]


def test_module_is_not_imported_by_runtime() -> None:
    """The diagnostic must stay outside runtime execution authority (§1)."""
    runtime = REPO / "src/trading_bot/autonomous/runtime.py"
    assert "strategy_failure_diagnostics" not in runtime.read_text(encoding="utf-8")
