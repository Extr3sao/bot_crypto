"""LEGACY-HIST-001 runtime gates: G7, G8, G10, G11, G12, G13.

Proves the Historical Evidence Layer is observation-only: identical
MetaRanker scores and identical paper-broker behavior with the layer ON or
OFF, fail-closed promotion attempts, and PIT/no-lookahead invariants.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_bot.legacy_evidence import (
    LegacyEvidenceBuilder,
    LegacyEvidenceIngester,
    LegacyHypothesisIndex,
    LegacyPromotionError,
    ShadowEvidenceLinker,
)
from trading_bot.multi_agent.contracts import TraceContext, TradeDirection, TradeProposal
from trading_bot.multi_agent.opportunity import MetaRanker, Opportunity
from trading_bot.strategies.types import Signal

CLOCK = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
TRACE = TraceContext(
    run_id="g-run",
    trace_id="g-trace",
    correlation_id="g-corr",
    causation_id="g-cause",
)


@pytest.fixture(scope="module")
def real_store(tmp_path_factory: pytest.TempPathFactory):
    """Build the store from the REAL his.zip (skip if unavailable)."""
    try:
        ingester = LegacyEvidenceIngester()
    except Exception:
        pytest.skip("his.zip source not available")
    work = tmp_path_factory.mktemp("legacy-real") / "flat"
    store, _report = LegacyEvidenceBuilder(ingester, work).build()
    return store


def _proposal(proposal_id: str, *, confidence: float = 0.8) -> TradeProposal:
    return TradeProposal(
        schema_version="ma-3-v1",
        proposal_id=proposal_id,
        run_id=TRACE.run_id,
        trace_id=TRACE.trace_id,
        asset="SOL",
        direction=TradeDirection.LONG,
        strategy="momentum",
        timeframe="5m",
        regime="TREND_UP",
        evidence_refs=(f"ev:{proposal_id}",),
        invalidation="structural stop",
        confidence=confidence,
        data_time=CLOCK,
        created_at=CLOCK,
        expires_at=CLOCK.replace(minute=CLOCK.minute + 15),
        trace=TRACE,
    )


# ---------------------------------------------------------------------------
# G7: MetaRanker scores identical with layer ON/OFF
# ---------------------------------------------------------------------------


class TestMetaRankerInvariance:
    def test_scores_identical_layer_on_off(self, real_store) -> None:
        proposal = _proposal("p:g7", confidence=0.83)
        opportunity = Opportunity(
            proposal=proposal,
            evidence_refs=proposal.evidence_refs,
            source_agent_id="strategy-expert-momentum",
            source_agent_version="1.0.0",
        )
        ranker = MetaRanker()
        baseline = ranker.score(opportunity, assessment=None, conflicted=False)
        # Layer ON: a shadow linker produces provenance for the same proposal,
        # but the ranker receives exactly the same inputs (links are not part
        # of scoring inputs).
        linker = ShadowEvidenceLinker(real_store)
        link = linker.link("p:g7", symbol="SOL", legacy_family="TP")
        assert link.legacy_evidence_ids  # layer produced provenance
        with_layer = ranker.score(opportunity, assessment=None, conflicted=False)
        assert with_layer.score == baseline.score
        assert with_layer.score_components == baseline.score_components

    def test_no_metaranker_or_board_api_accepts_legacy_records(self) -> None:
        # Structural proof: MetaRanker.score and Opportunity carry no field or
        # parameter that could accept a LegacyEvidenceRecord / ShadowLink.
        import inspect

        from trading_bot.multi_agent.opportunity import OpportunityBoard, RankedOpportunity

        ranker_params = inspect.signature(MetaRanker.score).parameters
        assert "legacy" not in {p.lower() for p in ranker_params}
        board_methods = [m for m in dir(OpportunityBoard) if not m.startswith("_")]
        assert not any("legacy" in m.lower() for m in board_methods)
        ranked_fields = set(RankedOpportunity.__dataclass_fields__)  # type: ignore[attr-defined]
        assert not any("legacy" in f.lower() for f in ranked_fields)


@pytest.fixture(scope="module")
def _bind_store(real_store):
    """Alias fixture marking classes that require the real legacy store."""
    return real_store


# ---------------------------------------------------------------------------
# G8: experts can query legacy evidence (asset + family mechanisms)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_bind_store")
class TestExpertQueries:
    def test_asset_expert_query_btc_eth_sol(self, real_store) -> None:
        index = LegacyHypothesisIndex(real_store)
        for asset in ("BTC", "ETH", "SOL"):
            records = index.for_asset(asset)
            assert records, f"no legacy evidence for {asset}"
            assert all(r.eligible_for_context for r in records)

    def test_other_27_assets_catalogued_not_agentic(self, real_store) -> None:
        catalogued = real_store.catalogued_symbols()
        assert len(catalogued) == 30
        assert {"BTC", "ETH", "SOL"} <= set(catalogued)
        assert "VET" in catalogued and "WIF" in catalogued
        # Catalogued != agents: the layer exposes data only, no new agents.

    def test_strategy_expert_query_by_family(self, real_store) -> None:
        index = LegacyHypothesisIndex(real_store)
        tp = index.for_family("TP")
        assert tp and tp[0].canonical_strategy_hint == "Trend"
        fbs = index.for_family("FBS")
        assert fbs and fbs[0].canonical_strategy_hint == "MeanReversion"


# ---------------------------------------------------------------------------
# G9 covered in test_legacy_evidence.py (critique hints).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# G10: paper execution identical with layer ON/OFF
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_bind_store")
class TestPaperExecutionInvariance:
    def test_broker_order_count_identical(self, real_store) -> None:
        from trading_bot.paper.broker import PaperBroker

        def run_broker(with_layer: bool) -> int:
            broker = PaperBroker(equity=10_000.0)
            if with_layer:
                # Layer ON: produce shadow provenance for the same signal.
                ShadowEvidenceLinker(real_store).link("p:g10-on", symbol="SOL")
            signal = Signal(
                symbol="SOL/USDT",
                side="buy",
                strategy_name="momentum",
                timeframe="5m",
                confidence=0.8,
                price=100.0,
                stop_loss_pct=0.05,
                take_profit_pct=0.10,
            )
            result = broker.execute_signal(signal)
            return 1 if result is not None else 0

        assert run_broker(with_layer=False) == run_broker(with_layer=True)

    def test_demo_run_counts_unchanged_by_layer_presence(self) -> None:
        # The legacy summary is attached AFTER the trading loop; the report's
        # trading counters must not depend on it. Structural check:
        import inspect

        from trading_bot.demo import paper_multi_agent as demo

        src = inspect.getsource(demo.run_fixture_demo)
        attach_pos = src.find("_attach_legacy_evidence_summary")
        reconcile_pos = src.find("_reconcile(")
        write_pos = src.find("_write_reports(")
        assert 0 < reconcile_pos < attach_pos < write_pos


# ---------------------------------------------------------------------------
# G11: PIT / no-lookahead invariants of the layer
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_bind_store")
class TestPitInvariants:
    def test_legacy_period_strictly_before_any_current_decision(self, real_store) -> None:
        for record in real_store.all_records():
            assert record.period_end <= datetime(2026, 8, 18, tzinfo=UTC)
            assert record.period_start >= datetime(2026, 5, 1, tzinfo=UTC)

    def test_no_legacy_record_can_be_scheduled_in_the_future(self, real_store) -> None:
        # The layer exposes no scheduling capability: records are immutable
        # historical aggregates with a fixed, closed period.

        from trading_bot.legacy_evidence import LegacyEvidenceRecord

        public = [m for m in dir(LegacyEvidenceRecord) if not m.startswith("_")]
        assert not any("schedule" in m or "ingest" in m for m in public)

    def test_records_declare_no_execution_capability(self, real_store) -> None:
        for record in real_store.all_records():
            assert record.can_affect_execution is False


# ---------------------------------------------------------------------------
# G12/G13: explicit rejection of legacy-driven promotion
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_bind_store")
class TestPromotionRejects:
    def test_g12_vet_wif_promotion_rejected(self, real_store) -> None:
        vet = real_store.by_symbol("VET")
        wif = real_store.by_symbol("WIF")
        assert vet and wif  # both catalogued with per-asset legacy PnL
        for record in (*vet, *wif):
            with pytest.raises(LegacyPromotionError):
                real_store.attempt_candidate_promotion(record.evidence_id)

    def test_g13_r319_volume_rule_conversion_rejected(self, real_store) -> None:
        diagnostics = [r for r in real_store.all_records() if r.kind == "diagnostic"]
        assert len(diagnostics) == 1
        diag = diagnostics[0]
        assert diag.verdict == "FAIL_NOT_PROMOTED"
        assert diag.payload["candidate"] == "VOL_GE_1"
        with pytest.raises(LegacyPromotionError):
            real_store.attempt_rule_adoption(diag.evidence_id)
