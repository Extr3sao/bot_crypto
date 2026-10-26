"""RFC-PAPER-008 — a REAL signal must come from a real venue.

The lab used to run the CCXT connector with ``sandbox: true`` and label every
projected row ``source=REAL``. Binance testnet serves synthetic prices and
volumes, so that label was a false claim about the market, not a detail of
configuration. These tests pin the provenance decision at both ends:

* the source reports whether it is sandboxed (unknown provenance is sandbox);
* the runtime refuses to publish REAL from it, and an explicit opt-in publishes
  FAKE instead;
* the run descriptor survives its own shutdown write (provider/venue were lost
  when the stopped descriptor replaced the start-up one).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))


def _load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(f"{name}_provenance_test", REPO / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"{name}_provenance_test"] = module
    spec.loader.exec_module(module)
    return module


def test_a_testnet_source_is_refused_unless_explicitly_allowed() -> None:
    paper = _load_script("autonomous_paper")
    source, mode, refusal = paper.resolve_data_provenance(
        provider="ccxt", sandbox=True, allow_testnet=False
    )
    assert source is None
    assert mode == "TESTNET"
    assert refusal is not None and "sandbox" in refusal


def test_an_explicit_testnet_opt_in_publishes_fake_never_real() -> None:
    paper = _load_script("autonomous_paper")
    source, mode, refusal = paper.resolve_data_provenance(
        provider="ccxt", sandbox=True, allow_testnet=True
    )
    assert (source, mode, refusal) == ("FAKE", "TESTNET", None)


def test_mainnet_public_data_is_real_and_the_fake_provider_is_fake() -> None:
    paper = _load_script("autonomous_paper")
    assert paper.resolve_data_provenance(
        provider="ccxt", sandbox=False, allow_testnet=False
    ) == ("REAL", "MAINNET", None)
    assert paper.resolve_data_provenance(
        provider="fake", sandbox=False, allow_testnet=False
    ) == ("FAKE", "FAKE", None)


def test_the_ccxt_provider_reads_the_public_mainnet_source() -> None:
    """The signal plane is wired to G-7's public REST source, not the hub.

    The Settings invariant keeps the credentialed connector sandboxed in PAPER;
    the market-data plane therefore has to be a separate, public-only client,
    or `source=REAL` would be impossible to earn honestly.
    """
    from trading_bot.config.settings import load_settings

    paper = _load_script("autonomous_paper")
    settings = load_settings(config_dir="config/realdata")
    _factory, source = paper.build_scanner_factory(settings, "ccxt")
    assert source.provider == "binance-public-rest"
    assert source.venue == "binance"
    assert source.sandbox_enabled is False


def test_the_bridge_reports_unknown_provenance_as_sandbox() -> None:
    from trading_bot.market_data.scanner_bridge import HubMarketDataSource

    class _Known:
        sandbox_enabled = True
        exchange_id = "binance"

    class _Unknown:
        exchange_id = "binance"

        @property
        def sandbox_enabled(self) -> bool:
            raise RuntimeError("connector cannot answer")

    assert HubMarketDataSource(_Known(), timeframe="5m").sandbox_enabled is True
    assert HubMarketDataSource(_Unknown(), timeframe="5m").sandbox_enabled is True


def test_the_shutdown_descriptor_does_not_forget_provenance(tmp_path: Path) -> None:
    """The stopped write used to replace the start-up descriptor wholesale."""
    paper = _load_script("autonomous_paper")
    run_dir = tmp_path / "run-descriptor"
    paper.write_run_descriptor(
        run_dir,
        {
            "run_id": "run-descriptor",
            "provider": "ccxt",
            "market_data": "MAINNET",
            "signal_source": "REAL",
            "assets": ["BTC"],
        },
    )
    paper.write_run_descriptor(
        run_dir, {"run_id": "run-descriptor", "state": "STOPPED", "cycles": 3}
    )
    payload = json.loads((run_dir / "PAPER_RUN.json").read_text(encoding="utf-8"))
    assert payload["state"] == "STOPPED"
    assert payload["cycles"] == 3
    assert payload["provider"] == "ccxt"
    assert payload["market_data"] == "MAINNET"
    assert payload["signal_source"] == "REAL"
    assert payload["assets"] == ["BTC"]


def test_the_heartbeat_carries_the_last_bar_and_signal_times() -> None:
    from trading_bot.autonomous.paper_loop import PaperHeartbeat

    report = SimpleNamespace(
        assets=[
            SimpleNamespace(
                asset="BTC",
                market_time_ms=1_793_009_700_000,
                decision_time_ms=1_793_010_005_007,
                risk_state="APPROVED",
            ),
            SimpleNamespace(
                asset="ETH",
                market_time_ms=1_793_009_700_000,
                decision_time_ms=1_793_010_005_007,
                risk_state="APPROVED",
            ),
        ],
        signals={"appended": 2},
        outcomes_resolved=1,
        outcomes_pending=1,
        no_trades=2,
        no_trade_kinds={"NO_TRADE_STRATEGIC": 2},
        shadow_trades=0,
        paper_trades=0,
        runtime_failures=0,
        errors=(),
    )
    beat = PaperHeartbeat.from_cycle(
        run_id="run-times",
        cycle=1,
        report=report,
        started_at_ms=1_793_009_000_000,
        timeframe="5m",
        paper_candidates=(),
    )
    payload = beat.to_dict()
    assert payload["last_market_time_ms"] == 1_793_009_700_000
    assert payload["last_market_time_utc"].startswith("2026-10-26T10:15:00")
    assert payload["last_decision_time_ms"] == 1_793_010_005_007
    assert payload["signals_appended"] == 2
    assert payload["outcomes_resolved"] == 1
    assert payload["outcomes_pending"] == 1
    assert payload["decisions"] == 2
