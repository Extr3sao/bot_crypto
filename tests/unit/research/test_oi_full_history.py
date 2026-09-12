"""OI-FULL-HISTORY-FREEZE-01 tests (Tracks B/C/D/E/J).

Covers: canonical contract semantics (units, cadence, string-timestamp
conversion), valid-day classification, PIT invariant, future-mutation safety,
frozen-file anchors (dataset sha256, frozen 1h price authority extension) and
full-dataset invariants (when the frozen dataset is present on this machine;
skipped otherwise so the suite stays hermetic on clean checkouts).
"""

from __future__ import annotations

import csv as _csv_mod
import hashlib
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.normalize_oi_full_history import (
    ALLOWED_PROVIDER_FIELDS,
    COMMON_WINDOW,
    EXPECTED_INTERVAL_SECONDS,
    EXPECTED_ROWS_PER_DAY,
    RANGES,
    SCHEMA_VERSION,
    process_file,
)
from trading_bot.research.oi_dataset import (
    decision_eligibility_at,
    load_ledger,
    oi_hourly_decision_state,
    oi_state_at,
    valid_days_for,
)

REPO = Path(__file__).resolve().parents[3]
FROZEN_LEDGER = REPO / "data" / "processed" / "oi_full_history" / "OI_DAY_VALIDITY_LEDGER.jsonl"
FROZEN_MANIFEST = REPO / "data" / "processed" / "oi_full_history" / "OI_FULL_HISTORY_DATASET_MANIFEST.json"
FROZEN_DATASET_SHA256 = "16779b7d2eff0dc9e56015c444c2dbe7b67ef083e6cf1877a024a6de74098d99"
PRICE_AUTHORITY_DIR = REPO / "docs" / "external-audit-01" / "h1-regime-transition-01" / "dataset"


def _is_frozen_dataset_present() -> bool:
    return FROZEN_LEDGER.exists() and FROZEN_MANIFEST.exists()


def _git_diff_empty(path: str, against: str) -> bool:
    out = subprocess.run(
        ["git", "diff", against, "--", path], capture_output=True, text=True
    ).stdout
    return out == ""


# ---------- Track B: contract semantics ----------

def test_schema_versions_frozen() -> None:
    assert SCHEMA_VERSION == "2.0.1"
    assert EXPECTED_INTERVAL_SECONDS == 300
    assert EXPECTED_ROWS_PER_DAY == 288


def test_provider_string_timestamp_conversion() -> None:
    """Provider create_time 'YYYY-MM-DD HH:MM:SS' maps to the 5m UTC grid."""
    import hashlib
    import io
    import csv as _csv

    raw = REPO / "data" / "raw" / "binance_um" / "metrics" / "BTCUSDT" / "BTCUSDT-metrics-2020-09-01.zip"
    if not raw.exists():
        pytest.skip("raw sample not present on this machine")
    with zipfile.ZipFile(raw) as zf:
        with zf.open(zf.namelist()[0]) as fh:
            rows = list(_csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8")))
    first = rows[0]
    ts = int(
        datetime.strptime(first["create_time"], "%Y-%m-%d %H:%M:%S")
        .replace(tzinfo=timezone.utc)
        .timestamp()
        * 1000
    )
    assert ts % (EXPECTED_INTERVAL_SECONDS * 1000) == 0
    # documented era artifact: 2020-09-01 emits 576 exact-duplicate rows
    assert len(rows) == 576


def test_field_whitelist_excludes_ratio_fields() -> None:
    forbidden = {
        "count_toptrader_long_short_ratio",
        "sum_toptrader_long_short_ratio",
        "count_long_short_ratio",
        "sum_taker_long_short_vol_ratio",
    }
    assert not (ALLOWED_PROVIDER_FIELDS & forbidden)
    wl = json.loads((REPO / "docs/external-audit-01/oi-full-history-01/H6_FEATURE_AUTHORITY_WHITELIST.json").read_text())
    assert {f["field"] for f in wl["ALLOWED_FIELDS"]} >= {"sum_open_interest", "sum_open_interest_value"}


def test_common_window_frozen() -> None:
    assert COMMON_WINDOW == ("2021-12-01T00:00:00Z", "2026-09-10T23:55:00Z")
    assert RANGES["BTCUSDT"] == ("2020-09-01", "2026-09-10")
    assert RANGES["ETHUSDT"] == ("2021-12-01", "2026-09-10")
    assert RANGES["SOLUSDT"] == ("2021-12-01", "2026-09-10")


# ---------- Track E: valid-day contract ----------

def _make_metrics_zip(tmp: Path, day: str, symbol: str, rows: list[tuple[str, str, str, str]] | None = None,
                      duplicate: bool = False, conflicting: bool = False, drop_last: bool = False) -> Path:
    import csv as _csv
    import io

    base = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if rows is None:
        rows = []
        for i in range(EXPECTED_ROWS_PER_DAY):
            ts = base.timestamp() + i * 300
            t = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            oi = 100.0 + i
            rows.append((t, symbol, f"{oi}", f"{oi * 50}"))
        if duplicate:
            rows = rows + rows  # provider-era artifact: every row exactly twice
        if conflicting:
            rows = rows + [(rows[-1][0], symbol, "999.0", "49950.0")]
        if drop_last:
            rows = rows[:-1]
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
                "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
                "count_long_short_ratio", "sum_taker_long_short_vol_ratio"])
    for r in rows:
        w.writerow(r)
    zdir = tmp / symbol
    zdir.mkdir(parents=True, exist_ok=True)
    zpath = zdir / f"{symbol}-metrics-{day}.zip"
    zpath.write_bytes(b"")
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr(f"{symbol}-metrics-{day}.csv", buf.getvalue())
    digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
    zpath.with_name(zpath.name + ".CHECKSUM").write_text(f"{digest}  {zpath.name}\n")
    return zpath


def test_valid_day_classification(tmp_path: Path) -> None:
    day = "2024-06-05"
    out_dir = tmp_path / "out_valid"
    _make_metrics_zip(tmp_path, day, "BTCUSDT", duplicate=True)
    e = process_file("BTCUSDT", day, raw_dir=tmp_path, out_dir=out_dir)
    assert e["classification"] == "VALID"
    assert e["rows"] == EXPECTED_ROWS_PER_DAY
    assert e["exact_duplicate_rows_collapsed"] == EXPECTED_ROWS_PER_DAY
    assert e["checksum"] == "PASS"


def test_conflicting_duplicate_invalidates(tmp_path: Path) -> None:
    day = "2024-06-05"
    out_dir = tmp_path / "out_conflict"
    _make_metrics_zip(tmp_path, day, "BTCUSDT", duplicate=False, conflicting=True)
    e = process_file("BTCUSDT", day, raw_dir=tmp_path, out_dir=out_dir)
    # V1 used INVALID_DUPLICATE, V2 API uses INVALID_CONFLICTING_DUPLICATE; accept either
    assert e["classification"] in ("INVALID_DUPLICATE", "INVALID_CONFLICTING_DUPLICATE")


def test_gap_invalidates(tmp_path: Path) -> None:
    day = "2024-06-05"
    out_dir = tmp_path / "out_gap"
    _make_metrics_zip(tmp_path, day, "BTCUSDT", drop_last=True)
    e = process_file("BTCUSDT", day, raw_dir=tmp_path, out_dir=out_dir)
    assert e["classification"] == "INVALID_GAP"


def test_checksum_failure_invalidates(tmp_path: Path) -> None:
    day = "2024-06-05"
    out_dir = tmp_path / "out_chk"
    zp = _make_metrics_zip(tmp_path, day, "BTCUSDT")
    zp.write_bytes(zp.read_bytes() + b"x")  # corrupt after sidecar written
    e = process_file("BTCUSDT", day, raw_dir=tmp_path, out_dir=out_dir)
    assert e["classification"] == "INVALID_CHECKSUM"


def test_missing_file_is_source_missing(tmp_path: Path) -> None:
    e = process_file("BTCUSDT", "2024-06-05", raw_dir=tmp_path, out_dir=tmp_path / "out_missing")
    assert e["classification"] == "SOURCE_MISSING"


# ---------- Track J: PIT + future mutation ----------

def test_pit_cutoff_and_future_mutation(tmp_path: Path) -> None:
    from scripts.normalize_oi_full_history import _grid_for_day

    day = "2024-06-05"
    out_dir = tmp_path / "out"
    _make_metrics_zip(tmp_path, day, "BTCUSDT", duplicate=True)
    e = process_file("BTCUSDT", day, raw_dir=tmp_path, out_dir=out_dir)
    assert e["classification"] == "VALID"
    norm_path = out_dir / "BTCUSDT" / f"BTCUSDT-oi-5m-{day}.jsonl"
    before = norm_path.read_bytes()

    ledger = load_ledger(_tmp_ledger(tmp_path, e))
    grid = _grid_for_day(day)
    mid = grid[144]  # 12:00

    state = oi_state_at(mid, ledger, "BTCUSDT", out_dir)
    assert state and all(int(r["timestamp_ms"]) <= mid for r in state)  # type: ignore[arg-type]
    assert all(int(r["timestamp_ms"]) % 300_000 == 0 for r in state)  # type: ignore[arg-type]

    # future mutation: writing a synthetic future file AFTER T must not change state at T
    (tmp_path / "BTCUSDT" / "BTCUSDT-metrics-2026-01-01.zip").write_bytes(b"")
    state_after = oi_state_at(mid, ledger, "BTCUSDT", out_dir)
    assert state_after == state
    # and the normalized artifact itself is untouched
    assert norm_path.read_bytes() == before


def _tmp_ledger(tmp_path: Path, entry: dict) -> Path:
    p = tmp_path / "ledger.jsonl"
    p.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    return p


def test_hourly_decision_state_is_causal() -> None:
    from trading_bot.research.oi_dataset import hour_bucket_ms

    decision = 1700000800000 - (1700000800000 % 3_600_000) + 20 * 60 * 1000  # inside a bucket
    bucket = hour_bucket_ms(decision)
    assert bucket < decision
    assert (decision - bucket) < 3_600_000


# ---------- P0-B: DECISION_ELIGIBILITY_AT_T causality ----------

def _make_synthetic_history(tmp_path: Path, days: list[str]) -> tuple[Path, Path]:
    """Two full valid days of OI in a temp raw dir + processed ledger/artifacts."""
    out_dir = tmp_path / "out"
    entries = []
    for d in days:
        _make_metrics_zip(tmp_path, d, "BTCUSDT", duplicate=True)
        entries.append(process_file("BTCUSDT", d, raw_dir=tmp_path, out_dir=out_dir))
        assert entries[-1]["classification"] == "VALID"
    ledger_path = tmp_path / "ledger.jsonl"
    ledger_path.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in entries), encoding="utf-8")
    return ledger_path, out_dir


def test_future_gap_after_T_cannot_change_state(tmp_path: Path) -> None:
    """FUTURE_SAME_DAY_GAP_MUTATION: eligibility/feature state at T byte-identical."""
    days = ["2024-06-04", "2024-06-05"]
    ledger_path, out_dir = _make_synthetic_history(tmp_path, days)
    ledger = load_ledger(ledger_path)
    # T = 12:00 on day 2 (completed hour 11:00-12:00)
    T = 1717588800000  # 2024-06-05T12:00:00Z
    before = decision_eligibility_at(T, ledger, "BTCUSDT", out_dir)
    assert before["reason"] in ("ELIGIBLE", "INELIGIBLE_ROLLING_HISTORY_SUFFICIENT")

    # inject a FUTURE day (strictly after T) with a provider gap
    day3 = "2024-06-06"
    _make_metrics_zip(tmp_path, day3, "BTCUSDT", drop_last=True)
    e3 = process_file("BTCUSDT", day3, raw_dir=tmp_path, out_dir=out_dir)
    ledger.append(e3)
    ledger_path.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in ledger), encoding="utf-8")

    after = decision_eligibility_at(T, ledger, "BTCUSDT", out_dir)
    assert json.dumps(after, sort_keys=True) == json.dumps(before, sort_keys=True)


def test_past_gap_before_T_may_change_state(tmp_path: Path) -> None:
    ledger_path, out_dir = _make_synthetic_history(tmp_path, ["2024-06-04", "2024-06-05"])
    ledger = load_ledger(ledger_path)
    T = 1717588800000
    before = decision_eligibility_at(T, ledger, "BTCUSDT", out_dir)

    # rewrite day-1 artifacts with a gapped (INVALID_GAP) day: drops history BEFORE T
    bad = dict(ledger[0])
    bad["classification"] = "INVALID_GAP"
    ledger[0] = bad
    ledger_path.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in ledger), encoding="utf-8")
    after = decision_eligibility_at(T, ledger, "BTCUSDT", out_dir)
    # only history-based checks may move; current-hour completeness must not
    assert after["checks"]["current_hour_complete"] == before["checks"]["current_hour_complete"]
    assert after["checks"]["rolling_history_sufficient"] is False
    assert after["eligible"] is False


# ---------- H6 prereg contract mirrors (skipif spec not present) ----------

@pytest.mark.skipif(not (REPO / "docs/external-audit-01/oi-full-history-01/H6_SPEC.json").exists(), reason="H6 spec not present")
class TestH6PreregContract:
    SPEC = json.loads((REPO / "docs/external-audit-01/oi-full-history-01/H6_SPEC.json").read_text(encoding="utf-8"))

    def test_no_execution_yet(self) -> None:
        assert self.SPEC["H6_EXECUTIONS"] == 0
        assert self.SPEC["H6_BACKTESTS"] == 0
        assert self.SPEC["PERFORMANCE_OBSERVED"] is False

    def test_single_canonical_cost(self) -> None:
        cm = self.SPEC["cost_model"]
        assert cm["BASE_TOTAL_ROUND_TRIP_COST_BPS"] == 10
        assert cm["COST_SENSITIVITY_BPS"] == [0, 10, 20, 40]
        assert cm["gross_reporting_required"] is True

    def test_funding_excluded_with_limitation(self) -> None:
        fa = self.SPEC["funding_accounting"]
        assert fa["FUNDING_DISCOVERY_ACCOUNTING"] == "EXCLUDED_WITH_LIMITATION"
        assert fa["funding_materiality_gate_before_promotion"] is True

    def test_orthogonality_gate_single_value(self) -> None:
        og = self.SPEC["orthogonality_gates"]
        assert og["MAX_ABS_DAILY_CORRELATION_TO_MOMENTUM_PROXY"] == 0.50
        assert og["H5_PNL_CORRELATION"].startswith("NOT_EVALUABLE_FROM_PERSISTED_EVIDENCE")

    def test_discovery_simplification(self) -> None:
        assert self.SPEC["stop_invalidation"].startswith("NONE")
        assert self.SPEC["cooldown"].startswith("NONE")
        assert self.SPEC["decision_timeframe"]["primary_holding_horizon_hours"] == 1
        assert self.SPEC["experiment_id"] == 1

    def test_robust_z_frozen_definition(self) -> None:
        rw = self.SPEC["rolling_windows"]["z_oi"]
        assert rw["center"] == "median" and rw["scale"] == "1.4826*MAD"
        assert rw["length_hours"] == 720 and rw["min_observations"] == 336
        assert self.SPEC["threshold_rule"]["expansion_condition"] == "z_oi >= +1.0"

    def test_no_sweep_language(self) -> None:
        blob = json.dumps(self.SPEC)
        assert "NO parameter sweep" in blob or "NO_PARAMETER_SWEEP" in blob

    def test_causal_eligibility_constants_match_spec(self) -> None:
        from trading_bot.research import oi_dataset as od

        assert od.ROBUST_Z_WINDOW_HOURS == 720
        assert od.ROBUST_Z_MIN_OBSERVATIONS == 336
        assert od.ROBUST_Z_MAD_SCALE == 1.4826
        assert od.OI_Z_THRESHOLD == 1.0
        assert od.SNAPSHOTS_PER_HOUR == 12


# ---------- frozen anchors (run where the dataset exists) ----------

@pytest.mark.skipif(not _is_frozen_dataset_present(), reason="frozen OI dataset not on this machine")
class TestFrozenAnchors:
    def test_dataset_fingerprint_matches_freeze(self) -> None:
        m = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))
        assert m["OI_FULL_HISTORY_DATASET_SHA256"] == FROZEN_DATASET_SHA256
        assert m["quality_status"] == "PASS_WITH_EXPLICIT_GAPS"
        assert m["totals"]["valid_days"] == 5596
        assert m["totals"]["rows_valid"] == 1611648

    def test_valid_day_counts_per_symbol(self) -> None:
        ledger = load_ledger(FROZEN_LEDGER)
        for sym, expected in (("BTCUSDT", 2129), ("ETHUSDT", 1735), ("SOLUSDT", 1732)):
            assert len(valid_days_for(ledger, sym)) == expected

    def test_no_valid_day_contains_future_rows(self) -> None:
        ledger = load_ledger(FROZEN_LEDGER)
        bad = [
            e
            for e in ledger
            if e["classification"] == "VALID" and int(e.get("rows_within_pit", 0)) != int(e.get("rows", 0))  # type: ignore[arg-type]
        ]
        assert not bad

    def test_normalized_rows_match_manifest_totals(self) -> None:
        ledger = load_ledger(FROZEN_LEDGER)
        total = sum(int(e.get("rows", 0)) for e in ledger if e["classification"] == "VALID")  # type: ignore[arg-type]
        assert total == 1611648


# ---------- Track H: frozen price authority ----------

def test_frozen_1h_price_authority_unchanged() -> None:
    """The committed H1 1h dataset must remain byte-identical to its frozen commit.

    It already covers the ENTIRE common research window: last bucket
    openTime 1788912000000 = 2026-09-10T00:00Z (close 23:59:59.999Z).
    """
    rel = "docs/external-audit-01/h1-regime-transition-01/dataset/BTCUSDT_1h.jsonl"
    assert _git_diff_empty(rel, "cb3de4f"), "frozen price authority was modified"
    rows = (REPO / rel).read_text(encoding="utf-8").splitlines()
    assert len(rows) == 58633
    assert int(json.loads(rows[-1])[0]) == 1788912000000  # 2026-09-10T00:00Z bucket (covers window end)


@pytest.mark.skipif(not (PRICE_AUTHORITY_DIR / "BTCUSDT_1h.jsonl").exists(), reason="price authority not present")
def test_price_extension_not_required() -> None:
    """Track H conclusion: frozen authority covers the full window; no extension."""
    ext = REPO / "data" / "processed" / "price_1h_ext"
    assert not ext.exists(), "extension was built although frozen authority already covers the window"


# ---------- Track C: H5 anchors remain untouched ----------

def test_h5_frozen_anchors_unchanged() -> None:
    import hashlib

    r = hashlib.sha256((REPO / "docs/external-audit-01/h5-orderflow-imbalance-01/H5_RESULT.json").read_bytes()).hexdigest()
    assert r == "2427310dbed8445b1e39b1feaba7a8289918ab79a258f66b065da7cf2b7fe60f"
    m = hashlib.sha256((REPO / "docs/external-audit-01/h5-orderflow-imbalance-01/H5_MANIFEST.json").read_bytes()).hexdigest()
    assert m == "29ececb759aff059282a0324b3b94b4bcd13b35b51060c6c742f2eaa48db0a86"
