"""Independent verification of the ECONOMIC-001 cost-evidence closure.

These tests take the closure's own claims and re-derive them from *other* sources: the raw price
series on a third window convention, the frozen cost constants, the raw read-only snapshot, the
governance documents, and git itself.  They never run the builder and never rewrite an artefact.

Route summary: the builder measured aligned windows on native series; the verifier script used
exhaustive and shifted windows; here the horizons are re-measured with a prime step and the family
verdicts are re-derived from the *rule* rather than from the published booleans, the cost split is
re-summed from the frozen components, the spread is re-pooled from the snapshot, and the
non-circularity claim is re-checked against the commit's tree.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import statistics
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CLOSURE = REPO / "data" / "economic001" / "EVIDENCE_CLOSURE.json"
CLOSURE_MD = REPO / "data" / "economic001" / "EVIDENCE_CLOSURE.md"
VERIFICATION = REPO / "data" / "economic001" / "EVIDENCE_CLOSURE_VERIFICATION.json"
SNAPSHOT = REPO / "data" / "economic001" / "READ_ONLY_SNAPSHOT.json"
COST_MODEL = REPO / "docs" / "COST_MODEL_V3.json"
FORENSICS = REPO / "data" / "rfc046" / "COST_FORENSICS.json"
RUN_REPORT = REPO / "data" / "rfc046" / "RUN_REPORT.json"
RFC046 = REPO / "docs" / "rfc" / "RFC-046_CONTROLLED_DISCOVERY.json"
OPERATING_MODEL = REPO / "docs" / "research" / "PROFITABILITY_OPERATING_MODEL.json"
EXCHANGE_CFG = REPO / "config" / "exchange.yaml"
RUNTIME_CFG = REPO / "config" / "runtime.yaml"
PRICE_DIR = REPO / "data" / "raw" / "alpha003" / "price"
STORAGE = REPO / "data" / "storage"

BPS = 10_000.0
CAPITAL = 200.0
DOCUMENTED_SIZE = 1000.0
FROZEN_TOLL_BPS = 23.7906
POSTERIOR_TOLL_BPS = 23.353553391
MARGIN_MULTIPLE = 5.0
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
HORIZONS = {
    "5m": ("5m", 1),
    "15m": ("15m", 1),
    "1h": ("1h", 1),
    "4h": ("1h", 4),
    "8h": ("1h", 8),
    "24h": ("1h", 24),
    "72h": ("1h", 72),
    "168h": ("1h", 168),
}
SERIES_MINUTES = {"5m": 5, "15m": 15, "1h": 60}
LONG_HORIZON_FAMILIES = ("momentum", "swing_trading", "trend_following")
FORBIDDEN_TOKENS = ("EDGE_CONFIRMED", "PROFITABLE", "PRODUCTION_READY", "READY_FOR_LIVE")
VERDICTS = ("COST_EVIDENCE_VERIFIED", "COST_EVIDENCE_INCOMPLETE", "COST_EVIDENCE_FAILED")
REQUIRED_FIELDS = (
    "CURRENT_HEAD",
    "FILES_COMMITTED",
    "DATASET_HASHES",
    "TIMEFRAME_VERIFICATION",
    "COST_MODEL_STATUS",
    "READ_ONLY_MARKET_DATA_STATUS",
    "ESTIMATED_VS_MEASURED_COSTS",
    "INDEPENDENT_VERIFICATION",
    "FALSE_SUCCESS",
    "OPEN_DEFECTS",
    "NEXT_GATE",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def git(*args: str) -> tuple[str, int]:
    result = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=False)
    return result.stdout.strip(), result.returncode


def moves(asset: str, timeframe: str, bars: int, step: int, offset: int) -> list[float]:
    rows = read_json(PRICE_DIR / f"{asset}_{timeframe}.json")
    opens = [float(row[1]) for row in rows]
    return [
        abs(opens[start + bars] / opens[start] - 1.0) * BPS
        for start in range(offset, len(opens) - bars, step)
    ]


@pytest.fixture(scope="module")
def closure() -> dict:
    return read_json(CLOSURE)  # type: ignore[return-value]


@pytest.fixture(scope="module")
def verification() -> dict:
    return read_json(VERIFICATION)  # type: ignore[return-value]


@pytest.fixture(scope="module")
def model() -> dict:
    return read_json(COST_MODEL)  # type: ignore[return-value]


def test_the_artefacts_exist_and_the_verification_is_clean(
    closure: dict, verification: dict
) -> None:
    assert CLOSURE.exists() and CLOSURE_MD.exists() and VERIFICATION.exists() and SNAPSHOT.exists()
    assert verification["status"] == "PASS"
    assert verification["mismatches"] == 0
    assert verification["checks_passed"] == verification["checks_total"]
    assert verification["false_success"] == 0
    assert closure["false_success"] == 0


def test_the_verified_bytes_are_the_shipped_bytes(closure: dict, verification: dict) -> None:
    assert verification["verified_artifact_sha256"] == sha256(CLOSURE)
    assert closure["builder_equals_verifier"] is False
    assert verification["builder_equals_verifier"] is False
    assert verification["builder"] != verification["verifier"]


def test_the_closure_states_its_own_weight_and_limits(closure: dict) -> None:
    assert closure["artifact"] == "ECONOMIC-001_COST_EVIDENCE_CLOSURE"
    assert closure["gate"] == "ECONOMIC-001"
    assert closure["builder"].endswith("economic001_closure.py")
    assert len(closure["does_not_license"]) >= 3
    haystack = json.dumps(closure).upper() + CLOSURE_MD.read_text(encoding="utf-8").upper()
    assert [token for token in FORBIDDEN_TOKENS if token in haystack] == []


def test_the_final_report_delivers_the_eleven_required_fields(closure: dict) -> None:
    final = closure["final_report"]
    assert set(REQUIRED_FIELDS).issubset(final)
    assert final["CURRENT_HEAD"] == closure["head_at_run"]
    assert final["FALSE_SUCCESS"] == 0
    assert final["NEXT_GATE"]["campaign"] == "NOT_AUTHORIZED"
    assert final["NEXT_GATE"]["trades_authorized"] == 0
    assert final["COST_MODEL_STATUS"]["rejected_candidates_recomputed"] is False
    assert final["READ_ONLY_MARKET_DATA_STATUS"]["orders_sent"] == 0
    assert final["READ_ONLY_MARKET_DATA_STATUS"]["credentials_used"] == 0


def test_the_dataset_hashes_are_the_files_on_disk(closure: dict) -> None:
    hashes = closure["dataset_hashes"]
    assert len(hashes) == 12
    for relative, recorded in hashes.items():
        assert recorded == sha256(REPO / relative), relative


def test_the_delivery_commit_carries_exactly_the_six_deliverables(closure: dict) -> None:
    commit = closure["evidence_preservation"]["delivery_commit"]
    listing, rc = git("show", "--name-only", "--format=", commit)
    assert rc == 0
    paths = sorted(line for line in listing.splitlines() if line.strip())
    assert paths == sorted(closure["evidence_preservation"]["deliverables"])
    assert closure["evidence_preservation"]["foreign_paths_in_delivery_commit"] == []


def test_the_closure_is_not_inside_the_commit_it_names(closure: dict) -> None:
    commit = closure["evidence_preservation"]["delivery_commit"]
    closure_path = str(CLOSURE.relative_to(REPO)).replace("\\", "/")
    _, present = git("cat-file", "-e", f"{commit}:{closure_path}")
    assert present != 0
    _, ancestor = git("merge-base", "--is-ancestor", commit, git("rev-parse", "HEAD")[0])
    assert ancestor == 0


def test_every_deliverable_hash_matches_the_repository(closure: dict) -> None:
    commit = closure["evidence_preservation"]["delivery_commit"]
    for relative, recorded in closure["evidence_preservation"]["deliverable_hashes"].items():
        assert recorded["working_tree_sha256"] == sha256(REPO / relative), relative
        blob = subprocess.run(
            ["git", "cat-file", "blob", f"{commit}:{relative}"],
            cwd=REPO,
            capture_output=True,
            check=True,
        ).stdout
        assert recorded["git_blob_sha256"] == hashlib.sha256(blob).hexdigest(), relative


def test_the_report_bytes_still_match_the_rfc046_verification(closure: dict) -> None:
    presence = closure["evidence_preservation"]
    assert presence["bytes_match_the_verified_run"] is True
    assert presence["verified_artifact_sha256_recorded_by_verifier"] == sha256(
        REPO / "data" / "rfc046" / "ECONOMIC_FEASIBILITY.json"
    )


def test_every_horizon_is_certified_by_a_series_that_can_certify_it(closure: dict) -> None:
    per_horizon = closure["horizon_verification"]["per_horizon"]
    assert set(per_horizon) == set(HORIZONS)
    for horizon, (timeframe, bars) in HORIZONS.items():
        minutes = int(horizon.rstrip("mh") or 0) * (60 if horizon.endswith("h") else 1)
        resolution = SERIES_MINUTES[timeframe]
        assert resolution <= minutes and minutes % resolution == 0, horizon
        row = per_horizon[horizon]
        assert row["series_resolution_minutes"] == resolution
        assert row["bars_per_window"] == bars
        assert row["resolution_is_sufficient"] is True
        assert row["windows"] > 0
        assert row["median_abs_move_bps"] > 0
        assert row["windows_are_disjoint"] is True


def test_the_medians_reproduce_on_a_third_window_convention(closure: dict) -> None:
    """A prime step (5) is neither the builder's aligned step nor the verifier's shifted one."""
    per_horizon = closure["horizon_verification"]["per_horizon"]
    for horizon, (timeframe, bars) in HORIZONS.items():
        step = 5 * bars
        pooled: list[float] = []
        for asset in ASSETS:
            pooled.extend(moves(asset, timeframe, bars, step, bars))
        recomputed = statistics.median(pooled)
        published = per_horizon[horizon]["median_abs_move_bps"]
        assert abs(recomputed - published) / published <= 0.25, (horizon, recomputed, published)


def test_the_median_ordering_is_the_one_the_families_relied_on(closure: dict) -> None:
    per_horizon = closure["horizon_verification"]["per_horizon"]
    medians = {horizon: row["median_abs_move_bps"] for horizon, row in per_horizon.items()}
    ordered = ["5m", "15m", "1h", "4h", "8h", "24h", "72h", "168h"]
    values = [medians[horizon] for horizon in ordered]
    assert values == sorted(values), values
    assert medians["168h"] / medians["24h"] > 2.0


def test_the_timestamps_are_gapless_grid_aligned_and_on_one_timeline(closure: dict) -> None:
    for timeframe, minutes in SERIES_MINUTES.items():
        step_ms = minutes * 60_000
        for asset in ASSETS:
            rows = read_json(PRICE_DIR / f"{asset}_{timeframe}.json")
            times = [int(row[0]) for row in rows]
            assert len(set(times)) == len(times), (asset, timeframe)
            assert all(t % step_ms == 0 for t in times), (asset, timeframe)
            assert all(b - a == step_ms for a, b in itertools.pairwise(times)), (asset, timeframe)
    assert closure["horizon_verification"]["assets_with_aggregation_mismatch"] == []
    # The hourly file must open exactly where the 5-minute series opens on the same grid.
    five = [int(row[0]) for row in read_json(PRICE_DIR / "BTCUSDT_5m.json")]
    hour = [int(row[0]) for row in read_json(PRICE_DIR / "BTCUSDT_1h.json")]
    assert five[0] == hour[0]
    assert set(hour).issubset(set(five))


def test_the_cost_split_resums_from_the_frozen_components(closure: dict, model: dict) -> None:
    split = closure["cost_model_verification"]["split"]
    evaluation = next(
        scenario["evaluation"]
        for scenario in model["scenarios"]
        if scenario["evaluation"]["scenario_id"] == "BINANCE_SPOT_STANDARD_TAKER"
    )
    known = sum(c["value_bps"] for c in evaluation["components"] if c["knowledge"] == "KNOWN")
    estimated = sum(c["value_bps"] for c in evaluation["components"] if c["knowledge"] != "KNOWN")
    assert split["known_fees_bps"] == pytest.approx(known, abs=1e-9)
    assert split["estimated_execution_bps"] == pytest.approx(estimated, abs=1e-9)
    assert split["known_fees_bps"] == pytest.approx(20.0, abs=1e-9)
    assert split["recomputed_total_bps_at_1000_usd"] == pytest.approx(FROZEN_TOLL_BPS, abs=1e-4)


def test_the_two_tolls_are_distinct_and_the_historical_one_is_frozen(closure: dict) -> None:
    costs = closure["cost_model_verification"]
    assert costs["historical_evaluation_toll_bps"] == FROZEN_TOLL_BPS
    assert costs["posterior_evaluation_toll_bps"] == pytest.approx(POSTERIOR_TOLL_BPS, abs=1e-9)
    assert costs["posterior_evaluation_toll_bps"] < costs["historical_evaluation_toll_bps"]
    assert read_json(FORENSICS)["cost_model"]["admission_round_trip_bps"] == FROZEN_TOLL_BPS
    assert costs["non_retroactivity"]["cost_forensics_sha256"] == sha256(FORENSICS)
    assert costs["non_retroactivity"]["run_report_sha256"] == sha256(RUN_REPORT)
    assert costs["non_retroactivity"]["rejected_candidates_recomputed"] is False
    assert costs["maker_path"]["admissible"] is False


def test_the_break_even_at_the_account_size_is_the_posterior_toll(
    closure: dict, model: dict
) -> None:
    constants = model["model_constants"]
    spec = next(
        scenario["spec"]
        for scenario in model["scenarios"]
        if scenario["spec"]["scenario_id"] == "BINANCE_SPOT_STANDARD_TAKER"
    )
    ratio = (CAPITAL / constants["reference_notional_usd"]) ** 0.5
    expected = (
        2 * spec["taker_fee_bps"]
        + spec["default_taker_spread_bps"]
        + 2 * constants["base_slippage_bps"] * (1 + ratio)
        + 2 * constants["base_impact_bps"] * ratio
    )
    assert expected == pytest.approx(POSTERIOR_TOLL_BPS, abs=1e-9)
    assert closure["cost_model_verification"]["independent_recomputation"]["at_200_usdt"][
        "total_bps"
    ] == pytest.approx(expected, abs=1e-9)
    assert closure["cost_model_verification"]["independent_recomputation"]["at_200_usdt"][
        "stressed_at_1p5x_bps"
    ] == pytest.approx(expected * 1.5, abs=1e-6)
    assert (
        closure["cost_model_verification"]["independent_recomputation"]["at_200_usdt"]["fees_share"]
        > 0.85
    )


def test_the_read_only_collection_proves_it_sent_nothing(closure: dict) -> None:
    snapshot = read_json(SNAPSHOT)
    collection = closure["read_only_execution_reality"]["collection"]
    assert snapshot["orders_sent"] == 0
    assert snapshot["credentials_used"] == 0
    assert snapshot["private_endpoints_called"] == []
    assert snapshot["authentication"].startswith("none")
    assert snapshot["budget"]["finite"] is True
    assert snapshot["budget"]["declared_before_collection"] is True
    assert snapshot["budget"]["requests_made"] <= snapshot["budget"]["requests_planned"]
    assert collection["orders_sent"] == 0
    assert collection["credentials_used"] == 0
    assert snapshot["endpoint_base"] == "https://api.binance.com"


def test_the_measured_spread_is_re_pooled_from_the_raw_snapshot(closure: dict) -> None:
    snapshot = read_json(SNAPSHOT)
    spreads = {symbol: [] for symbol in snapshot["symbols"]}
    for row in snapshot["observations"]:
        for symbol, book in row["books"].items():
            spreads[symbol].append(book["spread_bps"])
    pool = [value for values in spreads.values() for value in values]
    block = closure["read_only_execution_reality"]["spread"]
    assert block["pooled_median_full_spread_bps"] == pytest.approx(
        statistics.median(pool), abs=1e-6
    )
    assert block["max_observed_full_spread_bps"] == pytest.approx(max(pool), abs=1e-6)
    assert block["modelled_round_trip_spread_bps"] == 1.0
    assert block["verdict"] in (
        "MODEL_CONSERVATIVE",
        "AT_THE_MODELLED_BOUNDARY",
        "WIDER_THAN_MODELLED",
    )
    assert block["conservative_verdict"] in (
        "MODEL_CONSERVATIVE",
        "AT_THE_MODELLED_BOUNDARY",
        "WIDER_THAN_MODELLED",
    )
    for symbol, row in block["per_symbol"].items():
        assert row["observations"] == snapshot["budget"]["rounds"], symbol
        assert row["median_full_spread_bps"] == pytest.approx(
            statistics.median(spreads[symbol]), abs=1e-6
        )


def test_the_depth_walk_is_arithmetic_and_larger_sizes_cost_more(closure: dict) -> None:
    snapshot = read_json(SNAPSHOT)
    block = closure["read_only_execution_reality"]["depth"]
    for symbol in snapshot["symbols"]:
        asks = snapshot["observations"][0]["depth"][symbol]["asks"]
        best = asks[0][0]
        # Recompute the 20,000 USDT walk here, independently of both scripts.
        target, spent, qty = 20_000.0, 0.0, 0.0
        for price, size in asks:
            take = min(target - spent, price * size)
            if take <= 0:
                break
            spent += take
            qty += take / price
        filled = spent >= 20_000.0 - 1e-9
        reported = block["impact_estimate_bps"][symbol]["20000_usdt"]["buy"]
        assert reported["filled"] is filled
        if filled:
            assert reported["cost_bps"] == pytest.approx(
                (spent / qty - best) / best * BPS, abs=1e-6
            )
        assert reported["cost_bps"] is None or reported["cost_bps"] >= 0.0
    assert block["all_targets_covered"] is True


def test_nothing_unmeasurable_is_claimed_as_measured(closure: dict) -> None:
    block = closure["read_only_execution_reality"]
    assert block["realized_slippage_measured"] is False
    assert block["fill_quality_measured"] is False
    assert block["simulator_used_as_measurement"] is False
    assert block["maker_queue_position"] == "UNKNOWN"
    assert block["historical_spread"] == "UNVERIFIABLE_NO_HISTORICAL_ENDPOINT"
    unknown = " ".join(block["estimated_vs_measured"]["unknown_and_stated"]).lower()
    for term in ("queue position", "fill probability", "realised slippage", "fill quality"):
        assert term in unknown


def test_the_family_verdicts_follow_the_rule_not_the_published_flags(closure: dict) -> None:
    block = closure["economic_decision"]
    assert block["rule"].startswith("movement margin is sufficient")
    for family, row in block["per_family"].items():
        expected = row["median_abs_move_bps"] / POSTERIOR_TOLL_BPS >= MARGIN_MULTIPLE
        assert row["movement_margin_sufficient"] is expected, family
        assert row["multiple_of_posterior_toll"] == pytest.approx(
            row["median_abs_move_bps"] / POSTERIOR_TOLL_BPS, abs=1e-5
        )
        assert (
            row["median_abs_move_bps"]
            == closure["horizon_verification"]["per_horizon"][row["horizon"]]["median_abs_move_bps"]
        )
    expected_verdict = (
        "MOVEMENT_MARGIN_SUFFICIENT_FOR_FURTHER_RESEARCH"
        if all(
            block["per_family"][family]["movement_margin_sufficient"]
            for family in LONG_HORIZON_FAMILIES
        )
        else "MOVEMENT_MARGIN_INSUFFICIENT"
    )
    assert block["scope_verdict"] == expected_verdict


def test_the_rejected_candidates_are_preserved_and_not_recomputed(closure: dict) -> None:
    block = closure["economic_decision"]
    forensics = read_json(FORENSICS)
    assert set(block["rejected_candidates_preserved"]) == set(forensics["candidates"])
    for candidate_id, preserved in block["rejected_candidates_preserved"].items():
        recorded = forensics["candidates"][candidate_id]
        assert preserved["verdict"] == recorded["verdict"], candidate_id
        assert preserved["gross_expectancy_bps"] == recorded["gross_expectancy_bps"], candidate_id
        assert preserved["recomputed_here"] is False
        assert preserved["gate_verdict"] == "CANDIDATE_REJECTED"
    zero_sample = block["rejected_candidates_preserved"]["CAND-046-003"]
    assert zero_sample["gross_expectancy_bps"] is None
    assert zero_sample["zero_sample"] is True
    assert block["new_hypotheses_generated"] == 0
    assert block["new_strategies_recommended"] == 0
    assert block["rejected_candidates_recomputed"] == 0


def test_movement_margin_is_never_presented_as_alpha(closure: dict) -> None:
    block = closure["economic_decision"]
    assert block["movement_margin_is_not_alpha"] is True
    assert block["movement_margin_is_not_capturable_edge"] is True
    assert "not evidence that any mechanism" in block["reading"]
    assert block["it_does_not_authorize"]


def test_the_standing_limits_are_read_from_the_governance_documents(closure: dict) -> None:
    standing = closure["standing"]
    invariants = read_json(RFC046)["invariants_while_active"]
    assert standing["trades_authorized"] == invariants["TRADES_AUTHORIZED"] == 0
    assert standing["rfc_live_trading"] == invariants["LIVE_TRADING"] == "DISABLED"
    assert invariants["real_orders"] == "REFUSED_BY_POLICY"
    assert standing["campaign_status"] == "DISCOVERY_CAMPAIGN_FAILED"
    assert standing["next_campaign"] == "NOT_AUTHORIZED"
    assert standing["profitability_verified"] is False
    assert standing["G_BUSINESS_REENTRY"] == "NOT_PASS"
    assert standing["false_success"] == 0
    assert '"TRADES_AUTHORIZED": 0' in OPERATING_MODEL.read_text(encoding="utf-8")


def test_no_order_path_exists_anywhere(closure: dict) -> None:
    runtime_text = RUNTIME_CFG.read_text(encoding="utf-8")
    exchange_text = EXCHANGE_CFG.read_text(encoding="utf-8")
    assert "live_trading_enabled: false" in runtime_text
    assert "sandbox: true" in exchange_text
    assert (STORAGE / "bot.db").exists() is False
    assert closure["absence_of_real_trades"]["no_real_trades"] is True
    assert closure["absence_of_real_trades"]["any_record_carries_an_order_or_fill_field"] is False
    assert closure["standing"]["runtime_mode"] == "paper"


def test_the_open_defects_are_declared_rather_than_absorbed(closure: dict) -> None:
    defects = closure["open_defects"]
    ids = {defect["id"] for defect in defects}
    assert {"TD-1", "TD-2", "ECO-1", "ECO-2"}.issubset(ids)
    for defect in defects:
        assert defect["status"] in (
            "OPEN_NOT_REPAIRED",
            "OPEN_BOUNDED",
            "OPEN_PARTIALLY_CLOSED",
            "UNKNOWN_NOT_RESOLVABLE_OFFLINE",
        )
        assert defect["scope"]
    bounded = next(defect for defect in defects if defect["id"] == "ECO-1")
    assert "one bounded window" in bounded["scope"]
    assert bounded["status"] != "OPEN_BOUNDED"  # only while no forward window existed
    assert "ST-6 monitor" in bounded["scope"]


def test_the_closure_adopts_the_forward_drift_evidence(closure: dict) -> None:
    block = closure["cost_drift_evidence"]
    status = read_json(REPO / "data" / "economic001" / "COST_DRIFT_STATUS.json")
    history = [
        json.loads(line)
        for line in (REPO / "data" / "economic001" / "COST_DRIFT_HISTORY.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert block["present"] is True
    assert block["windows"] == status["windows"] == len(history)
    assert block["verdict"] == status["verdict"]
    assert block["provisional"] == status["provisional"]
    assert block["orders_sent"] == 0 and block["credentials_used"] == 0
    assert [row["window_id"] for row in block["per_window"]] == [
        row["window_id"] for row in history
    ]
    assert block["assumption_holds_in_every_window_so_far"] is all(
        row["worst_spread_bps"] <= 1.0 for row in history
    )


def test_the_drift_thresholds_are_the_frozen_model_terms(closure: dict, model: dict) -> None:
    rule = closure["cost_drift_evidence"]["declared_rule"]
    spec = next(
        scenario["spec"]
        for scenario in model["scenarios"]
        if scenario["spec"]["scenario_id"] == "BINANCE_SPOT_STANDARD_TAKER"
    )
    assert rule["modelled_round_trip_spread_bps"] == spec["default_taker_spread_bps"] == 1.0
    assert rule["modelled_impact_bps"] == model["model_constants"]["base_impact_bps"] == 0.25
    assert rule["minimum_windows_for_a_stable_verdict"] >= 2
    assert closure["cost_drift_evidence"]["stop_rule"].startswith("stop collecting")


def test_eco1_is_partially_closed_and_says_so(closure: dict) -> None:
    defect = next(row for row in closure["open_defects"] if row["id"] == "ECO-1")
    assert defect["status"] == "OPEN_PARTIALLY_CLOSED"
    assert "cost_drift_monitor" in defect["this_gate"]
    assert "counted in units, not in regimes" in defect["scope"]
    assert closure["final_report"]["READ_ONLY_MARKET_DATA_STATUS"]["drift_windows"] >= 1


def test_the_verification_artefact_stays_inside_its_own_vocabulary(verification: dict) -> None:
    assert verification["verdict"] in VERDICTS
    assert verification["allowed_verdicts"] == list(VERDICTS)
    delivery = verification["closure_delivery_commit"]
    closure_head = verification["closure_head"]
    _, delivery_precedes = git("merge-base", "--is-ancestor", delivery, closure_head)
    assert delivery_precedes == 0
    _, head_precedes = git("merge-base", "--is-ancestor", closure_head, verification["head"])
    assert head_precedes == 0
    assert "library" in verification["method"] and "git blobs" in verification["method"]
