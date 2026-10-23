"""Asset-universe preflight tests (DEF-AUTO-2, §39).

The defect was silent: an unsupported asset produced a per-cycle
``CONTEXT_ERROR`` instead of stopping the run. These tests pin the three layers
and, more importantly, pin the *reasons* — a preflight that refuses without
saying which layer failed is just a slower version of the same problem.
"""

from __future__ import annotations

import json
from pathlib import Path

from trading_bot.autonomous.universe_preflight import (
    preflight_universe,
    research_universe_from_sources,
)

AGENTS = ("BTC", "ETH", "SOL")


def test_a_fully_supported_universe_passes() -> None:
    support = preflight_universe(
        configured=["BTC", "ETH", "SOL"],
        asset_agents=AGENTS,
        strategy_assets=("BTC", "ETH", "SOL"),
        provider_supported=("BTC", "ETH", "SOL", "BNB"),
    )
    assert support.ok
    assert support.effective == ("BTC", "ETH", "SOL")
    assert support.unsupported == {}
    assert support.blocking_reason is None
    assert support.provider_verified is True


def test_an_asset_without_an_asset_agent_blocks_the_run() -> None:
    """This is the exact DEF-AUTO-2 case: BNB is configured, no agent exists."""
    support = preflight_universe(
        configured=["BTC", "ETH", "SOL", "BNB"],
        asset_agents=AGENTS,
        strategy_assets=("BTC", "ETH", "SOL"),
    )
    assert not support.ok
    assert support.effective == ("BTC", "ETH", "SOL")
    assert "no AssetAgent registered" in support.unsupported["BNB"]
    assert "BNB" in (support.blocking_reason or "")


def test_an_asset_without_research_evidence_is_reported_separately() -> None:
    support = preflight_universe(
        configured=["BTC", "DOGE"],
        asset_agents=("BTC", "DOGE"),
        strategy_assets=("BTC", "ETH", "SOL"),
    )
    assert not support.ok
    assert "no strategy evidence" in support.unsupported["DOGE"]


def test_a_provider_that_does_not_list_the_market_blocks_the_run() -> None:
    support = preflight_universe(
        configured=["BTC"],
        asset_agents=("BTC",),
        strategy_assets=("BTC",),
        provider_supported=("ETH", "SOL"),
    )
    assert not support.ok
    assert "provider does not list" in support.unsupported["BTC"]
    assert support.provider_verified is True


def test_an_unverified_provider_is_reported_and_not_a_failure() -> None:
    """Offline must not read as "unsupported" — nor as "everything is fine"."""
    support = preflight_universe(
        configured=["BTC"],
        asset_agents=("BTC",),
        strategy_assets=("BTC",),
        provider_supported=None,
    )
    assert support.ok
    assert support.provider_supported is None
    assert support.provider_verified is False


def test_an_undeclared_strategy_universe_is_reported_as_undeclared() -> None:
    support = preflight_universe(configured=["BTC"], asset_agents=("BTC",), strategy_assets=None)
    assert support.ok
    assert support.strategy_universe_source == "UNDECLARED"
    assert support.strategy_supported == ()


def test_assets_are_normalised_and_deduplicated() -> None:
    support = preflight_universe(
        configured=[" btc", "BTC", "eth"],
        asset_agents=AGENTS,
    )
    assert support.configured == ("BTC", "ETH")


def test_research_universe_is_read_from_the_ledger_sources(tmp_path: Path) -> None:
    doc = tmp_path / "docs" / "STRATEGY_DISCOVERY_V3_RESULTS.json"
    doc.parent.mkdir(parents=True)
    doc.write_text(json.dumps({"dataset": {"assets": ["BTC", "eth", "SOL"]}}), encoding="utf-8")
    assets, source = research_universe_from_sources(
        [{"path": "docs/STRATEGY_DISCOVERY_V3_RESULTS.json", "sha256": "0" * 64}],
        repo_root=tmp_path,
    )
    assert assets == ("BTC", "ETH", "SOL")
    assert source == "docs/STRATEGY_DISCOVERY_V3_RESULTS.json"


def test_a_missing_artifact_never_invents_a_universe(tmp_path: Path) -> None:
    assets, source = research_universe_from_sources(
        [{"path": "docs/nope.json", "sha256": "0" * 64}], repo_root=tmp_path
    )
    assert assets == ()
    assert source == "UNDECLARED"


def test_the_real_repository_universe_is_serviceable() -> None:
    """The shipped configuration must pass its own preflight."""
    repo_root = Path(__file__).resolve().parents[3]
    from trading_bot.autonomous.admission_ledger import AdmissionLedger

    ledger = AdmissionLedger.load(repo_root / "config" / "strategy_admission.json")
    assets, _source = research_universe_from_sources(ledger.sources, repo_root=repo_root)
    support = preflight_universe(
        configured=["BTC", "ETH", "SOL"],
        asset_agents=AGENTS,
        strategy_assets=assets or None,
    )
    assert support.ok, support.to_dict()
