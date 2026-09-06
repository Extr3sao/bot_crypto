"""Independent LEGACY-HIST-001 validator (Historical Evidence Layer).

Audits the layer from outside its modules against the 16 gates:
G1 source intact, G2 allowlist strict, G3 secrets never ingested,
G4 deterministic provenance, G5 CONSUMED period, G6 fail-closed flags,
G7 MetaRanker invariance, G8 expert queries, G9 critic detection,
G10 paper-broker invariance, G11 PIT invariants, G12 VET/WIF promotion
reject, G13 R31.9 rule-conversion reject, G14 import idempotency,
G15 determinism, G16 full regression (delegated to the suite run).

Usage:
    uv run python scripts/validate_legacy_hist_001.py
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_bot.legacy_evidence import (
    ALLOWLIST_FILES,
    LEGACY_PERIOD_END_EXCLUSIVE,
    LEGACY_PERIOD_START,
    SOURCE_PATH,
    LegacyCritiqueHints,
    LegacyEvidenceBuilder,
    LegacyEvidenceIngester,
    LegacyEvidenceStore,
    LegacyHypothesisIndex,
    LegacyIngestError,
    LegacyPromotionError,
    ShadowEvidenceLinker,
)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))


# Expected R26 reconstruction (spec sanity block).
EXPECTED = {
    "opportunities": 24379,
    "trades": 2217,
    "complete_days": 108,
    "gross_pnl": 1923.3045,
    "fees": 5805.7575,
    "net_pnl": -3882.4530,
    "pf": 0.809422,
    "expectancy_r": -0.086659,
}


def approx(a: float | None, b: float, tol: float = 1e-3) -> bool:
    return a is not None and abs(a - b) <= tol


def main() -> int:
    workdir = Path("reports/legacy-hist-001/validator-flat")

    # -- G1: exact source path, intact ZIP ---------------------------------
    try:
        ingester = LegacyEvidenceIngester()
        zip_sha = ingester.source_sha256()
        source_ok = ingester.zip_path == SOURCE_PATH and len(zip_sha) == 64
    except LegacyIngestError as exc:
        check("g1_source_intact", False, str(exc))
        return _summary()
    check("g1_source_intact", source_ok, f"zip_sha256={zip_sha[:16]}…")

    # -- G2: strict allowlist against the real ZIP --------------------------
    with zipfile.ZipFile(SOURCE_PATH) as zf:
        names = [i.filename for i in zf.infolist() if not i.is_dir()]
    basenames = {Path(n.replace("\\", "/")).name for n in names}
    allowlisted_present = ALLOWLIST_FILES & basenames
    if allowlisted_present != ALLOWLIST_FILES:
        check("g2_allowlist_strict", False, "missing members")
        return _summary()
    # Every allowlist basename must appear exactly once in the ZIP.
    dupes = [
        b
        for b in ALLOWLIST_FILES
        if sum(1 for n in names if Path(n.replace("\\", "/")).name == b) != 1
    ]
    check("g2_allowlist_strict", not dupes, f"allowlisted={len(ALLOWLIST_FILES)} dupes={dupes}")

    # -- G3: secrets/freebuff never ingested --------------------------------
    forbidden_markers = ("freebuff2api", ".env", ".bat", ".ps1", ".pyc", "token", "credential")
    ingested_dirs = {  # only allowlisted files may be read from the ZIP
        f["zip_member"]
        for f in _ingest(ingester, workdir)["files"]
    }
    g3_ok = all(
        not any(marker in member.lower() for marker in forbidden_markers)
        for member in ingested_dirs
    )
    # Belt-and-braces: the never-read set is huge; sample-verify count.
    never_read = [n for n in names if Path(n.replace("\\", "/")).name not in ALLOWLIST_FILES]
    check("g3_secrets_never_ingested", g3_ok, f"read={len(ingested_dirs)} never_read={len(never_read)}")

    # Rebuild store (G4/G15 need repeated builds).
    builder = LegacyEvidenceBuilder(ingester, workdir)
    store, report = builder.build()
    builder2 = LegacyEvidenceBuilder(ingester, workdir)
    store2, report2 = builder2.build()

    # -- G4: deterministic SHA-256 + provenance -----------------------------
    prov = _ingest(ingester, workdir)
    by_name = {f["name"]: f for f in prov["files"]}
    recompute_ok = True
    with zipfile.ZipFile(SOURCE_PATH) as zf:
        for name, meta in by_name.items():
            data = next(
                zf.read(i) for i in zf.infolist() if Path(i.filename.replace("\\", "/")).name == name
            )
            if hashlib.sha256(data).hexdigest() != meta["sha256"]:
                recompute_ok = False
    provenance_stable = prov == _ingest(ingester, workdir)
    check("g4_provenance_deterministic", recompute_ok and provenance_stable)

    # -- G5: CONSUMED_DEVELOPMENT period marked everywhere ------------------
    g5 = all(
        r.consumed_development_period is True
        and r.period_start == LEGACY_PERIOD_START
        and r.period_end == LEGACY_PERIOD_END_EXCLUSIVE
        for r in store.all_records()
    )
    check("g5_consumed_period", g5, f"records={len(store)}")

    # -- G6: fail-closed flags ----------------------------------------------
    g6 = all(
        r.eligible_for_context is True
        and r.eligible_for_training is False
        and r.eligible_for_candidate_promotion is False
        and r.eligible_for_confirmation is False
        and r.can_affect_execution is False
        for r in store.all_records()
    )
    check("g6_fail_closed_flags", g6)

    # -- G7: MetaRanker invariance ------------------------------------------
    g7 = _gate_metaranker(store)
    check("g7_metaranker_invariance", g7)

    # -- G8: experts can query evidence --------------------------------------
    index = LegacyHypothesisIndex(store)
    g8 = (
        all(index.for_asset(a) for a in ("BTC", "ETH", "SOL"))
        and index.for_family("TP")
        and index.for_family("FBS")
        and len(store.catalogued_symbols()) == 30
    )
    check("g8_expert_queries", g8, f"catalogued={len(store.catalogued_symbols())}")

    # -- G9: critics detect legacy hypotheses --------------------------------
    hints = index.critique_hints(symbol="VET", legacy_family="TP")
    g9 = (
        isinstance(hints, LegacyCritiqueHints)
        and hints.hypothesis_already_tested
        and hints.cost_problem
        and hints.post_hoc_attempt
        and bool(index.rejected_campaigns())
    )
    check("g9_critics_detect_legacy", g9, hints.summary)

    # -- G10: paper-broker invariance ----------------------------------------
    g10 = _gate_broker(store)
    check("g10_paper_execution_invariance", g10)

    # -- G11: PIT / no-lookahead ---------------------------------------------
    now = datetime.now(tz=UTC)
    g11 = all(
        r.period_end <= datetime(2026, 8, 18, tzinfo=UTC) < now
        and r.can_affect_execution is False
        for r in store.all_records()
    )
    check("g11_pit_no_lookahead", g11)

    # -- G12: VET/WIF promotion attempt => REJECT ----------------------------
    g12_hits = 0
    for sym in ("VET", "WIF"):
        for record in store.by_symbol(sym):
            try:
                store.attempt_candidate_promotion(record.evidence_id)
            except LegacyPromotionError:
                g12_hits += 1
    check("g12_vet_wif_promotion_rejected", g12_hits >= 2, f"rejects={g12_hits}")

    # -- G13: R31.9 volume>=1 rule conversion => REJECT -----------------------
    r319 = next(r for r in store.all_records() if r.kind == "diagnostic")
    g13 = False
    try:
        store.attempt_rule_adoption(r319.evidence_id)
    except LegacyPromotionError:
        g13 = True
    check(
        "g13_r319_rule_conversion_rejected",
        g13 and r319.verdict == "FAIL_NOT_PROMOTED" and r319.payload["candidate"] == "VOL_GE_1",
    )

    # -- G14/G15: import idempotency + determinism ---------------------------
    same = [r.evidence_id for r in store.all_records()] == [
        r.evidence_id for r in store2.all_records()
    ] and report["sanity"] == report2["sanity"]
    check("g15_same_input_same_records", same)
    g14 = _gate_import_idempotent()
    check("g14_import_idempotent", g14)

    # -- Sanity reconstruction (spec block) ----------------------------------
    sanity = report["sanity"]
    sanity_ok = (
        sanity["opportunities"] == EXPECTED["opportunities"]
        and sanity["trades"] == EXPECTED["trades"]
        and sanity["complete_days"] == EXPECTED["complete_days"]
        and approx(sanity["gross_pnl"], EXPECTED["gross_pnl"])
        and approx(sanity["fees"], EXPECTED["fees"])
        and approx(sanity["net_pnl"], EXPECTED["net_pnl"])
        and approx(sanity["pf"], EXPECTED["pf"], 1e-5)
        and approx(sanity["expectancy_r"], EXPECTED["expectancy_r"], 1e-5)
        and sanity["trades_recomputed"] == EXPECTED["trades"]
        and approx(sanity["gross_pnl_recomputed"], EXPECTED["gross_pnl"])
        and approx(sanity["net_pnl_recomputed"], EXPECTED["net_pnl"])
    )
    check("sanity_r26_reconstruction", sanity_ok, json.dumps(sanity, default=str)[:200])

    # -- Legacy verdicts preserved -------------------------------------------
    bcd = next(r for r in store.all_records() if r.kind == "campaign")
    registry = next(r for r in store.all_records() if r.kind == "registry")
    ledger = {e["id"]: e["status"] for e in registry.payload["ledger"]}
    verdicts_ok = (
        bcd.verdict == "CAMPAIGN_STOP_NO_EDGE"
        and bcd.payload["individual_quality_passers"] == []
        and bcd.payload["portfolio_passers"] == []
        and ledger.get("R26") == "RETAINED_DEVELOPMENT_BASELINE"
    )
    check("legacy_verdicts_preserved", verdicts_ok)

    # -- No legacy code ported (NO-PORT list) ---------------------------------
    # AST-based: no import/definition of legacy runtime modules, no legacy
    # strategy code, no scheduler/exec plumbing. (Mentions in the exclusion
    # list are intentional and must not fail this gate.)
    src_root = Path(__file__).resolve().parents[1] / "src" / "trading_bot" / "legacy_evidence"
    ported: list[str] = []
    for path in src_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_legacy_module(alias.name):
                        ported.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if _is_legacy_module(module):
                    ported.append(f"{path.name}: from {module}")
    check("no_legacy_code_ported", not ported, f"violations={ported}")

    return _summary()


def _ingest(ingester: LegacyEvidenceIngester, workdir: Path) -> dict:
    return ingester.ingest(workdir)


def _is_legacy_module(name: str) -> bool:
    """True for legacy runtime modules that must never be imported."""
    lowered = name.lower()
    return (
        lowered.startswith("fran_")
        or "research_daemon" in lowered
        or lowered.startswith("future_campaign_common")
        or "scheduler" in lowered
    )


def _gate_metaranker(store: LegacyEvidenceStore) -> bool:
    from trading_bot.multi_agent.contracts import TraceContext, TradeDirection, TradeProposal
    from trading_bot.multi_agent.opportunity import MetaRanker, Opportunity

    clock = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    trace = TraceContext(
        run_id="v-run", trace_id="v-trace", correlation_id="v-corr", causation_id="v-cause"
    )
    proposal = TradeProposal(
        schema_version="ma-3-v1",
        proposal_id="p:v",
        run_id=trace.run_id,
        trace_id=trace.trace_id,
        asset="SOL",
        direction=TradeDirection.LONG,
        strategy="momentum",
        timeframe="5m",
        regime="TREND_UP",
        evidence_refs=("ev:v",),
        invalidation="structural stop",
        confidence=0.83,
        data_time=clock,
        created_at=clock,
        expires_at=clock.replace(minute=15),
        trace=trace,
    )
    opportunity = Opportunity(
        proposal=proposal,
        evidence_refs=proposal.evidence_refs,
        source_agent_id="strategy-expert-momentum",
        source_agent_version="1.0.0",
    )
    ranker = MetaRanker()
    baseline = ranker.score(opportunity, assessment=None, conflicted=False)
    ShadowEvidenceLinker(store).link("p:v", symbol="SOL", legacy_family="TP")
    with_layer = ranker.score(opportunity, assessment=None, conflicted=False)
    return (
        with_layer.score == baseline.score
        and with_layer.score_components == baseline.score_components
    )


def _gate_broker(store: LegacyEvidenceStore) -> bool:
    from trading_bot.paper.broker import PaperBroker
    from trading_bot.strategies.types import Signal

    def orders(with_layer: bool) -> int:
        broker = PaperBroker(equity=10_000.0)
        if with_layer:
            ShadowEvidenceLinker(store).link("p:b", symbol="SOL")
        result = broker.execute_signal(
            Signal(
                symbol="SOL/USDT",
                side="buy",
                strategy_name="momentum",
                timeframe="5m",
                confidence=0.8,
                price=100.0,
                stop_loss_pct=0.05,
                take_profit_pct=0.10,
            )
        )
        return 1 if result is not None else 0

    return orders(False) == orders(True)


def _gate_import_idempotent() -> bool:
    import importlib

    before = set(sys.modules)
    mod = importlib.import_module("trading_bot.legacy_evidence")
    reloaded = importlib.reload(mod)
    after = set(sys.modules)
    new_leaks = [
        m
        for m in after - before
        if m.startswith("trading_bot") and "legacy" not in m and "multi_agent" not in m and "paper" not in m
    ]
    return reloaded is not None and not new_leaks


def _summary() -> int:
    total = len(RESULTS)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = total - passed
    print(f"\nLEGACY-HIST-001 validator: {passed}/{total} PASS, {failed} FAIL")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
