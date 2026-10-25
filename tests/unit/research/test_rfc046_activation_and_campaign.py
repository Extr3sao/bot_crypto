"""RFC-046 activation (2026-10-08, ADR-0024) and its first campaign — offline guards.

The checks below are deliberately read from the **artefacts that are actually obeyed**: the
governance documents, the live-trading gate, the frozen specs and the run report. Nothing here
asserts that an ADR says something nice; each assertion is about a file a program reads.

The proposal-era suite that asserted ``NOT_ACTIVE`` was replaced by this one: the owner approved
option 5A, which is exactly the transition those assertions were waiting to detect.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "rfc046"
RUN_JSON = DATA / "RUN_REPORT.json"
RUN_MD = DATA / "RUN_REPORT.md"
CAMPAIGN_DETAIL = REPO / "reports" / "rfc046" / "CAMPAIGN_DETAIL.json"
ACTIVATION = DATA / "ACTIVATION.json"
SPECS = REPO / "docs" / "research" / "discovery_campaign" / "specs"
REGISTRY = REPO / "docs" / "roadmap" / "RFC_REGISTRY.json"
DISCOVERY_MODULE = REPO / "src" / "trading_bot" / "research" / "discovery" / "__init__.py"

FORBIDDEN_VERDICTS = ("EDGE_CONFIRMED", "PROFITABLE", "PRODUCTION_READY")
NEGATIONS = ("never", "not ", "no ", "false", "cannot", "out of scope", "absence", "forbidden")
EXECUTION_TOKENS = (
    "create_order",
    "place_order",
    "submit_order",
    "ccxt",
    "binance.client",
    "api_key",
    "API_SECRET",
    "requests.",
    "urllib.request",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _spec_paths() -> list[Path]:
    return sorted(SPECS.glob("HYP-*.json"))


# --------------------------------------------------------------------------- #
# Governance activation
# --------------------------------------------------------------------------- #


def test_owner_approval_is_recorded_as_an_adr() -> None:
    decisions = _read(REPO / "tasks" / "decisions.md")
    assert re.search(r"^## ADR-0024\b", decisions, flags=re.MULTILINE), "ADR-0024 missing"
    assert "2026-10-08" in decisions
    assert "exclusivamente en investigacion offline" in decisions, "the ADR must limit scope to offline"
    assert "G_BUSINESS_REENTRY" in decisions and "distinto de PASS" in decisions
    assert "DISCOVERY_CAMPAIGN_FAILED" in decisions, "the stop rule must be in the approval record"


def test_rfc_state_flipped_but_production_gates_did_not() -> None:
    state = json.loads(_read(REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.json"))
    assert state["status"] == "APPROVED"
    assert state["approved"] is True and state["active"] is True
    assert state["approval"]["approved_at"] == "2026-10-08"
    assert state["approval"]["decision"].startswith("option 5A")
    runtime = state["runtime_state"]
    assert runtime["live_trading_enabled"] is False
    assert runtime["trades_authorized"] == 0
    assert runtime["profitability_verified"] is False
    assert runtime["discovery_offline_authorized"] is True
    assert state["invariants_while_active"]["G_BUSINESS_REENTRY"] == "NOT_PASS"
    text = _read(REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.md")
    assert "APPROVED / ACTIVE" in text and "## 00 — APPROVAL RECORD" in text


def test_rfc041_exemption_is_dated_and_does_not_open_production() -> None:
    policy = json.loads(_read(REPO / "docs" / "research" / "BUSINESS_REENTRY_POLICY.json"))
    exemption = policy["rfc046_limited_exemption"]
    assert exemption["approved_at"] == "2026-10-08"
    assert exemption["gate_state"]["G_BUSINESS_REENTRY"] == "NOT_PASS"
    assert exemption["gate_state"]["TRADES_AUTHORIZED"] == 0
    assert policy["next_rfc_requires"] == "G_BUSINESS_REENTRY = PASS", "the production gate is unchanged"
    for refused in ("live trading", "real orders", "paper trading"):
        assert refused in exemption["not_authorized"]
    md = _read(REPO / "docs" / "research" / "BUSINESS_REENTRY_POLICY.md")
    assert "EXCEPCION LIMITADA Y FECHADA" in md and "2026-10-08" in md


def test_operating_model_trigger_admits_only_the_offline_exemption() -> None:
    model = json.loads(_read(REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json"))
    policy = model["next_action_policy"]
    assert "RFC-046 limited exemption" in policy["trigger"]
    assert policy["rfc046_limited_exemption"]["gate_state"] == {
        "G_BUSINESS_REENTRY": "NOT_PASS",
        "LIVE_TRADING": "DISABLED",
        "TRADES_AUTHORIZED": 0,
    }
    md = _read(REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.md")
    assert "RFC-046 limited exemption" in md, "the .md twin must not drift from the .json"


def test_rfc035_freeze_is_closed_without_rewriting_its_body() -> None:
    freeze = _read(REPO / "docs" / "governance" / "PROFITABILITY_FIRST_FREEZE.md")
    assert "ADDENDUM DE CIERRE" in freeze
    assert "CLOSED_RFC035_ENDED" in freeze
    assert "## 8. Cierre formal" in freeze
    for marker in ("## 4. Single exception", "ACTIVE_RFC: **RFC-035", "## 7. Exit condition"):
        assert marker in freeze, f"historical body marker lost: {marker}"


def test_roadmap_and_registry_record_the_phase_and_the_number() -> None:
    roadmap = _read(REPO / "tasks" / "roadmap.md")
    assert "## Fase 10 - Investigacion cuantitativa controlada (RFC-046)" in roadmap
    assert "## Fase 9" in roadmap and "## Regla de salto" in roadmap
    registry = json.loads(_read(REGISTRY))
    assert registry["numbers"]["046"]["status"] == "APPROVED / ACTIVE"
    assert registry["numbers"]["046"]["approval_record"] == "tasks/decisions.md ADR-0024"
    assert registry["numbers"]["045"]["state"] == "VACANT_BY_CONTROL"
    assert registry["numbers"]["045"]["assertion_count"] >= 4
    assert registry["numbers"]["036"]["state"] == "OCCUPIED"
    assert registry["next_free_number_above_046"] not in registry["numbers"]
    assert registry["counts"]["occupied"] >= 27


def test_proposal_era_tools_are_labelled_as_history() -> None:
    for rel in ("scripts/rfc046_audit.py", "scripts/rfc046_verify.py"):
        text = _read(REPO / rel)
        assert "HISTORICAL SCOPE (2026-10-08)" in text, f"{rel} must say it is history"
        assert "rfc046_campaign_verify.py" in text, f"{rel} must point at the current verifier"


# --------------------------------------------------------------------------- #
# Negative permission tests: no order can leave this programme
# --------------------------------------------------------------------------- #


def test_live_trading_gate_refuses_the_current_configuration() -> None:
    from trading_bot.config.settings import Settings
    from trading_bot.execution.live_gate import LiveTradingGate

    try:
        settings = Settings()
    except Exception:  # pragma: no cover - depends on ambient env
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
    report = LiveTradingGate(settings, data_dir=REPO / "data").validate()
    assert report.all_passed is False, "the live gate must not pass in this configuration"
    assert report.critical_failures, "a refusal must name at least one critical failure"
    assert settings.runtime.live_trading_enabled is False
    assert settings.runtime.mode.value == "paper"


def test_the_execution_path_raises_a_live_block() -> None:
    source = _read(REPO / "src" / "trading_bot" / "execution" / "live_gate.py")
    assert "class LiveTradingBlocked" in source
    assert "raise LiveTradingBlocked" in source, "the block must actually be raised somewhere"


def test_configuration_keeps_live_disabled() -> None:
    for rel in ("config/runtime.yaml", "config/risk.yaml"):
        assert "live_trading_enabled: false" in _read(REPO / rel), f"{rel} enables live trading"


def test_discovery_code_cannot_touch_an_order_or_a_credential() -> None:
    files = [
        DISCOVERY_MODULE,
        REPO / "scripts" / "rfc046_campaign.py",
        REPO / "scripts" / "rfc046_activate.py",
        REPO / "scripts" / "rfc046_campaign_verify.py",
    ]
    for path in files:
        body = _read(path)
        for token in EXECUTION_TOKENS:
            assert token not in body, f"{path.name} must not reference {token!r}"
        tree = ast.parse(body)
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        forbidden_prefixes = ("ccxt", "requests", "urllib", "trading_bot.execution", "trading_bot.market_data")
        assert not any(i.startswith(forbidden_prefixes) for i in imports), (path.name, sorted(imports))


# --------------------------------------------------------------------------- #
# PIT integrity
# --------------------------------------------------------------------------- #


def test_defective_htf_helper_is_not_on_the_discovery_data_path() -> None:
    tree = ast.parse(_read(DISCOVERY_MODULE))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "get_completed_htf_state_at" not in names
    assert "htf_pit" not in _read(DISCOVERY_MODULE), "the defective helper must not be imported"
    contract = json.loads(_read(REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.json"))
    conventions = " ".join(contract["data_partition"]["existing_reusable_convention"])
    assert "availability_ms" in conventions and "is_candle_complete" in conventions, (
        "the RFC must name the reusable PIT conventions the campaign is allowed to follow"
    )
    assert contract["data_partition"]["known_open_defect"].startswith("DEF-HTF-PIT-001")


def test_signals_need_no_data_after_their_own_exit() -> None:
    import sys

    sys.path.insert(0, str(REPO / "src"))
    from trading_bot.research import discovery as D

    spec = D.load_spec(SPECS / "HYP-002.json")
    bars = D.load_bars(REPO / "data" / "raw" / "alpha003" / "price" / f"{spec.asset}_1h.json")
    funding = D.load_funding(REPO / "data" / "raw" / "alpha002" / "funding_rate" / f"{spec.asset}.json")
    signals = D.signal_settlement_dip(bars, funding, spec.parameters)
    assert signals, "a look-ahead probe with no signals proves nothing"
    for signal in signals[:3] + signals[-3:]:
        prefix_bars = [b for b in bars if b.open_time_ms <= signal.exit_ms]
        prefix_funding = [f for f in funding if f.time_ms <= signal.entry_ms]
        again = D.signal_settlement_dip(prefix_bars, prefix_funding, spec.parameters)
        assert any(s.entry_ms == signal.entry_ms for s in again), signal.reason


# --------------------------------------------------------------------------- #
# Frozen specs and campaign output
# --------------------------------------------------------------------------- #


def test_three_specs_are_frozen_before_evaluation() -> None:
    paths = _spec_paths()
    assert len(paths) == 3, "the budget is three hypotheses, one candidate each"
    report = json.loads(_read(RUN_JSON))
    recorded = {run["hypothesis_id"]: run["spec_hash"] for run in report["runs"]}
    assert len(recorded) == 3
    for path in paths:
        spec = json.loads(_read(path))
        assert spec["cost_bps"] == 23.7906, "the audited cost is not negotiable"
        assert [p["name"] for p in spec["partitions"]] == ["development", "validation", "final_oos"]
        assert spec["mechanism"] in {
            "institutional_constraint",
            "risk_transfer",
            "market_microstructure",
            "forced_flows",
            "regulatory_effect",
            "structural_carry",
            "liquidity_provision",
        }
        assert spec["source_ids"], "a hypothesis must name its sources"
        assert spec["registered_at_utc"] == "2026-10-08"
        digest = hashlib.sha256(
            json.dumps(spec, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assert recorded[spec["hypothesis_id"]] == digest, f"{path.name} changed after the run"
        assert spec["parameters"], "frozen parameters are required"


def test_no_candidate_passed_and_the_campaign_stopped() -> None:
    report = json.loads(_read(RUN_JSON))
    verdicts = report["campaign"]["verdicts"]
    assert set(verdicts) == {"CAND-046-001", "CAND-046-002", "CAND-046-003"}
    assert all(v == "CANDIDATE_REJECTED" for v in verdicts.values())
    assert report["campaign"]["campaign_status"] == "DISCOVERY_CAMPAIGN_FAILED"
    assert "NONE" in report["campaign"]["refill"], "a failed campaign must not refill itself"
    assert report["runtime_state"]["profitability_verified"] is False
    assert report["runtime_state"]["false_success"] == 0


def test_every_candidate_reports_the_full_gate() -> None:
    report = json.loads(_read(RUN_JSON))
    for run in report["runs"]:
        gate = run["gate"]
        assert [r["id"] for r in gate["requirements"]] == [f"PG-{i}" for i in range(1, 12)]
        assert gate["verdict"] == "CANDIDATE_REJECTED"
        assert gate["failed"], "a rejection must name the gates it failed"
        assert run["spec_hash"]
        assert run["data"]["bars"] > 0


def test_zero_sample_hypothesis_is_recorded_as_such() -> None:
    detail = json.loads(CAMPAIGN_DETAIL.read_text(encoding="utf-8"))
    by_id = {run["spec"]["hypothesis_id"]: run for run in detail["runs"]}
    assert by_id["HYP-003"]["gate"]["zero_sample"] is True
    assert by_id["HYP-003"]["trades"] == []
    for hid in ("HYP-001", "HYP-002"):
        assert by_id[hid]["gate"]["zero_sample"] is False
        assert by_id[hid]["trades"], f"{hid} should have produced trades"


def test_no_forbidden_verdict_appears_outside_a_negation() -> None:
    text = _read(RUN_MD) + json.dumps(json.loads(_read(RUN_JSON)))
    for line in text.splitlines():
        for verdict in FORBIDDEN_VERDICTS:
            if verdict in line:
                assert any(marker in line.lower() for marker in NEGATIONS), line


def test_independent_verification_passed_and_is_independent() -> None:
    result = json.loads(_read(ACTIVATION))
    assert result["status"] == "PASS"
    assert result["mismatches"] == 0
    assert result["false_success"] == 0
    assert result["checks_total"] >= 70
    assert result["builder_equals_verifier"] is False
    assert result["verifier"] != result["builder"]
    assert result["campaign"]["campaign_status"] == "DISCOVERY_CAMPAIGN_FAILED"
    policy = result["policy_checks"]
    assert "governance documents themselves" in policy


def test_run_report_timestamp_is_computed_not_authored() -> None:
    report = json.loads(_read(RUN_JSON))
    stamp = report["generated_at_utc"]
    assert re.fullmatch(r"20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp), stamp
    assert report["head_at_run"] and re.fullmatch(r"[0-9a-f]{40}", report["head_at_run"])


@pytest.mark.parametrize("rel", ["data/rfc046/RUN_REPORT.md", "data/rfc046/RUN_REPORT.json"])
def test_tracked_run_report_exists_and_is_not_empty(rel: str) -> None:
    path = REPO / rel
    assert path.is_file() and path.stat().st_size > 0
