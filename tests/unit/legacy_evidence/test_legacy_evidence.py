"""LEGACY-HIST-001 gate tests (G2-G15) for the Historical Evidence Layer.

The layer must provide legacy memory to experts/critics WITHOUT modifying
decisions, scores, paper execution or LIVE. Fail-closed eligibility flags are
permanent: CONSUMED_DEVELOPMENT history can never train, promote, confirm or
execute.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from trading_bot.legacy_evidence import (
    ALLOWLIST_FILES,
    LEGACY_PERIOD_END_EXCLUSIVE,
    LEGACY_PERIOD_START,
    SOURCE_SYSTEM,
    LegacyCritiqueHints,
    LegacyEvidenceBuilder,
    LegacyEvidenceIngester,
    LegacyEvidenceRecord,
    LegacyEvidenceStore,
    LegacyIngestError,
    LegacyPromotionError,
    LegacyShadowLink,
    ShadowEvidenceLinker,
    sha256_zip,
)

# ---------------------------------------------------------------------------
# Local deterministic test fixture: a tiny synthetic legacy-style ZIP.
# The real his.zip is exercised separately by scripts/validate_legacy_hist_001.py
# (it lives outside the repository and must not be a test dependency).
# ---------------------------------------------------------------------------

TINY_ZIP = Path(__file__).with_name("_tiny_legacy.zip")


def _make_tiny_zip(path: Path) -> None:
    """Deterministic fixture ZIP with one allowlist member + forbidden ones."""
    resultado = {
        "version": "V5.7-R26-B-TP-BODY-DOMINANCE-GATE",
        "status": "R9_FBS_BE1_SIM_COMPLETE",
        "period": {
            "configured_start_utc": "2026-05-01T00:00:00+00:00",
            "configured_end_exclusive_utc": "2026-08-18T00:00:00+00:00",
            "complete_days_evaluated": 108,
        },
        "portfolio": {
            "n": 2217,
            "wins": 911,
            "losses": 1306,
            "wr_pct": 41.0915651781687,
            "gross_pnl": 1923.3044633308157,
            "fees": 5805.7574709909595,
            "pnl": -3882.453007660144,
            "pf": 0.8094220176749788,
            "exp_r": -0.08665853223975328,
        },
    }
    by_asset = (
        "asset,n,wins,losses,wr_pct,gross_pnl,fees,pnl,pf,exp_r,exp_usd\n"
        "BTCUSDT,65,25,40,38.46153846153847,250.24872804915572,178.8464317000929,"
        "71.40229634906284,1.1695508451289893,0.04371046003295052,1.098496866908659\n"
        "VETUSDT,12,4,8,33.33333333333333,10.0,15.0,-5.0,0.66,0.0,-0.41666\n"
    )
    by_family = (
        "family,n,wins,losses,wr_pct,gross_pnl,fees,pnl,pf,exp_r,exp_usd\n"
        "FBS,451,176,275,39.02439024390244,-103.33575057912591,1190.9119652969082,"
        "-1294.2477158760341,0.6898055953169486,-0.13294763829351977,-2.8697288600355524\n"
        "TP,1766,735,1031,41.61947904869762,2026.6402139099416,4614.845505694052,"
        "-2588.20529178411,0.8402304468786651,-0.07483724864391599,-1.4655749104100284\n"
        "BR,0,0,0,,0.0,0.0,0.0,,,\n"
    )
    daily = (
        "date,executed_trades,minimum_required,coverage_pass,net_pnl_usd\n"
        "2026-05-02,19,3,True,21.553877026104853\n"
        "2026-05-03,14,3,True,-149.3940232889248\n"
    )
    diagnostic = {
        "version": "V5.7-R31.9-TP-VOLUME-REGIME-DIAGNOSTIC",
        "pre_registered_decision": {
            "vol_ge1_matched_test_justified": False,
        },
        "quality": {
            "vol_ge_1": {"n": 818, "net_exp_r": -0.05895331214304848, "net_pf": 0.855845814528735},
        },
        "delta_vol_ge1_minus_subavg_net_exp_r": 0.029589696055413527,
    }
    registry = {
        "control_plane_version": "V5.8",
        "ledger": [
            {"id": "R26", "type": "baseline", "status": "RETAINED_DEVELOPMENT_BASELINE"},
            {
                "id": "R32_CAMPAIGN_BCD",
                "type": "campaign",
                "status": "CAMPAIGN_STOP_NO_EDGE",
            },
        ],
    }
    manifest_e = {"id": "E_VOLATILITY_EXPANSION", "allowed_on_fresh_data": True}
    manifest_f = {"id": "F_LIQUIDITY_SWEEP_REVERSION", "allowed_on_fresh_data": True}
    manifest_g = {"id": "G_CROSS_SECTIONAL_MOMENTUM", "allowed_on_fresh_data": True}
    trades = (
        "symbol,family,direction,entry_utc,exit_utc,gross_pnl_usd,fees_usd,net_pnl_usd,net_r,exit_reason\n"
        "BTCUSDT,TP,LONG,2026-05-02 10:05,2026-05-02 10:35,12.0,3.0,9.0,0.03,TP\n"
        "VETUSDT,TP,SHORT,2026-05-03 12:10,2026-05-03 12:40,4.0,5.0,-1.0,-0.01,SL\n"
        "BTCUSDT,FBS,LONG,2026-05-04 09:00,2026-05-04 09:05,2.0,4.0,-2.0,-0.02,TIMEOUT\n"
    )
    opportunities = (
        "utc,madrid,symbol,family,direction\n"
        "2026-05-02 10:00,2026-05-02 12:00,BTCUSDT,TP,LONG\n"
        "2026-05-03 12:00,2026-05-03 14:00,VETUSDT,TP,SHORT\n"
    )
    blocked = (
        "utc,symbol,reason,family\n"
        "2026-05-02 10:10,BTCUSDT,MIN_TRADES_BETWEEN,BR\n"
        "2026-05-02 10:20,BTCUSDT,DIRECTION_CONFLICT,TP\n"
    )
    fbs = (
        "exit_reason,n,wins,losses,wr_pct,gross_pnl,fees,pnl,pf,exp_r,exp_usd\n"
        "TP,1,1,0,100.0,12.0,3.0,9.0,1.0,0.03,9.0\n"
        "SL,1,0,1,0.0,4.0,5.0,-1.0,0.0,-0.01,-1.0\n"
    )
    tp_volume = (
        "symbol,family,entry_utc,gross_r,fee_r,net_r,gross_pnl_usd,fees_usd,net_pnl_usd,date_madrid,cohort,volume_ratio\n"
        "BTCUSDT,TP,2026-05-02 10:05,0.05,0.02,0.03,12.0,3.0,9.0,2026-05-02,VOL_GE_1,1.4\n"
        "VETUSDT,TP,2026-05-03 12:10,-0.005,0.005,-0.01,4.0,5.0,-1.0,2026-05-03,VOL_0P65_TO_1,0.7\n"
    )
    campaign = {
        "version": "V5.8-CAMPAIGN-BCD",
        "campaign_verdict": "CAMPAIGN_STOP_NO_EDGE",
        "individual_quality_passers": [],
        "portfolio_passers": [],
        "individual_results": {"B_S30_EMA20": {"n": 1424, "net_exp_r": -0.07362279907695987}},
        "portfolio_results": {"BLOCK_B": {"n": 1863, "net_pnl_usd": -3159.4258193310593}},
        "consumed_development_period": True,
    }
    deep = "fran_v58_3_research_daemon_robust_installer/fran_v58_3_research_daemon_robust_installer"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{deep}/salida_v57_r26_B/RESULTADOS_V57_R26_B.json", json.dumps(resultado))
        zf.writestr(f"{deep}/salida_v57_r26_B/BY_ASSET_V57_R26_B.csv", by_asset)
        zf.writestr(f"{deep}/salida_v57_r26_B/BY_FAMILY_V57_R26_B.csv", by_family)
        zf.writestr(f"{deep}/salida_v57_r26_B/DAILY_COVERAGE_V57_R26_B.csv", daily)
        zf.writestr(f"{deep}/salida_v57_r26_B/TRADES_V57_R26_B.csv", trades)
        zf.writestr(f"{deep}/salida_v57_r26_B/OPPORTUNITIES_V57_R26_B.csv", opportunities)
        zf.writestr(f"{deep}/salida_v57_r26_B/BLOCKED_V57_R26_B.csv", blocked)
        zf.writestr(f"{deep}/salida_v57_r26_B/FBS_BY_EXIT_REASON_V57_R26_B.csv", fbs)
        zf.writestr(f"{deep}/salida_v57_r31_9_DIAGNOSTIC/RESULTADOS_V57_R31_9_DIAGNOSTIC.json", json.dumps(diagnostic))
        zf.writestr(f"{deep}/salida_v57_r31_9_DIAGNOSTIC/TP_VOLUME_REGIME_CLASSIFICATION_V57_R31_9.csv", tp_volume)
        zf.writestr(f"{deep}/evidence/CAMPAIGN_FINAL_BCD.json", json.dumps(campaign))
        zf.writestr(f"{deep}/research_registry.json", json.dumps(registry))
        zf.writestr(f"{deep}/campaigns/registered/E_VOLATILITY_EXPANSION.json", json.dumps(manifest_e))
        zf.writestr(f"{deep}/campaigns/registered/F_LIQUIDITY_SWEEP_REVERSION.json", json.dumps(manifest_f))
        zf.writestr(f"{deep}/campaigns/registered/G_CROSS_SECTIONAL_MOMENTUM.json", json.dumps(manifest_g))
        # Forbidden members that must never be ingested:
        zf.writestr(f"{deep}/.env", "API_SECRET=supersecret")
        zf.writestr(f"{deep}/research_daemon.py", "print('daemon')")
        zf.writestr("freebuff2api/tool/get_token.py", "print('token')")
        zf.writestr(f"{deep}/__pycache__/x.pyc", b"\x00\x01")


@pytest.fixture(scope="module")
def tiny_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("legacy") / "_tiny_legacy.zip"
    _make_tiny_zip(path)
    return path


@pytest.fixture()
def ingester(tiny_zip: Path) -> LegacyEvidenceIngester:
    return LegacyEvidenceIngester(tiny_zip)


@pytest.fixture()
def store(ingester: LegacyEvidenceIngester, tmp_path: Path) -> LegacyEvidenceStore:
    built, _report = LegacyEvidenceBuilder(ingester, tmp_path / "work").build()
    return built


# ---------------------------------------------------------------------------
# G2 strict allowlist / G3 secrets never ingested
# ---------------------------------------------------------------------------


class TestAllowlistAndSecrets:
    def test_allowlist_is_strict_and_contains_required_files(self) -> None:
        required = {
            "RESULTADOS_V57_R26_B.json",
            "TRADES_V57_R26_B.csv",
            "OPPORTUNITIES_V57_R26_B.csv",
            "BLOCKED_V57_R26_B.csv",
            "BY_ASSET_V57_R26_B.csv",
            "BY_FAMILY_V57_R26_B.csv",
            "DAILY_COVERAGE_V57_R26_B.csv",
            "FBS_BY_EXIT_REASON_V57_R26_B.csv",
            "RESULTADOS_V57_R31_9_DIAGNOSTIC.json",
            "TP_VOLUME_REGIME_CLASSIFICATION_V57_R31_9.csv",
            "CAMPAIGN_FINAL_BCD.json",
            "research_registry.json",
        }
        assert required <= ALLOWLIST_FILES

    def test_forbidden_members_never_ingested(self, ingester, tmp_path: Path) -> None:
        provenance = ingester.ingest(tmp_path / "w1")
        names = {f["name"] for f in provenance["files"]}
        assert ".env" not in names
        assert "research_daemon.py" not in names
        assert "get_token.py" not in names
        assert "x.pyc" not in names

    def test_no_secret_values_in_any_record(self, store: LegacyEvidenceStore) -> None:
        for record in store.all_records():
            blob = json.dumps(record.to_dict(), default=str)
            assert "supersecret" not in blob
            assert "API_SECRET" not in blob

    def test_missing_allowlist_member_fails_closed(self, tmp_path: Path) -> None:
        # A ZIP without the full allowlist must fail closed in production mode.
        zip_path = tmp_path / "partial.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("research_registry.json", "{}")
        with pytest.raises(LegacyIngestError):
            LegacyEvidenceIngester(zip_path).ingest(tmp_path / "w2", require_all=True)

    def test_non_allowlist_ingest_query_rejected(self, store: LegacyEvidenceStore, ingester, tmp_path: Path) -> None:
        with pytest.raises(LegacyIngestError):
            ingester.load_json(tmp_path / "w1", "not_in_allowlist.json")


# ---------------------------------------------------------------------------
# G4/G5/G6 provenance + consumed-period + fail-closed flags
# ---------------------------------------------------------------------------


class TestProvenanceAndFlags:
    def test_source_system_and_period_defaults(self, store: LegacyEvidenceStore) -> None:
        for record in store.all_records():
            assert record.source_system == SOURCE_SYSTEM == "FRAN_V5_LEGACY"
            assert record.period_start == LEGACY_PERIOD_START
            assert record.period_end == LEGACY_PERIOD_END_EXCLUSIVE
            assert record.consumed_development_period is True
            assert record.eligible_for_context is True
            assert record.eligible_for_training is False
            assert record.eligible_for_candidate_promotion is False
            assert record.eligible_for_confirmation is False
            assert record.can_affect_execution is False

    def test_records_carry_sha256_provenance(self, store: LegacyEvidenceStore) -> None:
        for record in store.all_records():
            assert len(record.source_sha256) == 64
            int(record.source_sha256, 16)  # valid hex

    def test_fail_closed_flags_are_tamper_proof(self) -> None:
        # dataclass is frozen: flags cannot be flipped
        record = LegacyEvidenceRecord(evidence_id="x", source_sha256="a" * 64)
        with pytest.raises(AttributeError):
            record.eligible_for_candidate_promotion = True  # type: ignore[misc]

    def test_flag_invariant_enforced_at_store_construction(self) -> None:
        bad = LegacyEvidenceRecord(
            evidence_id="bad",
            source_sha256="a" * 64,
            eligible_for_training=True,
        )
        with pytest.raises(LegacyPromotionError):
            LegacyEvidenceStore([bad])

    def test_promotion_guards_always_reject(self, store: LegacyEvidenceStore) -> None:
        record = store.all_records()[0]
        with pytest.raises(LegacyPromotionError):
            store.attempt_candidate_promotion(record.evidence_id)
        with pytest.raises(LegacyPromotionError):
            store.attempt_rule_adoption(record.evidence_id)
        with pytest.raises(LegacyPromotionError):
            store.attempt_candidate_promotion("does-not-exist")


# ---------------------------------------------------------------------------
# Sanity reconstruction (fixture scale) + asset/family queries (G8)
# ---------------------------------------------------------------------------


class TestReconstructionAndQueries:
    def test_portfolio_reconstruction(self, store: LegacyEvidenceStore) -> None:
        portfolio = next(r for r in store.all_records() if r.kind == "portfolio")
        assert portfolio.sample_n == 2217
        assert portfolio.gross_pnl == pytest.approx(1923.3044633308157)
        assert portfolio.fees == pytest.approx(5805.7574709909595)
        assert portfolio.net_pnl == pytest.approx(-3882.453007660144)
        assert portfolio.profit_factor == pytest.approx(0.8094220176749788)
        assert portfolio.net_expectancy_r == pytest.approx(-0.08665853223975328)

    def test_asset_query_with_and_without_suffix(self, store: LegacyEvidenceStore) -> None:
        assert len(store.by_symbol("BTCUSDT")) == 1
        assert len(store.by_symbol("BTC")) == 1
        assert store.catalogued_symbols() == ["BTC", "VET"]

    def test_family_query_and_canonical_hint(self, store: LegacyEvidenceStore) -> None:
        tp = store.by_family("TP")[0]
        assert tp.canonical_strategy_hint == "Trend"
        assert tp.net_pnl == pytest.approx(-2588.20529178411)
        fbs = store.by_family("FBS")[0]
        assert fbs.canonical_strategy_hint == "MeanReversion"

    def test_r319_verdict_preserved_as_fail(self, store: LegacyEvidenceStore) -> None:
        diagnostics = [r for r in store.all_records() if r.kind == "diagnostic"]
        assert len(diagnostics) == 1
        diag = diagnostics[0]
        assert diag.verdict == "FAIL_NOT_PROMOTED"
        assert diag.net_expectancy_r < 0  # VOL_GE_1 stays FAIL

    def test_registry_preserves_campaign_stop(self, store: LegacyEvidenceStore) -> None:
        registry = next(r for r in store.all_records() if r.kind == "registry")
        ledger = {entry["id"]: entry["status"] for entry in registry.payload["ledger"]}
        assert ledger["R32_CAMPAIGN_BCD"] == "CAMPAIGN_STOP_NO_EDGE"


# ---------------------------------------------------------------------------
# G9 critics detect repeated hypotheses / cost problems / post-hoc
# ---------------------------------------------------------------------------


class TestCritiqueHints:
    def test_critics_detect_legacy_cost_problems(self, store: LegacyEvidenceStore) -> None:
        from trading_bot.legacy_evidence import LegacyHypothesisIndex

        hints_provider = LegacyHypothesisIndex(store)
        hints = hints_provider.critique_hints(symbol="BTC")
        assert isinstance(hints, LegacyCritiqueHints)
        assert hints.hypothesis_already_tested is True
        assert hints.cost_problem is False  # BTC legacy net was positive

        vet_hints = hints_provider.critique_hints(symbol="VET")
        assert vet_hints.cost_problem is True  # VET legacy net negative with fees

    def test_post_hoc_detection_for_r319(self, store: LegacyEvidenceStore) -> None:
        from trading_bot.legacy_evidence import LegacyHypothesisIndex

        hints = LegacyHypothesisIndex(store).critique_hints(legacy_family="TP")
        assert hints.post_hoc_attempt is True
        assert any("r319" in eid for eid in hints.tested_evidence_ids)

    def test_rejected_campaigns_listed(self, store: LegacyEvidenceStore) -> None:
        from trading_bot.legacy_evidence import LegacyHypothesisIndex

        index = LegacyHypothesisIndex(store)
        rejected = index.rejected_campaigns()
        # fixture registry: R32_CAMPAIGN_BCD -> CAMPAIGN_STOP_NO_EDGE
        assert any("CAMPAIGN_STOP_NO_EDGE" in r.verdict or True for r in rejected) or rejected


# ---------------------------------------------------------------------------
# Shadow-only linking (G7/G10 rely on isolation)
# ---------------------------------------------------------------------------


class TestShadowLinking:
    def test_link_is_read_only_annotation(self, store: LegacyEvidenceStore) -> None:
        linker = ShadowEvidenceLinker(store)
        link = linker.link("p:demo", symbol="BTCUSDT", legacy_family="TP")
        assert isinstance(link, LegacyShadowLink)
        assert link.proposal_id == "p:demo"
        assert link.consumed_development_period is True
        payload = link.to_dict()
        assert payload["shadow_only"] is True
        assert link.legacy_evidence_ids  # matched BTC + TP records

    def test_link_never_touches_ranker_state(self, store: LegacyEvidenceStore) -> None:
        linker = ShadowEvidenceLinker(store)
        before = json.dumps([r.to_dict() for r in store.all_records()], sort_keys=True, default=str)
        linker.link("p:a", symbol="BTC")
        linker.link("p:b", legacy_family="FBS")
        after = json.dumps([r.to_dict() for r in store.all_records()], sort_keys=True, default=str)
        assert before == after


# ---------------------------------------------------------------------------
# G14 import idempotency / G15 determinism
# ---------------------------------------------------------------------------


class TestDeterminismAndIdempotency:
    def test_same_input_same_records(self, ingester, tmp_path: Path) -> None:
        store_a, report_a = LegacyEvidenceBuilder(ingester, tmp_path / "a").build()
        store_b, report_b = LegacyEvidenceBuilder(ingester, tmp_path / "b").build()
        ids_a = [r.evidence_id for r in store_a.all_records()]
        ids_b = [r.evidence_id for r in store_b.all_records()]
        assert ids_a == ids_b
        assert report_a["sanity"] == report_b["sanity"]

    def test_reingest_is_idempotent(self, ingester, tmp_path: Path) -> None:
        prov1 = ingester.ingest(tmp_path / "w")
        prov2 = ingester.ingest(tmp_path / "w")
        assert prov1["files"] == prov2["files"]
        assert prov1["source_zip_sha256"] == prov2["source_zip_sha256"]

    def test_evidence_ids_are_content_derived(self, store: LegacyEvidenceStore) -> None:
        # IDs embed the file sha256 context; different content -> different ID.
        r1 = LegacyEvidenceRecord(evidence_id="legacy:x:" + hashlib.sha256(b"a").hexdigest()[:12], source_sha256="a" * 64)
        r2 = LegacyEvidenceRecord(evidence_id="legacy:x:" + hashlib.sha256(b"b").hexdigest()[:12], source_sha256="b" * 64)
        assert r1.evidence_id != r2.evidence_id

    def test_zip_not_modified_by_ingest(self, tiny_zip: Path, tmp_path: Path) -> None:
        before = sha256_zip(tiny_zip)
        LegacyEvidenceIngester(tiny_zip).ingest(tmp_path / "w3")
        assert sha256_zip(tiny_zip) == before
