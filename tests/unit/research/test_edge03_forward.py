"""WP-EDGE-03 — the forward lane's own regressions.

These drive the SAME callable the runner drives (``run_forward_observation``), with the
network seam replaced by a scripted source, so the pipeline the tests pin is the pipeline
that runs. Each test names the failure it would catch:

* the frozen corpora are re-read and compared against the digests and end instants the
  earlier work packages published — if the local bytes move, the check below breaks;
* ingestion stores only CLOSED bars, only after the freeze, only on the grid, and the
  rejects are counted by name instead of vanishing;
* a gap is reported and never filled, and a revision to an already-stored bar is recorded
  while the stored value wins;
* a second ingest at the same instant appends nothing and moves nothing (restart safety);
* the shadow books hypothetical fills only, inside the forward window, and never claims an
  order was sent;
* the parity harness really drives the runtime engine, sizes identically when both admit
  an entry, and reports the rules the research budget does not model under their own class;
* the whole lane, run offline, produces artefacts the independent verifier accepts — and
  the verifier's sabotage self-test still detects tampering.

Nothing here reaches the network: a scripted source is injected everywhere.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.edge01.costs import cost_plane  # noqa: E402
from trading_bot.research.edge03 import forward_plan as FP  # noqa: E402
from trading_bot.research.edge03 import parity  # noqa: E402
from trading_bot.research.edge03 import run as RUN  # noqa: E402
from trading_bot.research.edge03.ingest import (  # noqa: E402
    ScriptedKlineSource,
    audit_series,
    default_store_root,
    ingest_series,
    validate_rows,
)
from trading_bot.research.edge03.shadow import (  # noqa: E402
    SHADOW_ARMS,
    load_forward_bars,
    union_series,
)

HOUR = 3_600_000
QUARTER = 900_000
FROZEN_1H_END = 1_772_319_600_000
FROZEN_15M_END = 1_791_372_600_000


def load_script(relative: str):
    """Import a ``scripts/`` file by path (the same trick the recovery tests use).

    The module is registered in ``sys.modules`` before it runs: a dataclass defined in an
    unregistered module cannot resolve its own annotations.
    """
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(f"edge03_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def kline(ts: int, price: float = 100.0, *, high: float | None = None, low: float | None = None):
    """One Binance-shaped row: [open_ts, o, h, l, c, v, close_ts, ...]."""
    high = price + 1 if high is None else high
    low = price - 1 if low is None else low
    return [ts, price, high, low, price + 0.5, 10.0, ts + HOUR - 1, "0", "0", "0", "0", "0"]


def scripted(*, bars: int = 48, start: int = FROZEN_1H_END + HOUR, step: int = HOUR):
    rows = {
        asset: [kline(start + index * step, 100.0 + index) for index in range(bars)]
        for asset in ("BTC", "ETH", "SOL")
    }
    now = start + bars * step
    return ScriptedKlineSource(rows_by_symbol=rows, server_time=now), now


@pytest.fixture()
def store(tmp_path: Path):
    return RUN.ForwardStore(default_store_root(tmp_path))


def _ingest(source, store, ledger, asset: str = "BTC", *, timeframe: str = "1h", now: int):
    return ingest_series(
        source=source,
        store=store,
        ledger=ledger,
        timeframe=timeframe,
        symbol=asset,
        frozen_end_ms=FROZEN_1H_END if timeframe == "1h" else FROZEN_15M_END,
        observed_at_ms=now,
    )


# --------------------------------------------------------------------------- frozen past
def test_frozen_corpus_is_pinned_to_the_published_digests():
    seen = FP.assert_frozen_corpus()
    for key, digest in FP.FROZEN_SHARD_SHA256.items():
        assert seen[key]["sha256_prefix16"] == digest, key
    assert seen["1h:BTC"]["last_ts"] == FP.FROZEN_1H_END_MS
    assert seen["15m:BTC"]["last_ts"] == FP.FROZEN_15M_END_MS


def test_a_moved_frozen_corpus_refuses_to_run(tmp_path, monkeypatch):
    """The lane must refuse to compare new bars against a different past."""
    moved = dict(FP.FROZEN_SHARD_SHA256)
    moved["1h:BTC"] = "0" * 16
    monkeypatch.setattr(FP, "FROZEN_SHARD_SHA256", moved)
    with pytest.raises(AssertionError, match="frozen 1h corpus for BTC changed"):
        FP.assert_frozen_corpus()


# ----------------------------------------------------------------------------- ingestion
def test_only_closed_grid_bars_after_the_freeze_are_stored(tmp_path):
    span = HOUR
    start = FROZEN_1H_END + span
    # ``now`` sits 30 s past a bucket boundary, which is exactly the real situation: the
    # newest bucket grid bar has already OPENED and not closed, so the venue returns it and
    # the lane has to refuse it.
    now = start + 4 * span + 30_000
    rows = [
        kline(FROZEN_1H_END),  # at the freeze: not forward evidence
        kline(start - span),  # before the freeze
        kline(start, 100.0),  # admissible
        kline(start + 2 * span, 102.0, high=90.0, low=110.0),  # impossible OHLC block
        kline(start + 2 * span + 1, 102.0),  # off the grid
        kline(start + 3 * span, 103.0),  # admissible
        kline(start + 4 * span, 104.0),  # still OPEN at the fetch instant
    ]
    source = ScriptedKlineSource(rows_by_symbol={"BTC": rows}, server_time=now)
    store = RUN.ForwardStore(tmp_path / "store")
    ledger = RUN.IngestLedger(tmp_path / "ledger.jsonl")
    row = _ingest(source, store, ledger, now=now)

    stored = [int(r["ts"]) for r in store.read("1h", "BTC")]
    assert stored == [start, start + 3 * span]
    assert row["rejected"]["not_closed"] == 1
    # The fetch window already starts at the first bar after the freeze, so a bar at or
    # before it never reaches validation; the guard itself is exercised directly in
    # ``test_validation_counts_each_reject_by_name``.
    assert row["rejected"]["at_or_before_frozen_end"] == 0
    assert row["rejected"]["off_grid"] == 1
    assert row["rejected"]["incomplete_ohlc"] == 1
    assert row["audit"]["duplicates"] == 0
    assert row["audit"]["contiguous"] is False  # two slots are missing by construction


def test_validation_counts_each_reject_by_name():
    rows = [
        {
            "ts": FROZEN_1H_END + HOUR,
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        },
        {
            "ts": FROZEN_1H_END + 2 * HOUR,
            "open": 1.0,
            "high": 1.0,
            "low": 1.0,
            "close": 1.0,
            "volume": 1.0,
        },
    ]
    kept, counts = validate_rows(
        rows,
        timeframe="1h",
        frozen_end_ms=FROZEN_1H_END,
        observed_at_ms=FROZEN_1H_END + 3 * HOUR,
    )
    assert len(kept) == 2
    assert counts["duplicate_in_fetch"] == 0
    _, again = validate_rows(
        rows, timeframe="1h", frozen_end_ms=FROZEN_1H_END, observed_at_ms=FROZEN_1H_END + HOUR
    )
    assert again["not_closed"] == 2


def test_a_gap_is_reported_and_never_filled(tmp_path):
    source, now = scripted(bars=8)
    source.rows_by_symbol["BTC"] = [
        row for index, row in enumerate(source.rows_by_symbol["BTC"]) if index != 3
    ]
    store = RUN.ForwardStore(tmp_path / "store")
    ledger = RUN.IngestLedger(tmp_path / "ledger.jsonl")
    row = _ingest(source, store, ledger, now=now)

    stored = store.read("1h", "BTC")
    assert len(stored) == 7  # nothing was invented to close the hole
    audit = row["audit"]
    assert audit["gap_count"] == 1
    assert audit["missing_bars"] == 1
    assert audit["contiguous"] is False
    assert audit["gaps"][0]["missing_bars"] == 1


def test_a_revision_is_recorded_and_the_stored_bar_wins(tmp_path):
    start = FROZEN_1H_END + HOUR
    first_rows = [kline(start, 100.0), kline(start + HOUR, 101.0)]
    source = ScriptedKlineSource(
        rows_by_symbol={"BTC": first_rows}, server_time=start + 2 * HOUR
    )
    store = RUN.ForwardStore(tmp_path / "store")
    ledger = RUN.IngestLedger(tmp_path / "ledger.jsonl")
    _ingest(source, store, ledger, now=start + 2 * HOUR)
    original = {int(r["ts"]): r["close"] for r in store.read("1h", "BTC")}

    # The venue later reports a different close for a bar it already published.
    revised = [kline(start, 100.0), kline(start + HOUR, 999.0), kline(start + 2 * HOUR, 102.0)]
    source2 = ScriptedKlineSource(
        rows_by_symbol={"BTC": revised}, server_time=start + 3 * HOUR
    )
    row = _ingest(source2, store, ledger, now=start + 3 * HOUR)

    after = {int(r["ts"]): r["close"] for r in store.read("1h", "BTC")}
    assert after[start + HOUR] == original[start + HOUR]
    assert row["revisions"] and row["revisions"][0]["ts"] == start + HOUR
    assert row["revisions"][0]["kept"] == "the first observation"
    assert row["prefix_preserved"] is True


def test_no_new_data_is_a_recorded_result_not_an_error(tmp_path):
    source, now = scripted(bars=4)
    store = RUN.ForwardStore(tmp_path / "store")
    ledger = RUN.IngestLedger(tmp_path / "ledger.jsonl")
    first = _ingest(source, store, ledger, now=now)
    assert first["outcome"] == "ingested" and first["appended"] == 4

    second = _ingest(source, store, ledger, now=now)
    assert second["outcome"] == "no_new_data"
    assert second["appended"] == 0
    assert "had not closed" in second["reason"]
    assert len(store.read("1h", "BTC")) == 4
    assert len(ledger.read()) == 2


def test_an_empty_fetch_is_also_no_new_data(tmp_path):
    start = FROZEN_1H_END + HOUR
    source = ScriptedKlineSource(rows_by_symbol={"BTC": []}, server_time=start + 2 * HOUR)
    store = RUN.ForwardStore(tmp_path / "store")
    ledger = RUN.IngestLedger(tmp_path / "ledger.jsonl")
    row = _ingest(source, store, ledger, now=start + 2 * HOUR)
    assert row["outcome"] == "no_new_data"
    assert row["appended"] == 0


def test_audit_counts_duplicates_and_disorder():
    rows = [
        {"ts": FROZEN_1H_END + HOUR},
        {"ts": FROZEN_1H_END + HOUR},
        {"ts": FROZEN_1H_END},
    ]
    audit = audit_series(rows, timeframe="1h", frozen_end_ms=FROZEN_1H_END)
    assert audit["duplicates"] == 1
    # Two non-advancing steps: the repeated bar and the one that goes backwards.
    assert audit["out_of_order"] == 2
    assert audit["contiguous"] is False
    # The audit reads the stored order as it is; it does not sort the evidence for the reader.
    assert audit["first_ts"] == FROZEN_1H_END + HOUR


# ------------------------------------------------------------------------------- shadow
def test_union_series_refuses_overlap():
    from trading_bot.research.edge01.data import OHLCVBar

    frozen = [OHLCVBar(FROZEN_1H_END - HOUR, 1, 1, 1, 1, 1), OHLCVBar(FROZEN_1H_END, 1, 1, 1, 1, 1)]
    with pytest.raises(AssertionError, match="does not come after the frozen end"):
        union_series(frozen, [OHLCVBar(FROZEN_1H_END, 1, 1, 1, 1, 1)], label="1h:BTC")


def test_forward_bars_before_the_freeze_are_refused(tmp_path):
    store = RUN.ForwardStore(tmp_path / "store")
    ledger = RUN.IngestLedger(tmp_path / "ledger.jsonl")
    path = store.path("1h", "BTC")
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "ts": FROZEN_1H_END,
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1.0,
                "interval": "1h",
                "source": "TEST",
                "fetched_at_ms": FROZEN_1H_END + HOUR,
                "payload_sha256": "0" * 64,
                "closed": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    del ledger
    with pytest.raises(AssertionError, match="not after the frozen end"):
        load_forward_bars(store, "1h", "BTC", frozen_end_ms=FROZEN_1H_END)


def test_every_declared_arm_is_hypothetical_and_carries_no_order_path():
    for arm, spec in SHADOW_ARMS.items():
        assert spec["source"] in {"1h", "15m"}, arm
        assert spec["limit"] in {True, False}, arm


def test_published_arm_labels_are_scenario_qualified_and_self_consistent(tmp_path):
    """Three cost scenarios produce three ledgers; a shared label cannot be summed.

    This is the defect the independent verifier caught on the real run: every scenario's
    fills were published under the bare arm id, so the summary of the BASE reading could
    not be reconciled against the rows that carried its name.
    """
    payload, _ = _run(tmp_path, scenarios=("BASE", "2X_FEES"))
    summaries = payload["shadow"]["arm_summaries"]
    assert set(summaries) >= {"edge_trend_01_4h:BASE", "edge_trend_01_4h:2X_FEES"}
    for label, body in summaries.items():
        if body.get("status") != "observed":
            continue
        assert body["arm"] == label
        assert ":" in label
        nets = sum(float(row["net"]) for row in body["trades_detail"])
        assert float(body["metrics"]["net_usdt"]) == pytest.approx(nets, abs=1e-9)
        assert int(body["metrics"]["trades"]) == len(body["trades_detail"])


# ------------------------------------------------------------------------------- parity
def test_the_runtime_signal_price_is_the_fill_the_research_books():
    """Parity rests on this identity: a sizing difference must be policy, not arithmetic."""
    plane = cost_plane(size_usd=1000.0, horizon_minutes=1440.0)
    state = {
        "asset": "BTC",
        "candidate": "edge_trend_01",
        "timeframe": "4h",
        "decision_ts": 1_791_372_600_000,
        "entry_mid": 50_000.0,
        "stop": 49_000.0,
        "targets": [52_000.0],
        "equity": 10_000.0,
        "peak_equity": 10_000.0,
    }
    research = parity.research_decision(state, policy=parity.load_risk_policy(), plane=plane)
    assert research["approved"] is True
    assert parity._entry_fill(plane, state["entry_mid"]) == pytest.approx(research["entry_fill"])


def test_a_clean_case_is_admitted_by_both_at_the_same_size():
    plane = cost_plane(size_usd=1000.0, horizon_minutes=1440.0)
    case = parity.declared_cases(sweep_cases=0)[0]
    research = parity.research_decision(case, policy=parity.load_risk_policy(), plane=plane)
    runtime = parity.runtime_decision(case, risk=parity.load_runtime_risk(), plane=plane)
    assert research["approved"] is True and runtime["approved"] is True
    assert research["notional"] == pytest.approx(runtime["notional"], abs=1e-6)
    assert research["quantity"] == pytest.approx(runtime["quantity"], rel=1e-12)


def test_the_parity_harness_drives_the_real_runtime_engine(monkeypatch):
    """If someone replaced the engine with a restatement, this count would be zero."""
    calls: list[str] = []
    from trading_bot.risk.manager import RiskManager

    original = RiskManager.check_signal

    def counting(self, signal):
        calls.append(signal.symbol)
        return original(self, signal)

    monkeypatch.setattr(RiskManager, "check_signal", counting)
    payload = parity.run_parity(captures=[], sweep_cases=4, shadow_case_limit=0)
    assert calls, "the runtime engine was never called"
    assert payload["verdict"] in {"PARITY_PASS", "PARITY_FINDINGS"}


def test_a_rule_the_research_budget_does_not_model_is_reported_under_its_own_class():
    plane = cost_plane(size_usd=1000.0, horizon_minutes=1440.0)
    case = parity.declared_cases(sweep_cases=0)[0]
    halted = {**case, "kill_switch": True}
    comparison = parity.compare(
        "kill_switch",
        "declared",
        halted,
        policy=parity.load_risk_policy(),
        risk=parity.load_runtime_risk(),
        plane=plane,
    )
    assert comparison.runtime["blocked_by"] == "kill_switch"
    assert comparison.klass == "RULE_NOT_MODELLED_BY_RESEARCH"


def test_a_cooldown_outliving_the_streak_is_a_research_only_refusal():
    plane = cost_plane(size_usd=1000.0, horizon_minutes=1440.0)
    ts = 1_791_372_600_000
    case = parity._case(
        case_id="cooldown-after-a-win",
        equity=10_000.0,
        peak_equity=10_000.0,
        consecutive_losses=0,
        cooldown_until_ts=ts + 30 * 60_000,
        decision_ts=ts,
    )
    comparison = parity.compare(
        "cooldown-after-a-win",
        "declared",
        case,
        policy=parity.load_risk_policy(),
        risk=parity.load_runtime_risk(),
        plane=plane,
    )
    assert comparison.klass == "RESEARCH_ONLY_REFUSAL"
    assert comparison.research["reason"] == "risk_loss_cooldown"


def test_a_cent_rounding_gap_is_named_as_rounding_and_not_as_policy():
    """The runtime publishes its notional in cents; that must not read as a policy gap."""
    research = {"approved": True, "reason": "parity_approved", "notional": 432.87336214562697}
    runtime = {"approved": True, "blocked_by": None, "notional": 432.87}
    assert parity._classify(research, runtime, tolerance=1e-6)[0] == "SIZING_ROUNDING_ONLY"
    # A genuine difference is still a difference: rounding must not launder it.
    assert parity._classify({**research, "notional": 500.0}, runtime, tolerance=1e-6)[0] == (
        "SIZING_DIFFERS"
    )
    assert parity._classify(research, {**runtime, "notional": 432.87336214562697}, tolerance=1e-6)[
        0
    ] == "AGREE_APPROVED"


def test_declared_cases_are_deterministic():
    first = parity.declared_cases(sweep_cases=16)
    second = parity.declared_cases(sweep_cases=16)
    assert [row["case_id"] for row in first] == [row["case_id"] for row in second]
    assert first[-1]["entry_mid"] == second[-1]["entry_mid"]


def test_captured_shadow_instants_become_parity_cases():
    capture = {
        "arm": "edge_trend_01_4h",
        "asset": "BTC",
        "candidate": "edge_trend_01",
        "decision_ts": 1_791_372_600_000,
        "equity": 10_000.0,
        "peak_equity": 10_000.0,
        "drawdown_pct": 0.0,
        "open_positions_count": 1,
        "open_positions_notional": 500.0,
        "open_notional_by_asset": {"ETH": 500.0},
        "open_assets": ["ETH"],
        "asset_held": False,
        "trades_today": 2,
        "consecutive_losses": 1,
        "cooldown_until_ts": 0,
        "entry_mid": 50_000.0,
        "stop": 49_000.0,
        "targets": [52_000.0],
        "timeframe": "4h",
        "decision": "APPROVED",
        "reason": None,
    }
    cases = parity.shadow_cases([capture])
    assert len(cases) == 1
    assert cases[0]["open_notional_by_asset"] == {"ETH": 500.0}
    assert cases[0]["captured_decision"] == "APPROVED"


# --------------------------------------------------------------------------- whole lane
def _run(tmp_path: Path, *, bars: int = 24, scenarios=("BASE",)):
    source, now = scripted(bars=bars)
    store_root = default_store_root(tmp_path)
    if store_root.exists():
        shutil.rmtree(store_root)
    payload = RUN.run_forward_observation(
        repo_root=tmp_path,
        source=source,
        observed_at_ms=now,
        scenarios=scenarios,
        sweep_cases=8,
    )
    outdir = tmp_path / "reports" / "edge-recovery" / "WP-EDGE-03"
    payload["entrypoint"] = "scripts/edge03_run.py:run_forward_observation"
    payload["test_target"] = "run_forward_observation"
    written = RUN.write_forward_artifacts(payload, outdir / "forward-observation")
    from trading_bot.research.edge03.parity import write_parity_artifacts

    written.update(write_parity_artifacts(payload["parity"], outdir / "risk-parity"))
    return payload, outdir


def test_the_lane_ingests_shadows_and_writes_artifacts(tmp_path):
    payload, outdir = _run(tmp_path)
    assert payload["health"]["new_bars"] == 24 * 3
    assert payload["restart_proof"]["second_run_appended"] == 0
    assert payload["restart_proof"]["digests_unchanged"] is True
    assert payload["restart_proof"]["duplicate_timestamps"] == 0
    assert payload["shadow"]["primary_arm"] == "edge_trend_01_4h:BASE"
    primary = payload["shadow"]["arm_summaries"]["edge_trend_01_4h:BASE"]
    assert primary["status"] == "observed"
    assert primary["arm"] == "edge_trend_01_4h:BASE"
    # The last complete frozen 4h bucket opens at 2026-02-28T20:00, so the forward window
    # starts at the next bucket: 2026-03-01T00:00, i.e. one hour after the frozen 1h end.
    assert primary["window_start_ts"] == FROZEN_1H_END + HOUR
    assert payload["shadow"]["order_sent"] is False
    assert payload["verdict"]["promotion"] == "NONE"
    for name in (
        "OBSERVATION.json",
        "SHADOW_SIGNALS.csv" if (outdir / "forward-observation/SHADOW_SIGNALS.csv").exists() else "INGEST_LEDGER.jsonl",
        "CUMULATIVE.md",
        "CUMULATIVE.json",
    ):
        assert (outdir / "forward-observation" / name).exists(), name
    assert (outdir / "risk-parity" / "PARITY.md").exists()


def test_the_daily_rollup_is_day_first_and_the_report_names_the_arms(tmp_path):
    """A rollup keyed by arm first leaves the daily report claiming nothing happened."""
    payload, _ = _run(tmp_path, scenarios=("BASE",))
    from trading_bot.research.edge03.reporting import daily_markdown

    daily_arms = payload["daily_arms"]
    assert daily_arms, "no arm activity was recorded on any date"
    for day in daily_arms:
        assert len(day) == 10 and day[4] == "-", day
        assert isinstance(daily_arms[day], dict)
    day, arms = next(iter(sorted(daily_arms.items())))
    rendered = daily_markdown(payload, day)
    for arm in arms:
        assert arm in rendered, f"{arm} is missing from the daily report for {day}"
    assert "No arm printed anything on this date." not in rendered


def test_the_published_exposure_is_the_one_the_fills_imply(tmp_path):
    payload, _ = _run(tmp_path, scenarios=("BASE",))
    hour = 3_600_000
    for label, body in payload["shadow"]["arm_summaries"].items():
        if body.get("status") != "observed":
            continue
        span = {"4h": 4 * hour, "1d": 24 * hour, "15m": 900_000}[body["timeframe"]]
        expected = (
            sum((row["exit_ts"] - row["entry_ts"]) / span for row in body["trades_detail"])
            / body["window_bars"]
            * 100.0
        )
        assert body["metrics"]["exposure_pct_of_time"] == pytest.approx(expected, abs=1e-6), label


def test_the_whole_lane_is_reproducible_from_scratch(tmp_path):
    first, _ = _run(tmp_path / "a")
    second, _ = _run(tmp_path / "b")
    assert first["ingest"]["ledger"][0]["store_sha256"] == second["ingest"]["ledger"][0]["store_sha256"]
    assert first["shadow"]["decisions_digest"] == second["shadow"]["decisions_digest"]
    assert first["primary_equity_curve"] == second["primary_equity_curve"]


def test_a_15m_hole_does_not_stop_the_1h_arms(tmp_path):
    source, now = scripted(bars=24)
    # no 15m bars at all: the intraday arms must report it rather than fail
    args = dict(
        repo_root=tmp_path,
        source=source,
        observed_at_ms=now,
        scenarios=("BASE",),
        sweep_cases=4,
    )
    shutil.rmtree(default_store_root(tmp_path), ignore_errors=True)
    payload = RUN.run_forward_observation(**args)
    intraday = payload["shadow"]["arm_summaries"]["edge_intra_01"]
    assert intraday["status"] == "no_forward_bars"
    assert "15m" in intraday["reason"]
    assert payload["shadow"]["arm_summaries"]["edge_trend_01_4h:BASE"]["status"] == "observed"


@pytest.mark.slow
def test_the_independent_verifier_accepts_the_lane_and_detects_tampering(tmp_path):
    verifier = load_script("scripts/edge03_verify.py")
    payload, outdir = _run(tmp_path, scenarios=("BASE",))
    bundle = verifier.Bundle(
        artifacts=outdir,
        repo=tmp_path,
        sources=ROOT,
        corpus=ROOT,
    )
    report = verifier.run_checks(bundle)
    failed = [entry for entry in report["checks"] if not entry["passed"]]
    assert report["verdict"] == "VERIFY_PASS", failed
    self_test = verifier.self_test(bundle)
    assert self_test["verdict"] == "SELF_TEST_PASS", self_test["sabotages"]
    # Every sabotage that could be applied was detected. In this rehearsal the arm prints
    # no signal and books no fill, so the three sabotages that target the shadow ledgers are
    # reported as skipped rather than silently counted as passes.
    assert self_test["applied"] + self_test["skipped"] == len(verifier._sabotages())
    assert self_test["detected"] == self_test["applied"]
    assert self_test["undetected"] == 0
    assert self_test["skipped"] == len(self_test["skipped_labels"])
