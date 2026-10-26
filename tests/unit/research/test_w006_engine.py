"""Regression tests for the WP-006 engine repairs (``scripts/multi_family_backtest.py``).

These tests use synthetic bars on purpose: they verify arithmetic, causality and
refusal behaviour, never profitability. The economic evaluation runs on the real
exchange data named by the manifest.

Each test names the defect it holds closed:

* ``D1`` no data may not become a result with exit 0;
* ``D2`` a family exception must survive as a failure, not as "no signals";
* ``D3`` ``net = gross - spread - slippage - fees`` per trade, and ``gross`` does not
  move when slippage does;
* ``D4`` partitions are chronological and independent of filenames;
* ``D5`` a signal fills at the next bar's open, never at its own close;
* ``D6`` equity is marked to market while a position is open.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from pathlib import Path
from statistics import mean
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
T0 = 1_600_000_000_000
STEP = 300_000


def load_engine():
    path = ROOT / "scripts" / "multi_family_backtest.py"
    spec = importlib.util.spec_from_file_location("multi_family_engine_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def engine():
    return load_engine()


def make_bars(n: int = 260, start: int = T0, close_fn=None) -> list[dict]:
    """Deterministic bars whose OHLC bracket each other; no randomness anywhere."""
    bars = []
    for i in range(n):
        close = close_fn(i) if close_fn else 100.0 + 10.0 * math.sin(i / 9.0) + 0.02 * i
        op = close + 0.10 * math.cos(i / 3.0)
        hi = max(op, close) + 0.40
        lo = min(op, close) - 0.40
        bars.append({"ts": start + i * STEP, "open": round(op, 4), "high": round(hi, 4),
                     "low": round(lo, 4), "close": round(close, 4), "volume": 5.0})
    return bars


def write_manifest(tmp_path: Path, series: dict[str, list[dict]]) -> Path:
    data = tmp_path / "data"
    (data / "datasets").mkdir(parents=True, exist_ok=True)
    entries = {}
    for symbol, bars in series.items():
        payload = json.dumps(bars, separators=(",", ":")).encode("utf-8") + b"\n"
        rel = f"datasets/{symbol}_5m.json"
        (data / rel).write_bytes(payload)
        entries[symbol] = {"path": rel, "sha256": hashlib.sha256(payload).hexdigest(),
                           "bars": len(bars)}
    manifest = {"schema": "W006_MARKET_DATA_MANIFEST_V1",
                "fetched_at_utc": "2026-10-25T00:00:00+00:00", "datasets": entries}
    path = data / "MANIFEST.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


class StubFamily:
    """Emits one signal on each requested bar index (index = (ts - T0) // STEP)."""

    def __init__(self, signal_indices, direction=1, stop_pct=1.0, seen_windows=None):
        self.signal_indices = set(signal_indices)
        self.direction = direction
        self.stop_pct = stop_pct
        self.seen_windows = seen_windows if seen_windows is not None else []

    def _compute_indicators(self, ohlcv):
        self.seen_windows.append([b.timestamp for b in ohlcv])
        return {}

    def generate(self, ohlcv, indicators, ctx):
        index = (ohlcv[-1].timestamp - T0) // STEP
        if index not in self.signal_indices:
            return []
        close = ohlcv[-1].close
        stop = close * (1 - self.direction * self.stop_pct / 100.0)
        return [SimpleNamespace(direction="LONG" if self.direction == 1 else "SHORT",
                                entry_reference=close, effective_stop=stop,
                                structural_stop=stop)]


class ExplodingFamily(StubFamily):
    def _compute_indicators(self, ohlcv):
        raise RuntimeError("indicator failure for the test")


def register(engine, name: str, family) -> str:
    engine.FAMILIES[name] = family
    engine.MIN_BARS[name] = 5
    return name


def results_of(out: Path) -> dict:
    return json.loads((out / "MULTI_FAMILY_RESULTS.json").read_text(encoding="utf-8"))


def run_probe(engine, tmp_path, family, *, scenarios=("BASE",), symbols=("SYM",),
              bars=None, out_name="out") -> tuple[Path, dict]:
    bars = bars or make_bars()
    manifest = write_manifest(tmp_path, {s: bars for s in symbols})
    out = tmp_path / out_name
    record = engine.run(manifest, out, list({family}), scenarios, list(symbols))
    return out, record


# --------------------------------------------------------------------------- #
# D1 - no data is not a result


def test_a_missing_manifest_is_no_data_and_writes_no_results(engine, tmp_path):
    out = tmp_path / "out"
    record = engine.run(tmp_path / "absent.json", out)
    assert record["status"] == "NO_DATA"
    assert (out / "MULTI_FAMILY_RUN.json").is_file(), "the refusal itself must be recorded"
    assert not (out / "MULTI_FAMILY_RESULTS.json").exists(), "D1: no results artifact without data"


def test_a_tampered_dataset_is_refused_before_any_evaluation(engine, tmp_path):
    manifest = write_manifest(tmp_path, {"SYM": make_bars()})
    dataset = tmp_path / "data" / "datasets" / "SYM_5m.json"
    dataset.write_bytes(dataset.read_bytes().replace(b'"volume":5.0', b'"volume":6.0', 1))
    out = tmp_path / "out"
    record = engine.run(manifest, out)
    assert record["status"] == "NO_DATA"
    assert "digest mismatch" in record["reason"]
    assert not (out / "MULTI_FAMILY_RESULTS.json").exists()


def test_the_cli_exit_code_distinguishes_no_data_from_success(engine, tmp_path):
    assert engine.main(["--manifest", str(tmp_path / "absent.json"),
                        "--out", str(tmp_path / "o1")]) == 2
    manifest = write_manifest(tmp_path, {"SYM": make_bars()})
    register(engine, "quiet", StubFamily(signal_indices=[]))
    assert engine.main(["--manifest", str(manifest), "--out", str(tmp_path / "o2"),
                        "--families", "quiet", "--scenarios", "BASE"]) == 0


# --------------------------------------------------------------------------- #
# D2 - a failure stays visible


def test_a_failing_family_blocks_the_results_artifact(engine, tmp_path):
    register(engine, "exploding", ExplodingFamily(signal_indices=[100]))
    out = tmp_path / "out"
    record = engine.run(write_manifest(tmp_path, {"SYM": make_bars()}), out,
                        ["exploding"], ("BASE",), ["SYM"])
    assert record["status"] == "INCOMPLETE"
    assert not (out / "MULTI_FAMILY_RESULTS.json").exists(), "D2: no results for an incomplete run"
    failure = record["failures"][0]
    assert failure["error_type"] == "RuntimeError"
    assert "indicator failure" in failure["error"]
    assert "_compute_indicators" in failure["traceback"]
    assert failure["bar_ts"] >= T0


def test_a_failure_is_not_indistinguishable_from_no_signals(engine, tmp_path):
    register(engine, "quiet2", StubFamily(signal_indices=[]))
    quiet_out, quiet = run_probe(engine, tmp_path, "quiet2", out_name="quiet")
    assert quiet["status"] == "OK"
    register(engine, "exploding2", ExplodingFamily(signal_indices=[100]))
    explode_out, explode = run_probe(engine, tmp_path, "exploding2", out_name="explode")
    assert explode["status"] == "INCOMPLETE"
    assert quiet["status"] != explode["status"], "the two outcomes must be distinguishable"


def test_the_cli_exits_three_on_an_incomplete_run(engine, tmp_path):
    register(engine, "exploding3", ExplodingFamily(signal_indices=[100]))
    manifest = write_manifest(tmp_path, {"SYM": make_bars()})
    assert engine.main(["--manifest", str(manifest), "--out", str(tmp_path / "o"),
                        "--families", "exploding3", "--scenarios", "BASE"]) == 3


# --------------------------------------------------------------------------- #
# D5 - fills happen after the signal, never at it


def test_a_signal_fills_at_the_next_bar_open(engine, tmp_path):
    import csv

    bars = make_bars()
    signal_index = 100
    register(engine, "nextbar", StubFamily(signal_indices=[signal_index]))
    manifest = write_manifest(tmp_path, {"SYM": bars})
    out = tmp_path / "out"
    engine.run(manifest, out, ["nextbar"], ("BASE",), ["SYM"], dump_trades=True)
    with (out / "TRADES.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    row = rows[0]
    assert int(row["entry_signal_ts"]) == bars[signal_index]["ts"]
    assert int(row["entry_bar_ts"]) == bars[signal_index + 1]["ts"], "D5: filled one bar later"
    assert float(row["entry_ref"]) == pytest.approx(bars[signal_index + 1]["open"])
    assert int(row["entry_signal_ts"]) < int(row["entry_bar_ts"])
    payload = results_of(out)
    assert payload["results"]["nextbar"]["BASE"]["totals"]["reconciled"] is True


def test_the_signal_window_never_includes_a_future_bar(engine, tmp_path):
    seen: list[list[int]] = []
    register(engine, "pit", StubFamily(signal_indices=[120], seen_windows=seen))
    run_probe(engine, tmp_path, "pit")
    assert seen, "the family must have been asked for a signal"
    starts = [w[-1] for w in seen]
    for window in seen:
        assert len(window) <= engine.WINDOW
        assert window == sorted(window)
    # every call is made on the close of the bar it names: the last element is the bar,
    # and no earlier call can have been made with a later bar
    assert starts == sorted(starts)


# --------------------------------------------------------------------------- #
# D3 - costs are separable and reconcile


def test_each_trade_reconciles_gross_minus_costs(engine, tmp_path):
    register(engine, "costs", StubFamily(signal_indices=[100, 140, 180]))
    manifest = write_manifest(tmp_path, {"SYM": make_bars()})
    out = tmp_path / "out"
    engine.run(manifest, out, ["costs"], ("BASE",), ["SYM"], dump_trades=True)
    import csv
    with (out / "TRADES.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows
    for row in rows:
        gross = float(row["gross_pnl"])
        costs = float(row["spread_cost"]) + float(row["slippage_cost"]) + float(row["fees"])
        assert float(row["net_pnl"]) == pytest.approx(gross - costs, abs=1e-6), row


def test_gross_pnl_does_not_move_when_slippage_moves(engine, tmp_path):
    register(engine, "costs2", StubFamily(signal_indices=[100, 140, 180]))
    out, _ = run_probe(engine, tmp_path, "costs2",
                       scenarios=("BASE", "STRESSED_SLIPPAGE", "ZERO_COST"))
    base = results_of(out)["results"]["costs2"]
    assert base["BASE"]["totals"]["gross_pnl"] == pytest.approx(
        base["STRESSED_SLIPPAGE"]["totals"]["gross_pnl"], abs=1e-6)
    assert base["BASE"]["totals"]["gross_pnl"] == pytest.approx(
        base["ZERO_COST"]["totals"]["gross_pnl"], abs=1e-6)
    assert base["STRESSED_SLIPPAGE"]["totals"]["slippage_cost"] == pytest.approx(
        5 * base["BASE"]["totals"]["slippage_cost"], abs=1e-6)
    assert base["STRESSED_SLIPPAGE"]["totals"]["net_pnl"] < base["BASE"]["totals"]["net_pnl"]


def test_fees_are_charged_once_per_leg(engine, tmp_path):
    register(engine, "costs3", StubFamily(signal_indices=[100, 140]))
    manifest = write_manifest(tmp_path, {"SYM": make_bars()})
    out = tmp_path / "out"
    engine.run(manifest, out, ["costs3"], ("BASE",), ["SYM"], dump_trades=True)
    import csv
    with (out / "TRADES.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        entry_notional = float(row["entry_ref"]) * float(row["qty"])
        exit_notional = float(row["exit_ref"]) * float(row["qty"])
        expected = (entry_notional + exit_notional) * 5.0 / 1e4
        assert float(row["fees"]) == pytest.approx(expected, rel=1e-6), row


def test_the_cost_model_fill_matches_its_own_bps(engine):
    model = engine.CostModel(fees_bps=5.0, slippage_bps=1.0, half_spread_bps=2.0)
    leg = model.leg(100.0, 2.0, direction=1)
    assert leg["fill"] == pytest.approx(100.0 * (1 + (2.0 + 1.0) / 1e4))
    assert leg["spread"] == pytest.approx(200.0 * 2.0 / 1e4)
    assert leg["slippage"] == pytest.approx(200.0 * 1.0 / 1e4)
    assert leg["fees"] == pytest.approx(200.0 * 5.0 / 1e4)


# --------------------------------------------------------------------------- #
# D4 - partitions are chronological and filename-independent


def test_partitions_are_monotone_and_cover_the_range(engine):
    bars = make_bars()
    partitions = engine.compute_partitions({"A": bars, "B": bars})
    t0, dev_end, val_end, t1 = (partitions["t0"], partitions["dev_end"],
                                partitions["val_end"], partitions["t1"])
    assert t0 < dev_end < val_end < t1
    assert partitions["classify"](t0) == "DEV"
    assert partitions["classify"](dev_end) == "VAL"
    assert partitions["classify"](val_end) == "OOS"
    assert partitions["classify"](t1 - 1) == "OOS"
    assert partitions["coverage_mismatch"] == {}


def test_partitions_do_not_depend_on_dataset_names(engine, tmp_path):
    bars = make_bars()
    register(engine, "naming", StubFamily(signal_indices=[100, 150, 200, 240]))
    out_a, _ = run_probe(engine, tmp_path, "naming", symbols=("AAAA",), bars=bars, out_name="a")
    out_b, _ = run_probe(engine, tmp_path, "naming", symbols=("ZZZZ",), bars=bars, out_name="b")
    a = results_of(out_a)["results"]["naming"]["BASE"]
    b = results_of(out_b)["results"]["naming"]["BASE"]
    for partition in ("DEV", "VAL", "OOS"):
        assert a[partition]["trades"] == b[partition]["trades"]
        assert a[partition]["net_pnl"] == pytest.approx(b[partition]["net_pnl"], abs=1e-9)
    assert results_of(out_a)["partitions"]["boundaries_ms"] == \
        results_of(out_b)["partitions"]["boundaries_ms"]


def test_a_partition_gap_is_published_not_hidden(engine, tmp_path):
    full = make_bars()
    short = full[:200]
    register(engine, "partition_gap", StubFamily(signal_indices=[100]))
    manifest = write_manifest(tmp_path, {"FULL": full, "SHORT": short})
    out = tmp_path / "out"
    record = engine.run(manifest, out, ["partition_gap"], ("BASE",), ["FULL", "SHORT"])
    assert record["status"] in {"OK", "INCOMPLETE"}
    partitions = json.loads((out / "MULTI_FAMILY_RUN.json").read_text(encoding="utf-8"))["partitions"]
    assert "SHORT" in partitions["coverage_mismatch"], "partial coverage must be declared"


# --------------------------------------------------------------------------- #
# D6 - equity includes open positions


def test_drawdown_sees_the_open_position(engine, tmp_path):
    # falls while the position is open and never closes it: a realised-only curve would
    # stay flat, so any drawdown must come from the mark-to-market path
    def close_fn(i: int) -> float:
        if i < 110:
            return 100.0
        if i < 150:
            return 100.0 - (i - 110) * 0.11
        return 96.0 if i < 240 else 100.5

    bars = make_bars(close_fn=close_fn)
    register(engine, "drawdown", StubFamily(signal_indices=[100], stop_pct=50.0))
    partitions = engine.compute_partitions({"SYM": bars})
    result = engine.simulate_family("drawdown", "SYM", bars, engine.CostModel(), partitions,
                                    family=engine.FAMILIES["drawdown"])
    curve = [eq for _, eq in result["equity_curve"]]
    assert len(result["trades"]) == 1  # closed at end_of_data, not by the stop
    assert result["max_dd_pct_realized"] == 0.0, "nothing was realised in drawdown"
    assert min(curve) < engine.START_EQUITY - 0.5, "D6: the open position must mark to market"
    assert result["max_dd_pct_mtm"] > 0.0


def test_the_legacy_adapter_keeps_its_callers_working(engine, tmp_path):
    """``multi_tf_backtest`` and ``strategy_dynamic_experiment`` call the simulator
    with (cost_mult, slip_mult) and read ``net``/``entry_ts``. The rewrite must not
    break them silently, so the adapter is held to that contract here."""
    register(engine, "legacy", StubFamily(signal_indices=[100, 140]))
    result = engine.simulate_family_legacy("legacy", "SYM", make_bars(), 1.0, 1.0)
    assert result["status"] == "OK"
    assert len(result["trades"]) == 2
    trade = result["trades"][0]
    for key in ("net", "gross", "fees", "entry_ts", "exit_ts", "notional", "reason"):
        assert key in trade, key
    assert trade["net"] == pytest.approx(trade["gross"] - trade["fees"] - trade["spread"]
                                         - trade["slippage"], abs=1e-4)
    assert {"final_equity", "max_dd_pct", "sharpe_proxy", "eval_bars"} <= set(result)
    doubled = engine.simulate_family_legacy("legacy", "SYM", make_bars(), 2.0, 1.0)
    # the adapter rounds to 4 decimals for its legacy consumers, so the doubled fee
    # can only match to that published precision
    assert doubled["trades"][0]["fees"] == pytest.approx(2 * trade["fees"], abs=1e-4)


def test_equity_at_the_end_reflects_the_realised_result(engine, tmp_path):
    register(engine, "equity", StubFamily(signal_indices=[100]))
    out, _ = run_probe(engine, tmp_path, "equity")
    block = results_of(out)["results"]["equity"]["BASE"]
    per_symbol = block["per_symbol"]["SYM"]
    assert per_symbol["final_equity"] == pytest.approx(engine.START_EQUITY
                                                       + block["totals"]["net_pnl"], abs=0.02)
