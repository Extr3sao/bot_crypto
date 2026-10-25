"""Tests for the ST-6 cost-drift monitor.

The monitor exists to be able to *fire*: a drift verdict invalidates the recommended cost profile,
so the interesting tests are the ones that prove the rule fires on worse data and stays silent on
the data we actually have.  Nothing here re-runs the collection or rewrites an artefact.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import statistics
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data" / "economic001"
HISTORY = DATA / "COST_DRIFT_HISTORY.jsonl"
STATUS = DATA / "COST_DRIFT_STATUS.json"
RAW_DIR = DATA / "drift_raw"
SNAPSHOT = DATA / "READ_ONLY_SNAPSHOT.json"
EXCHANGE_CFG = REPO / "config" / "exchange.yaml"
RUNTIME_CFG = REPO / "config" / "runtime.yaml"

MODELLED_SPREAD_BPS = 1.0
MODELLED_IMPACT_BPS = 0.25
BOUNDARY_MULTIPLE = 1.5
MIN_WINDOWS = 3
VERDICTS = (
    "WITHIN_MODELLED_ASSUMPTIONS",
    "AT_THE_MODELLED_BOUNDARY",
    "DRIFT_WIDER_THAN_MODELLED",
    "INSUFFICIENT_EVIDENCE",
)
COMPONENT_VALUES = ("WITHIN", "AT_BOUNDARY", "DRIFT", "INSUFFICIENT_EVIDENCE")
REQUIRED_FIELDS = (
    "window_id",
    "collected_at_utc",
    "provenance",
    "budget",
    "requests_made",
    "duration_s",
    "window_complete",
    "orders_sent",
    "credentials_used",
    "raw_path",
    "raw_sha256",
    "pooled_median_spread_bps",
    "worst_spread_bps",
    "per_symbol_median_spread_bps",
    "worst_walk_bps_at_account_size",
    "depth_covers_account_size",
    "latency_median_ms",
)


def load_module(name: str, relative: str) -> object:
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def monitor() -> object:
    return load_module("cost_drift_monitor", "scripts/cost_drift_monitor.py")


@pytest.fixture(scope="module")
def history() -> list[dict]:
    return [
        json.loads(line)
        for line in HISTORY.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture(scope="module")
def status() -> dict:
    return json.loads(STATUS.read_text(encoding="utf-8"))


def test_the_history_is_append_only_and_every_window_is_whole(history: list[dict]) -> None:
    assert history, "the monitor has never run"
    for record in history:
        assert set(REQUIRED_FIELDS).issubset(record), record["window_id"]
        assert record["window_complete"] is True
        assert record["budget"]["finite"] is True
        assert record["budget"]["declared_before_collection"] is True
        assert record["requests_made"] <= record["budget"]["requests_planned"]
    ids = [record["window_id"] for record in history]
    stamps = [record["collected_at_utc"] for record in history]
    assert len(set(ids)) == len(ids), ids
    assert stamps == sorted(stamps), stamps


def test_no_window_ever_sent_an_order_or_used_a_credential(history: list[dict]) -> None:
    for record in history:
        assert record["orders_sent"] == 0
        assert record["credentials_used"] == 0


def test_every_window_keeps_its_raw_bytes_and_the_hash_matches(history: list[dict]) -> None:
    for record in history:
        raw = REPO / record["raw_path"]
        assert raw.exists(), record["raw_path"]
        assert hashlib.sha256(raw.read_bytes()).hexdigest() == record["raw_sha256"]
        snapshot = json.loads(raw.read_text(encoding="utf-8"))
        assert snapshot["orders_sent"] == 0
        assert snapshot["credentials_used"] == 0
        assert snapshot["private_endpoints_called"] == []
        assert snapshot["endpoint_base"] == "https://api.binance.com"


def test_the_metrics_are_re_derived_from_the_raw_window(history: list[dict]) -> None:
    for record in history:
        snapshot = json.loads((REPO / record["raw_path"]).read_text(encoding="utf-8"))
        spreads: list[float] = []
        per_symbol: dict[str, list[float]] = {symbol: [] for symbol in snapshot["symbols"]}
        for row in snapshot["observations"]:
            for symbol, book in row["books"].items():
                spreads.append(book["spread_bps"])
                per_symbol[symbol].append(book["spread_bps"])
        assert record["pooled_median_spread_bps"] == pytest.approx(
            statistics.median(spreads), abs=1e-6
        )
        assert record["worst_spread_bps"] == pytest.approx(max(spreads), abs=1e-6)
        for symbol, values in per_symbol.items():
            assert record["per_symbol_median_spread_bps"][symbol] == pytest.approx(
                statistics.median(values), abs=1e-6
            )


def test_the_walk_arithmetic_agrees_with_the_closure(monitor: object, history: list[dict]) -> None:
    closure = load_module("economic001_closure_walk", "scripts/economic001_closure.py")
    for record in history:
        snapshot = json.loads((REPO / record["raw_path"]).read_text(encoding="utf-8"))
        for symbol in snapshot["symbols"]:
            asks = snapshot["observations"][0]["depth"][symbol]["asks"]
            mine = monitor._walk_bps(asks, 200.0)
            theirs = closure._vwap_cost(asks, 200.0)
            assert bool(theirs.get("filled")) is (mine is not None)
            if theirs.get("filled"):
                assert mine == pytest.approx(theirs["cost_bps"], abs=1e-9)
            else:
                assert mine is None  # one code path cannot disagree with the other


def test_the_status_verdict_re_derives_from_the_history(
    monitor: object, history: list[dict], status: dict
) -> None:
    recomputed = monitor.judge(history)
    assert status["verdict"] == recomputed["verdict"] in VERDICTS
    assert status["components"] == recomputed["components"]
    assert status["windows"] == len(history) == recomputed["windows"]
    assert status["provisional"] is (len(history) < MIN_WINDOWS)
    for value in status["components"].values():
        assert value in COMPONENT_VALUES


def test_the_status_is_a_clean_window_on_costs_and_admits_nothing(status: dict) -> None:
    assert status["false_success"] == 0
    assert status["orders_sent"] == 0
    assert status["credentials_used"] == 0
    assert status["declared_rule"]["modelled_round_trip_spread_bps"] == MODELLED_SPREAD_BPS
    assert status["declared_rule"]["modelled_impact_bps"] == MODELLED_IMPACT_BPS
    assert status["declared_rule"]["account_size_usdt"] == 200.0
    assert status["stop_rule"].startswith("stop collecting")
    assert len(status["does_not_license"]) >= 3


def test_the_kill_switch_fires_on_worse_data(monitor: object, history: list[dict]) -> None:
    """The rule must be able to reach DRIFT, or the monitor is decoration."""
    drifting = [dict(row) for row in history]
    for row in drifting:
        row["worst_spread_bps"] = 2.4
        row["pooled_median_spread_bps"] = 1.8
    fired = monitor.judge(drifting)
    assert fired["verdict"] == "DRIFT_WIDER_THAN_MODELLED"
    assert fired["components"]["spread"] == "DRIFT"

    boundary = [dict(row) for row in history]
    for row in boundary:
        row["worst_spread_bps"] = 1.2
        row["pooled_median_spread_bps"] = 0.9
    assert monitor.judge(boundary)["verdict"] == "AT_THE_MODELLED_BOUNDARY"

    deep = [dict(row) for row in history]
    for row in deep:
        row["worst_walk_bps_at_account_size"] = 0.9
    assert monitor.judge(deep)["verdict"] == "DRIFT_WIDER_THAN_MODELLED"


def test_a_within_verdict_needs_the_declared_minimum_of_windows(monitor: object) -> None:
    clean = {
        "window_id": "synthetic",
        "collected_at_utc": "2026-10-08T00:00:00Z",
        "pooled_median_spread_bps": 0.4,
        "worst_spread_bps": 0.9,
        "worst_walk_bps_at_account_size": 0.0,
        "depth_covers_account_size": True,
    }
    for count in range(1, MIN_WINDOWS + 1):
        judged = monitor.judge([dict(clean) for _ in range(count)])
        if count < MIN_WINDOWS:
            assert judged["provisional"] is True
            assert judged["verdict"] == "INSUFFICIENT_EVIDENCE"
        else:
            assert judged["provisional"] is False
            assert judged["verdict"] == "WITHIN_MODELLED_ASSUMPTIONS"


def test_the_monitor_cannot_trade_by_construction() -> None:
    runtime_text = RUNTIME_CFG.read_text(encoding="utf-8")
    exchange_text = EXCHANGE_CFG.read_text(encoding="utf-8")
    assert "live_trading_enabled: false" in runtime_text
    assert "sandbox: true" in exchange_text
    # Structural, not textual: a check that greps prose fails on the prose that documents it.
    source = (REPO / "scripts" / "cost_drift_monitor.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    called: set[str] = set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            called.add(getattr(func, "attr", None) or getattr(func, "id", ""))
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert not called & {"create_order", "cancel_order", "fetch_balance", "load_markets"}, called
    assert not any(name.startswith("ccxt") or "exchange_connector" in name for name in imported)
    assert "environ" not in called, called  # no environment credential can be read here
    assert (REPO / "data" / "storage" / "bot.db").exists() is False


def test_the_gate_snapshot_is_adopted_with_its_provenance(history: list[dict]) -> None:
    imported = [row for row in history if row["provenance"].startswith("ECONOMIC-001")]
    assert imported, "the closure's window was not adopted into the history"
    assert imported[0]["raw_path"].endswith("READ_ONLY_SNAPSHOT.json")
    assert imported[0]["budget"]["rounds"] == 5
    native = [row for row in history if row["provenance"] == "cost_drift_monitor"]
    assert native, "the monitor has never collected a window of its own"
    assert SNAPSHOT.exists()
