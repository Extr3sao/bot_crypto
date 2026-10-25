"""Tests for the ST-6 forward regime phase.

The phase exists to be able to *fire*: it must show a drift when the measured cost exceeds the
frozen model, and it must stay silent when it does not.  The interesting tests are therefore the
ones that push worse data through the declared rule, prove that a later round of a window is not
hidden by the first one, and prove that an incomplete period can never be reported as supported.

Nothing here re-runs the collection or rewrites a committed artefact.
"""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "st6"
PERIOD = DATA / "ST6_PERIOD.json"
WINDOWS = DATA / "ST6_WINDOWS.jsonl"
OBSERVATIONS = DATA / "ST6_OBSERVATIONS.jsonl"
COVERAGE = DATA / "ST6_REGIME_COVERAGE.json"
DRIFT = DATA / "ST6_MODEL_DRIFT.json"
REPORT = DATA / "ST6_FORWARD_REGIME_REPORT.json"
BUILDER = REPO / "scripts" / "st6_forward_regime.py"
VERIFIER = REPO / "scripts" / "st6_forward_regime_verify.py"
COST_MODEL = REPO / "docs" / "COST_MODEL_V3.json"

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
SPREAD_MODEL_BPS = 1.0
IMPACT_MODEL_BPS = 0.25
BOUNDARY_MULTIPLE = 1.5
OUTCOMES = (
    "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES",
    "COST_MODEL_DRIFT_DETECTED",
    "INSUFFICIENT_REGIME_COVERAGE",
    "DATA_QUALITY_FAILED",
)
CONTRACT_KEYS = (
    "run_id",
    "asset",
    "observed_at_utc",
    "exchange_time_ms",
    "exchange_time_utc",
    "exchange_timestamp_source",
    "bid",
    "ask",
    "spread_bps",
    "book_age_ms",
    "depth",
    "liquidity",
    "volatility",
    "market",
    "impact",
    "thresholds",
    "source",
    "raw",
    "stale",
    "rejected",
)
ROLLUP_KEYS = (
    "by_asset",
    "by_session",
    "by_day_type",
    "by_volatility_regime",
    "by_liquidity_band",
    "checks",
    "day_detail",
    "windows_per_day",
    "regime_statistics",
    "model_comparison",
    "spread_extremes",
    "impact_extremes",
)


def load_module(name: str, relative: str) -> object:
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def phase() -> object:
    return load_module("st6_forward_regime", "scripts/st6_forward_regime.py")


@pytest.fixture(scope="module")
def verifier() -> object:
    return load_module("st6_forward_regime_verify", "scripts/st6_forward_regime_verify.py")


def deep_book(mid: float = 100.0, spread_bps: float = 0.4) -> dict[str, list[list[float]]]:
    half = mid * spread_bps / 2.0 / 10_000.0
    return {
        "asks": [[mid + half, 1_000_000.0], [mid + half * 2, 1_000_000.0]],
        "bids": [[mid - half, 1_000_000.0], [mid - half * 2, 1_000_000.0]],
    }


def thin_book(mid: float = 100.0, spread_bps: float = 0.4) -> dict[str, list[list[float]]]:
    """A top level that cannot absorb the account size: the SOL case measured on 2026-10-08.

    The second level sits one spread away, which is what a real thin book looks like and which
    prices the walk far above the modelled impact term.
    """
    half = mid * spread_bps / 2.0 / 10_000.0
    step = mid * 2.0 / 10_000.0  # the next level sits two basis points away
    return {
        "asks": [[mid + half, 0.4], [mid + half + step, 1_000_000.0]],
        "bids": [[mid - half, 0.4], [mid - half - step, 1_000_000.0]],
    }


def snapshot(
    *,
    rounds: int = 3,
    spread_bps: float = 0.4,
    missing_book: tuple[int, str] | None = None,
    thin_round: tuple[int, str] | None = None,
    age_seconds: float = 2.0,
    failures: list[str] | None = None,
    started: str = "2026-10-08T16:00:00.000000Z",
) -> dict:
    base = datetime.strptime(started, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    observations = []
    for index in range(rounds):
        at = base + timedelta(seconds=index * age_seconds)
        books: dict[str, dict[str, float]] = {}
        depth: dict[str, dict[str, object]] = {}
        for symbol in SYMBOLS:
            if missing_book == (index, symbol):
                continue
            mid = 100.0
            half = mid * spread_bps / 2.0 / 10_000.0
            books[symbol] = {
                "bid": mid - half,
                "ask": mid + half,
                "mid": mid,
                "spread_abs": (mid + half) - (mid - half),
                "spread_bps": (mid + half) - (mid - half) and 2 * half / mid * 10_000.0,
            }
            levels = (
                thin_book(mid, spread_bps)
                if thin_round == (index, symbol)
                else deep_book(mid, spread_bps)
            )
            depth[symbol] = {
                "asks": levels["asks"],
                "bids": levels["bids"],
                "last_update_id": 100 + index,
            }
        observations.append(
            {
                "round": index,
                "local_utc": at.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "server_time_ms": (at.timestamp() - 0.01) * 1000.0,
                "clock_offset_ms": 8.0,
                "books": books,
                "depth": depth,
            }
        )
    return {
        "artifact": "ECONOMIC-001_READ_ONLY_SNAPSHOT",
        "endpoint_base": "https://api.binance.com",
        "symbols": list(SYMBOLS),
        "budget": {
            "rounds": rounds,
            "spacing_s": 5.0,
            "depth_limit": 100,
            "max_attempts_per_request": 2,
            "requests_planned": rounds * 6,
            "requests_made": rounds * 6,
            "finite": True,
            "declared_before_collection": True,
        },
        "duration_s": round(rounds * 5.0, 3),
        "latency_ms": {
            "samples": {"time": [30.0], "bookTicker": [40.0], "depth": [50.0]},
            "reading": "round-trip of the observation path",
        },
        "observations": observations,
        "failures": failures or [],
        "complete": not failures,
        "orders_sent": 0,
        "credentials_used": 0,
        "local_started_utc": started,
        # the probe closes its evidence about one spacing after its last round
        "local_finished_utc": (base + timedelta(seconds=rounds * age_seconds)).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        ),
    }


def synthetic_window(
    phase: object,
    tmp_path: Path,
    *,
    window_id: str,
    closed_at: datetime,
    spread_bps: float = 0.4,
    thin_round: tuple[int, str] | None = None,
    missing_book: tuple[int, str] | None = None,
    failures: list[str] | None = None,
    bands: dict[str, str] | None = None,
    age_seconds: float = 2.0,
    started: datetime | None = None,
) -> tuple[dict, list[dict]]:
    """One window's index row and its observation rows, built through the phase's own code."""
    # by default the window's own span ends exactly at the instant it is said to close, which is
    # what the real collector produces: the reference instant comes from the raw bytes
    default_start = closed_at - timedelta(seconds=3 * 2.0)
    snap = snapshot(
        spread_bps=spread_bps,
        thin_round=thin_round,
        missing_book=missing_book,
        failures=failures,
        age_seconds=age_seconds,
        started=(started or default_start).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    )
    payload = json.dumps(snap, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    path = tmp_path / f"{window_id}.json.gz"
    with gzip.GzipFile(filename="", mode="wb", fileobj=path.open("wb"), mtime=0) as handle:
        handle.write(payload)
    raw = {
        "window_id": window_id,
        "path": str(path),
        "encoding": "gzip",
        "uncompressed_bytes": len(payload),
        "uncompressed_sha256": hashlib.sha256(payload).hexdigest(),
        "compressed_bytes": path.stat().st_size,
        "compressed_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    volatility = {
        symbol: {
            "value_bps": 20.0,
            "regime": (bands or {}).get(symbol, "NORMAL"),
            "reference": "test archive",
        }
        for symbol in SYMBOLS
    }
    thresholds = phase.frozen_thresholds()
    rows = phase.build_observations(
        snap, window_id, f"run-{window_id}", volatility, raw, thresholds, closed_at
    )
    metrics = phase.window_metrics(snap)
    slot = phase.slot_of(closed_at)
    record = {
        "artifact": "ST6_FORWARD_WINDOW",
        "window_id": window_id,
        "run_id": f"run-{window_id}",
        "collected_at_utc": closed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "raw": raw,
        "budget": snap["budget"],
        "window_complete": snap["complete"],
        "failures": snap["failures"],
        "orders_sent": 0,
        "credentials_used": 0,
        **slot,
        **metrics,
        "worst_walk_bps_at_account_size": round(
            max(
                value
                for row in rows
                for value in (row["impact"].get("buy_bps"), row["impact"].get("sell_bps"))
                if isinstance(value, float)
            ),
            9,
        )
        if any(
            isinstance(value, float)
            for row in rows
            for value in (row["impact"].get("buy_bps"), row["impact"].get("sell_bps"))
        )
        else None,
        "depth_covers_account_size": all(
            row["impact"].get("filled_buy") and row["impact"].get("filled_sell")
            for row in rows
            if row["depth"].get("available")
        ),
        "worst_walk_bps_round_zero": metrics["worst_walk_bps_at_account_size"],
        "depth_covers_account_size_round_zero": metrics["depth_covers_account_size"],
        "freshness": phase.freshness_rule(snap, metrics),
        "assets_present": sorted({row["asset"] for row in rows if row["bid"] is not None}),
        "observations_written": len(rows),
        "rejected_observations": sum(1 for row in rows if row["rejected"]),
        "thresholds": {
            "spread_bps": thresholds["spread_bps"],
            "impact_bps": thresholds["impact_bps"],
            "source": thresholds["source"],
        },
    }
    return record, rows


def synthetic_period(phase: object, days: int = 14) -> dict:
    start = datetime(2026, 10, 8, 0, 0, 0, tzinfo=UTC)
    return {
        "artifact": "ST6_OBSERVATION_PERIOD",
        "started_at_utc": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ends_at_utc": (start + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "period_days": days,
        "slots": [
            f"{index * phase.SLOT_HOURS:02d}:00-{(index + 1) * phase.SLOT_HOURS:02d}:00 UTC"
            for index in range(phase.SLOTS_PER_DAY)
        ],
        "max_observations_per_day": phase.SLOTS_PER_DAY,
        "head_at_declaration": "0" * 40,
        "thresholds": phase.frozen_thresholds(),
        "does_not_license": ["a campaign", "capital", "live trading"],
    }


def full_coverage_windows(
    phase: object, tmp_path: Path, *, drift_window: bool = False
) -> tuple[list[dict], list[dict]]:
    """Fourteen days, six slots a day: the declared coverage rule satisfied."""
    windows: list[dict] = []
    rows: list[dict] = []
    start = datetime(2026, 10, 8, 0, 0, 0, tzinfo=UTC)
    for day in range(14):
        for slot in range(phase.SLOTS_PER_DAY):
            closed_at = start + timedelta(days=day, hours=slot * 4, minutes=30)
            window_id = closed_at.strftime("%Y%m%dT%H%M%SZ")
            thin = (1, "SOLUSDT") if drift_window and day == 0 and slot == 0 else None
            bands = {"BTCUSDT": "LOW", "ETHUSDT": "NORMAL", "SOLUSDT": "HIGH", "XRPUSDT": "NORMAL"}
            record, observations = synthetic_window(
                phase,
                tmp_path,
                window_id=window_id,
                closed_at=closed_at,
                thin_round=thin,
                bands=bands,
            )
            windows.append(record)
            rows.extend(observations)
    return windows, rows


# ------------------------------------------------------------------ thresholds and declarations


def test_thresholds_are_read_from_the_frozen_model(phase: object) -> None:
    thresholds = phase.frozen_thresholds()
    assert thresholds["spread_bps"] == SPREAD_MODEL_BPS
    assert thresholds["impact_bps"] == IMPACT_MODEL_BPS
    assert thresholds["source"] == "docs\\COST_MODEL_V3.json" or thresholds["source"].endswith(
        "COST_MODEL_V3.json"
    )
    assert thresholds["model_sha256"] == hashlib.sha256(COST_MODEL.read_bytes()).hexdigest()
    assert "never writes" in thresholds["declared"]


def test_thresholds_refuse_a_changed_model(phase: object, tmp_path: Path) -> None:
    model = json.loads(COST_MODEL.read_text(encoding="utf-8"))
    model["model_constants"]["base_slippage_bps"] = 2.0
    changed = tmp_path / "COST_MODEL_V3.json"
    changed.write_text(json.dumps(model), encoding="utf-8")
    with pytest.raises(phase.ModelMismatch):
        phase.frozen_thresholds(changed)


def test_the_slot_grid_covers_every_declared_session(phase: object) -> None:
    seen = {}
    for hour in range(24):
        moment = datetime(2026, 10, 8, hour, 0, tzinfo=UTC)
        slot = phase.slot_of(moment)
        seen[slot["slot_index"]] = slot["slot"]
        assert slot["session"] in ("asia", "europe", "us")
        assert slot["day_type"] == "weekday"
    assert len(seen) == phase.SLOTS_PER_DAY
    assert phase.session_of(datetime(2026, 10, 8, 3, tzinfo=UTC)) == "asia"
    assert phase.session_of(datetime(2026, 10, 8, 12, tzinfo=UTC)) == "europe"
    assert phase.session_of(datetime(2026, 10, 8, 20, tzinfo=UTC)) == "us"
    saturday = datetime(2026, 10, 10, 12, tzinfo=UTC)
    sunday = datetime(2026, 10, 11, 12, tzinfo=UTC)
    assert phase.day_type(saturday) == "weekend"
    assert phase.day_type(sunday) == "weekend"
    assert phase.slot_of(saturday)["day_type"] == "weekend"


def test_volatility_regimes_use_the_declared_tertiles(phase: object) -> None:
    reference = {"p33_bps": 10.0, "p67_bps": 20.0}
    assert phase.classify_volatility(9.9, reference) == "LOW"
    assert phase.classify_volatility(10.0, reference) == "LOW"
    assert phase.classify_volatility(15.0, reference) == "NORMAL"
    assert phase.classify_volatility(20.0, reference) == "NORMAL"
    assert phase.classify_volatility(20.1, reference) == "HIGH"


# ------------------------------------------------------------------ the walk and the contract


def test_walk_detail_matches_the_proven_monitor_arithmetic(phase: object) -> None:
    monitor = load_module("cost_drift_monitor", "scripts/cost_drift_monitor.py")
    cases = [
        ([[100.0, 1_000_000.0], [100.1, 1_000_000.0]], 200.0),
        ([[100.0, 0.4], [100.05, 1_000_000.0]], 200.0),
        ([[100.0, 0.4], [100.05, 1.0]], 200.0),
        ([[100.0, 1.0], [100.02, 0.5], [100.5, 10.0]], 150.0),
    ]
    for levels, notional in cases:
        mine = phase.walk_detail(levels, notional)
        theirs = monitor._walk_bps(levels, notional)
        if mine["filled"]:
            assert theirs is not None
            assert mine["walk_bps"] == pytest.approx(theirs, abs=1e-9)
        else:
            assert theirs is None


def test_the_thin_top_level_case_is_visible(phase: object) -> None:
    detail = phase.walk_detail(thin_book()["asks"], 200.0)
    assert detail["filled"] is True
    assert detail["levels_consumed"] >= 2
    assert detail["walk_bps"] > BOUNDARY_MULTIPLE * IMPACT_MODEL_BPS


def test_the_observation_contract_is_complete(phase: object, tmp_path: Path) -> None:
    closed_at = datetime(2026, 10, 8, 16, 30, tzinfo=UTC)
    _, rows = synthetic_window(phase, tmp_path, window_id="20261008T163000Z", closed_at=closed_at)
    assert rows
    for row in rows:
        assert set(CONTRACT_KEYS).issubset(row), sorted(set(CONTRACT_KEYS) - set(row))
        assert row["asset"] in SYMBOLS
        assert row["run_id"]
        assert row["observed_at_utc"]
        assert row["exchange_time_ms"] is not None
        assert row["exchange_time_utc"]
        assert "venue clock" in row["exchange_timestamp_source"]
        assert row["bid"] is not None and row["ask"] is not None
        assert row["spread_bps"] is not None
        assert row["depth"]["available"] is True
        assert row["liquidity"]["band"] in ("THIN", "NORMAL", "DEEP")
        assert row["volatility"]["regime"] in ("LOW", "NORMAL", "HIGH")
        assert row["market"]["session"] in ("asia", "europe", "us")
        assert row["market"]["day_type"] in ("weekday", "weekend")
        assert row["impact"]["size_usdt"] == 200.0
        assert row["thresholds"]["spread_bps"] == SPREAD_MODEL_BPS
        assert row["thresholds"]["impact_bps"] == IMPACT_MODEL_BPS
        assert row["raw"]["uncompressed_sha256"]
        assert row["freshness_limit_ms"] == row["declared_window_span_ms"] + (
            phase.MAX_BOOK_AGE_MARGIN_MS
        )
        assert row["stale"] is False and row["rejected"] is False


def test_the_freshness_limit_follows_the_declared_window_span(
    phase: object, tmp_path: Path
) -> None:
    closed_at = datetime(2026, 10, 8, 16, 30, tzinfo=UTC)
    _, rows = synthetic_window(phase, tmp_path, window_id="20261008T163010Z", closed_at=closed_at)
    span = 3 * 5.0 * 1000.0  # rounds x spacing of the synthetic budget
    limit = span + phase.MAX_BOOK_AGE_MARGIN_MS
    assert all(row["declared_window_span_ms"] == span for row in rows)
    assert all(row["freshness_limit_ms"] == limit for row in rows)
    assert all(row["stale"] is False for row in rows), [row["book_age_ms"] for row in rows]
    assert max(row["book_age_ms"] for row in rows) <= limit

    # a window whose rounds drifted far past its declared cadence is stale, and says so
    _, slow = synthetic_window(
        phase,
        tmp_path,
        window_id="20261008T163011Z",
        closed_at=closed_at,
        started=closed_at - timedelta(minutes=5),
        age_seconds=60.0,
    )
    assert all(row["stale"] for row in slow)
    assert all("exceeds the declared freshness limit" in row["stale_reason"] for row in slow)


def test_the_freshness_check_can_fail(phase: object, verifier: object, tmp_path: Path) -> None:
    """A check that cannot fail is not a check: push a wrong stale flag through it."""
    closed_at = datetime(2026, 10, 8, 16, 30, tzinfo=UTC)
    record, rows = synthetic_window(
        phase, tmp_path, window_id="20261008T163012Z", closed_at=closed_at
    )
    recomputed = {record["window_id"]: verifier.recompute_window(Path(record["raw"]["path"]))}
    checks = verifier.Checks()
    verifier.verify_freshness(checks, [record], rows, recomputed)
    assert checks.failed == [], checks.failed

    tampered = [dict(row) for row in rows]
    tampered[0] = {**tampered[0], "stale": True}
    broken = verifier.Checks()
    verifier.verify_freshness(broken, [record], tampered, recomputed)
    assert broken.failed, "the freshness check did not notice a contradicted stale flag"

    lying = [dict(row) for row in rows]
    lying[0] = {**lying[0], "freshness_limit_ms": 1.0}
    second = verifier.Checks()
    verifier.verify_freshness(second, [record], lying, recomputed)
    assert second.failed, "the freshness check did not notice a wrong limit"


def test_observations_do_not_duplicate_window_rollups(phase: object, tmp_path: Path) -> None:
    closed_at = datetime(2026, 10, 8, 16, 30, tzinfo=UTC)
    _, rows = synthetic_window(phase, tmp_path, window_id="20261008T163001Z", closed_at=closed_at)
    for row in rows:
        for key in ROLLUP_KEYS:
            assert key not in row, f"{key} duplicated inside an observation event"


def test_incomplete_and_stale_windows_are_recorded_not_dropped(
    phase: object, tmp_path: Path
) -> None:
    closed_at = datetime(2026, 10, 8, 16, 30, tzinfo=UTC)
    record, rows = synthetic_window(
        phase,
        tmp_path,
        window_id="20261008T163002Z",
        closed_at=closed_at,
        missing_book=(0, "XRPUSDT"),
        failures=["round 1 depth SOLUSDT: timeout"],
        started=closed_at - timedelta(hours=1),
        age_seconds=60.0,
    )
    assert record["window_complete"] is False
    assert record["failures"]
    missing = [row for row in rows if row["asset"] == "XRPUSDT" and row["round"] == 0]
    assert missing and missing[0]["rejected"] is True
    assert missing[0]["rejected_reason"]
    assert missing[0]["stale"] is True
    # every observation of this window is stale because the books age past the declared maximum
    assert all(row["stale"] for row in rows)
    assert record["rejected_observations"] == sum(1 for row in rows if row["rejected"]) == len(rows)
    assert len(rows) == 12  # nothing was dropped: 3 rounds x 4 assets


# ------------------------------------------------------------------ the rule, and hiding extremes


def test_the_rule_sees_a_breach_in_a_later_round(phase: object, tmp_path: Path) -> None:
    """Regression: the monitor's own window metric prices the walk from round zero only."""
    closed_at = datetime(2026, 10, 8, 16, 30, tzinfo=UTC)
    record, rows = synthetic_window(
        phase,
        tmp_path,
        window_id="20261008T163003Z",
        closed_at=closed_at,
        thin_round=(2, "SOLUSDT"),
    )
    assert record["worst_walk_bps_round_zero"] == 0.0, record["worst_walk_bps_round_zero"]
    assert record["worst_walk_bps_at_account_size"] > BOUNDARY_MULTIPLE * IMPACT_MODEL_BPS
    statistics_ = phase.regime_statistics(rows)
    drift = phase.drift_document(synthetic_period(phase), [record], rows, statistics_)
    assert drift["st6_components"]["impact"] == "DRIFT"
    assert drift["st6_window_verdict"] == "DRIFT_WIDER_THAN_MODELLED"
    assert drift["drift_detected"] is True
    breach = [entry for entry in drift["breaches"] if entry["kind"].startswith("impact")]
    assert breach, drift["breaches"]
    assert breach[0]["asset"] == "SOLUSDT"
    assert breach[0]["context"]["size_usdt"] == 200.0
    assert drift["what_the_rule_saw"][0]["worst_walk_bps_at_account_size"] > 0.0


def test_a_clean_window_stays_within_the_model(phase: object, tmp_path: Path) -> None:
    closed_at = datetime(2026, 10, 8, 16, 30, tzinfo=UTC)
    record, rows = synthetic_window(
        phase, tmp_path, window_id="20261008T163004Z", closed_at=closed_at
    )
    statistics_ = phase.regime_statistics(rows)
    drift = phase.drift_document(synthetic_period(phase), [record], rows, statistics_)
    assert drift["st6_components"] == {"spread": "WITHIN", "impact": "WITHIN", "depth": "WITHIN"}
    assert drift["breaches_total"] == 0
    assert drift["drift_detected"] is False
    assert drift["st6_provisional"] is True  # one window is never a stable verdict


def test_a_wide_spread_reaches_drift(phase: object, tmp_path: Path) -> None:
    closed_at = datetime(2026, 10, 8, 16, 30, tzinfo=UTC)
    record, rows = synthetic_window(
        phase,
        tmp_path,
        window_id="20261008T163005Z",
        closed_at=closed_at,
        spread_bps=2.0,
    )
    statistics_ = phase.regime_statistics(rows)
    drift = phase.drift_document(synthetic_period(phase), [record], rows, statistics_)
    assert drift["st6_components"]["spread"] == "DRIFT"
    assert drift["drift_detected"] is True
    assert (
        statistics_["overall"]["spread_bps"]["over_model"]
        == statistics_["overall"]["spread_bps"]["n"]
    )


# ------------------------------------------------------------------ coverage and the outcome


def test_coverage_is_checked_not_assumed(phase: object, tmp_path: Path) -> None:
    period = synthetic_period(phase)
    empty = phase.coverage_document(period, [], [])
    assert empty["coverage_complete"] is False
    assert empty["coverage_token"] == "REGIME_COVERAGE_INSUFFICIENT"
    assert empty["missing"], "an empty period must name what is missing"
    conditions = {entry["condition"] for entry in empty["missing"]}
    assert any("days_covered" in name for name in conditions)
    assert any("slots" in name for name in conditions)

    closed_at = datetime(2026, 10, 8, 16, 30, tzinfo=UTC)
    record, rows = synthetic_window(
        phase, tmp_path, window_id="20261008T163006Z", closed_at=closed_at
    )
    one = phase.coverage_document(period, [record], rows)
    assert one["coverage_complete"] is False
    assert one["observed_windows"] == 1
    assert len(one["day_detail"]) == period["period_days"] + 1


def test_full_coverage_satisfies_every_declared_condition(phase: object, tmp_path: Path) -> None:
    period = synthetic_period(phase)
    windows, rows = full_coverage_windows(phase, tmp_path)
    coverage = phase.coverage_document(period, windows, rows)
    assert coverage["coverage_complete"] is True, coverage["missing"]
    assert coverage["coverage_token"] == "REGIME_COVERAGE_SUFFICIENT"
    assert coverage["observed_windows"] == 14 * phase.SLOTS_PER_DAY
    assert len(coverage["regimes_identified"]["volatility_bands"]) == 3
    assert all(entry["satisfied"] for entry in coverage["checks"].values())


def test_outcome_vocabulary_and_ordering(phase: object, tmp_path: Path) -> None:
    period = synthetic_period(phase)

    # 1. an open period with nothing collected is insufficient, never failed
    coverage = phase.coverage_document(period, [], [])
    drift = phase.drift_document(period, [], [], phase.regime_statistics([]))
    outcome = phase.outcome_document(period, coverage, drift, [], [])
    assert outcome["outcome"] == "INSUFFICIENT_REGIME_COVERAGE"
    assert outcome["outcome"] in OUTCOMES
    assert outcome["no_observations_yet"] is True

    # 2. an open period that already measured a breach reports the breach, not a PASS
    closed_at = datetime(2026, 10, 8, 16, 30, tzinfo=UTC)
    record, rows = synthetic_window(
        phase,
        tmp_path,
        window_id="20261008T163007Z",
        closed_at=closed_at,
        thin_round=(2, "SOLUSDT"),
    )
    coverage = phase.coverage_document(period, [record], rows)
    statistics_ = phase.regime_statistics(rows)
    drift = phase.drift_document(period, [record], rows, statistics_)
    outcome = phase.outcome_document(period, coverage, drift, [record], rows)
    assert outcome["outcome"] == "INSUFFICIENT_REGIME_COVERAGE"
    assert outcome["drift_observed_so_far"] is True
    assert "drift breach" in outcome["outcome_basis"]
    assert outcome["eco_1"].startswith("OPEN")

    # 3. a complete period with no breach is the only route to the supported verdict
    windows, rows = full_coverage_windows(phase, tmp_path)
    coverage = phase.coverage_document(period, windows, rows)
    statistics_ = phase.regime_statistics(rows)
    drift = phase.drift_document(period, windows, rows, statistics_)
    outcome = phase.outcome_document(period, coverage, drift, windows, rows)
    assert outcome["outcome"] == "COST_MODEL_SUPPORTED_IN_OBSERVED_REGIMES"
    assert outcome["eco_1"] == "CLOSED_WITHIN_OBSERVED_REGIMES"
    assert "only" in outcome["outcome_basis"]

    # 4. a complete period with a breach is drift
    windows, rows = full_coverage_windows(phase, tmp_path, drift_window=True)
    coverage = phase.coverage_document(period, windows, rows)
    statistics_ = phase.regime_statistics(rows)
    drift = phase.drift_document(period, windows, rows, statistics_)
    outcome = phase.outcome_document(period, coverage, drift, windows, rows)
    assert drift["drift_detected"] is True
    assert outcome["outcome"] == "COST_MODEL_DRIFT_DETECTED"
    assert outcome["eco_1"].startswith("OPEN")

    # 5. evidence that does not reproduce is a data-quality failure
    broken = dict(record)
    broken["raw"] = dict(record["raw"])
    broken["raw"]["uncompressed_sha256"] = "0" * 64
    coverage = phase.coverage_document(period, [broken], rows)
    statistics_ = phase.regime_statistics(rows)
    drift = phase.drift_document(period, [broken], rows, statistics_)
    outcome = phase.outcome_document(period, coverage, drift, [broken], rows)
    assert outcome["outcome"] == "DATA_QUALITY_FAILED"
    assert outcome["evidence_failures"]
    assert outcome["false_success"] == 0


def test_the_report_keeps_every_standing_limit(phase: object, tmp_path: Path) -> None:
    period = synthetic_period(phase)
    thresholds = phase.frozen_thresholds()
    closed_at = datetime(2026, 10, 8, 16, 30, tzinfo=UTC)
    record, rows = synthetic_window(
        phase, tmp_path, window_id="20261008T163008Z", closed_at=closed_at
    )
    coverage = phase.coverage_document(period, [record], rows)
    statistics_ = phase.regime_statistics(rows)
    drift = phase.drift_document(period, [record], rows, statistics_)
    outcome = phase.outcome_document(period, coverage, drift, [record], rows)
    report = phase.build_report(
        period, coverage, drift, outcome, statistics_, [record], rows, thresholds
    )
    standing = report["standing_state"]
    assert standing["DISCOVERY_CAMPAIGN_FAILED"] is True
    assert standing["NEXT_CAMPAIGN"] == "NOT_AUTHORIZED"
    assert standing["TRADES_AUTHORIZED"] == 0
    assert standing["LIVE_TRADING"] == "DISABLED"
    assert standing["PROFITABILITY_VERIFIED"] is False
    assert standing["ECO_2"] == "UNKNOWN_NOT_RESOLVABLE_OFFLINE"
    assert report["assets_observed"] == sorted(SYMBOLS)
    assert report["orders_sent"] == 0
    assert report["credentials_used"] == 0
    assert report["false_success"] == 0
    assert report["scheduler"]["daemon_created"] is False
    assert report["scheduler"]["trading_scheduler_touched"] is False
    markdown = phase._render_markdown(report)
    assert "ECO-2" in markdown
    assert "does not license" in markdown
    assert report["does_not_license"]
    for token in ("EDGE_CONFIRMED", "PROFITABLE", "READY_FOR_LIVE"):
        assert token not in markdown


def test_the_period_is_declared_once_and_never_extended_silently(phase: object) -> None:
    period = json.loads(PERIOD.read_text(encoding="utf-8"))
    assert period["period_days"] == 14
    assert period["slots_per_day"] == 6
    assert period["one_window_per_slot"] is True
    assert period["coverage_rule"]["minimum_windows_total"] == 42
    assert period["thresholds"]["spread_bps"] == SPREAD_MODEL_BPS
    assert period["thresholds"]["impact_bps"] == IMPACT_MODEL_BPS
    assert "not prolonged automatically" in period["extension_policy"]
    start = datetime.strptime(period["started_at_utc"], "%Y-%m-%dT%H:%M:%SZ")
    end = datetime.strptime(period["ends_at_utc"], "%Y-%m-%dT%H:%M:%SZ")
    assert (end - start).days == 14


def test_no_order_or_credential_path_can_be_seen_by_the_ast_scan(
    phase: object, verifier: object
) -> None:
    source = BUILDER.read_text(encoding="utf-8")
    assert verifier.order_path_tokens(source) == []
    assert verifier.order_path_tokens("client.create_order(symbol, side)") == ["create_order"]
    assert verifier.order_path_tokens("key = api_key") == ["api_key"]
    assert verifier.order_path_tokens("x = 1") == []
    assert "ccxt" not in source
    assert "import requests" not in source


# ------------------------------------------------------------------ the committed artefacts


def test_the_committed_artefacts_are_coherent() -> None:
    period = json.loads(PERIOD.read_text(encoding="utf-8"))
    windows = [
        json.loads(line)
        for line in WINDOWS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    observations = [
        json.loads(line)
        for line in OBSERVATIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    drift = json.loads(DRIFT.read_text(encoding="utf-8"))
    report = json.loads(REPORT.read_text(encoding="utf-8"))

    assert windows, "the phase has never collected a window"
    for window in windows:
        raw = Path(window["raw"]["path"])
        if not raw.is_absolute():
            raw = REPO / raw
        assert raw.exists(), window["raw"]["path"]
        with gzip.open(raw, "rb") as handle:
            assert hashlib.sha256(handle.read()).hexdigest() == window["raw"]["uncompressed_sha256"]
        assert window["orders_sent"] == 0 and window["credentials_used"] == 0
        assert window["thresholds"]["spread_bps"] == SPREAD_MODEL_BPS
        assert window["thresholds"]["impact_bps"] == IMPACT_MODEL_BPS
        assert window["collected_at_utc"].endswith("Z")
        assert window["freshness"]["freshness_limit_ms"] > 0
    # every recorded book age is a real, non-negative age and follows the declared limit
    for row in observations:
        if row.get("book_age_ms") is None:
            continue
        assert row["book_age_ms"] >= 0.0, row
        assert row["stale"] == (row["book_age_ms"] > row["freshness_limit_ms"]), row
    # the raw instants reproduce the age of every observation
    for window in windows:
        raw = Path(window["raw"]["path"])
        if not raw.is_absolute():
            raw = REPO / raw
        with gzip.open(raw, "rb") as handle:
            snapshot = json.loads(handle.read().decode("utf-8"))
        finished = datetime.strptime(
            snapshot["local_finished_utc"].split(".")[0], "%Y-%m-%dT%H:%M:%S"
        ).replace(tzinfo=UTC)
        for row in [r for r in observations if r["window_id"] == window["window_id"]]:
            observed = datetime.strptime(
                row["observed_at_utc"].split(".")[0], "%Y-%m-%dT%H:%M:%S"
            ).replace(tzinfo=UTC)
            expected = (finished - observed).total_seconds() * 1000.0
            assert abs(row["book_age_ms"] - expected) <= 1000.0, (row, expected)
    assert report["outcome"] in OUTCOMES
    assert coverage["coverage_token"] in (
        "REGIME_COVERAGE_SUFFICIENT",
        "REGIME_COVERAGE_INSUFFICIENT",
    )
    # one window cannot satisfy the declared rule, and the reports say so
    assert coverage["coverage_complete"] is False
    assert report["outcome"] == "INSUFFICIENT_REGIME_COVERAGE"
    assert report["eco_2"] == "UNKNOWN_NOT_RESOLVABLE_OFFLINE"
    assert report["false_success"] == 0
    assert drift["st6_components"]["spread"] == "WITHIN"
    assert observations and all("run_id" in row for row in observations)
    assert len(observations) == sum(window["observations_written"] for window in windows)
    assert len({(window["day"], window["slot_index"]) for window in windows}) == len(windows)
    assert period["head_at_declaration"]


def test_the_independent_verifier_passes_without_rewriting_the_committed_artefact(
    tmp_path: Path,
) -> None:
    out = tmp_path / "verification.json"
    md_out = tmp_path / "verification.md"
    result = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--out",
            str(out),
            "--md-out",
            str(md_out),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["status"] == "PASS"
    assert document["mismatches"] == 0
    assert document["false_success"] == 0
    assert document["builder_equals_verifier"] is False
    assert document["checks_total"] == document["checks_passed"]
    assert document["builder"] == "scripts/st6_forward_regime.py"
    assert document["verifier"] == "scripts/st6_forward_regime_verify.py"
    assert document["raw_windows_verified"]
