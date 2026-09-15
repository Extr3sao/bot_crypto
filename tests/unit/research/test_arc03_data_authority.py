"""ARC-03 data-authority contract tests (performance-blind).

Covers the normalization contract, the fail-closed rules, the frozen feature semantics,
the PIT adversarial battery and the real-authority fingerprint binding.

No economic quantity is computed: no returns, no PnL, no signal-return statistics.
"""

from __future__ import annotations

import json
import pathlib
import zipfile

import pytest

from trading_bot.research.arc03 import arc03_pit
from trading_bot.research.arc03.arc03_authority import (
    BAR_MS,
    DAY_MS,
    Kline5m,
    NO_SIGNAL_PRECEDENCE,
    common_causal_window,
    evaluate_bar,
    load_partition,
    partition_fingerprint,
    resolve_partition_dir,
)
from trading_bot.research.arc03.arc03_normalize import (
    ADMITTED_CLASSIFICATIONS,
    BAR_MS as NBAR_MS,
    EXPECTED_HEADER,
    build_manifest,
    canonical_json,
    day_shortfalls,
    month_first_open_ms,
    normalize_symbol,
    parse_daily_archive,
    parse_month,
    sha256_bytes,
    write_json_bytes,
    write_jsonl_bytes,
)

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO / "docs" / "arc03-data-authority-01" / "ARC03_DATA_MANIFEST.json"


# --------------------------------------------------------------------------- helpers
def _month_rows(month: str, *, bars: int | None = None, header: bool = False) -> list[str]:
    import calendar
    import datetime as dt

    y, m = int(month[:4]), int(month[5:])
    total = calendar.monthrange(y, m)[1] * 288
    n = total if bars is None else bars
    start = int(dt.datetime(y, m, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
    out = [EXPECTED_HEADER] if header else []
    for i in range(n):
        t = start + i * NBAR_MS
        out.append(f"{t},100.0,100.5,99.5,100.1,10,{t + NBAR_MS - 1},1000,5,4,400,0")
    return out


def _write_month(raw: pathlib.Path, symbol: str, month: str, rows: list[str]) -> pathlib.Path:
    md = raw / symbol / month
    md.mkdir(parents=True, exist_ok=True)
    zp = md / f"{symbol}-5m-{month}.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr(f"{symbol}-5m-{month}.csv", "\n".join(rows) + "\n")
    return zp


def _write_day(raw: pathlib.Path, symbol: str, date: str, rows: list[str], *, checksum: bool = True) -> pathlib.Path:
    import hashlib

    md = raw / symbol / date
    md.mkdir(parents=True, exist_ok=True)
    zp = md / f"{symbol}-5m-{date}.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr(f"{symbol}-5m-{date}.csv", "\n".join(rows) + "\n")
    if checksum:
        digest = hashlib.sha256(zp.read_bytes()).hexdigest()
        (md / (zp.name + ".CHECKSUM")).write_text(f"{digest}  {zp.name}\n", encoding="utf-8")
    return zp


def _day_rows(date: str, *, bars: int = 288) -> list[str]:
    import datetime as dt

    start = int(dt.datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp() * 1000)
    return [
        f"{start + i * NBAR_MS},100.0,100.5,99.5,100.1,10,{start + i * NBAR_MS + NBAR_MS - 1},1000,5,4,400,0"
        for i in range(bars)
    ]


# ------------------------------------------------------------------ normalization
def test_normalization_admits_a_complete_month(tmp_path: pathlib.Path) -> None:
    raw = tmp_path / "raw"
    _write_month(raw, "BTCUSDT", "2024-01", _month_rows("2024-01"))
    ledger, rows, sha = normalize_symbol("BTCUSDT", raw / "BTCUSDT", write=False)
    assert ledger[0]["classification"] == "VALID"
    assert len(rows) == 31 * 288
    assert sha is None  # write=False
    assert ledger[-1]["kind"] == "SYMBOL_SUMMARY"
    assert ledger[-1]["internal_cadence_breaks_admitted"] == 0


def test_provider_header_schema_change_is_handled(tmp_path: pathlib.Path) -> None:
    raw = tmp_path / "raw"
    with_h = _month_rows("2024-01", header=True)
    without_h = _month_rows("2024-01", header=False)
    _write_month(raw, "BTCUSDT", "2024-01", with_h)
    p_hdr = parse_month(raw / "BTCUSDT" / "2024-01" / "BTCUSDT-5m-2024-01.zip")
    assert p_hdr["entry"]["header_present"] is True
    assert p_hdr["entry"]["rows"] == 31 * 288
    _write_month(raw, "BTCUSDT", "2024-01", without_h)
    p_nohdr = parse_month(raw / "BTCUSDT" / "2024-01" / "BTCUSDT-5m-2024-01.zip")
    assert p_nohdr["entry"]["header_present"] is False
    assert p_nohdr["entry"]["rows"] == p_hdr["entry"]["rows"]


def test_conflicting_duplicate_fails_closed(tmp_path: pathlib.Path) -> None:
    raw = tmp_path / "raw"
    rows = _month_rows("2024-02")
    conflict = list(rows)
    conflict[3] = conflict[3].replace(",100.1,", ",777.7,")
    conflict.append(rows[3])
    _write_month(raw, "ETHUSDT", "2024-02", conflict)
    ledger, rows_out, _ = normalize_symbol("ETHUSDT", raw / "ETHUSDT", write=False)
    assert ledger[0]["classification"] == "INVALID_CONFLICTING_DUPLICATE"
    assert rows_out == []


def test_exact_duplicate_rows_collapse(tmp_path: pathlib.Path) -> None:
    raw = tmp_path / "raw"
    rows = _month_rows("2024-02")
    _write_month(raw, "ETHUSDT", "2024-02", rows + [rows[5]])
    p = parse_month(raw / "ETHUSDT" / "2024-02" / "ETHUSDT-5m-2024-02.zip")
    assert p["entry"]["exact_duplicate_rows_collapsed"] == 1
    assert p["entry"]["conflicting_duplicates"] == 0
    assert p["entry"]["rows"] == 29 * 288


def test_internal_gap_fails_closed_in_a_non_first_month(tmp_path: pathlib.Path) -> None:
    raw = tmp_path / "raw"
    _write_month(raw, "BTCUSDT", "2024-01", _month_rows("2024-01"))
    gapped = [r for i, r in enumerate(_month_rows("2024-02")) if i != 40]
    _write_month(raw, "BTCUSDT", "2024-02", gapped)
    ledger, rows, _ = normalize_symbol("BTCUSDT", raw / "BTCUSDT", write=False)
    cls = {e["month"]: e["classification"] for e in ledger if "month" in e}
    assert cls["2024-01"] == "VALID"
    assert cls["2024-02"] == "INVALID_GAP"
    assert len(rows) == 31 * 288


def test_first_month_partial_only_when_leading_and_running_to_month_end(tmp_path: pathlib.Path) -> None:
    raw = tmp_path / "raw"
    late_start = _month_rows("2024-03")[-100:]  # contiguous, ends at month end
    _write_month(raw, "BTCUSDT", "2024-03", late_start)
    ledger, rows, _ = normalize_symbol("BTCUSDT", raw / "BTCUSDT", write=False)
    assert ledger[0]["classification"] == "VALID_INITIAL_PARTIAL"
    assert ledger[0]["ends_at_month_end"] is True
    assert len(rows) == 100

    # a mid-month stop is NOT admitted even as the first month
    raw2 = tmp_path / "raw2"
    _write_month(raw2, "BTCUSDT", "2024-04", _month_rows("2024-04", bars=5000))
    ledger2, rows2, _ = normalize_symbol("BTCUSDT", raw2 / "BTCUSDT", write=False)
    assert ledger2[0]["classification"] == "INVALID_GAP"
    assert rows2 == []


def test_malformed_and_field_drift_fail_month_closed(tmp_path: pathlib.Path) -> None:
    raw = tmp_path / "raw"
    bad = _month_rows("2024-05")
    bad[7] = "not_a_number,100,100,99,100,10,1,1,1,1,1,1"
    _write_month(raw, "BTCUSDT", "2024-05", bad)
    ledger, rows, _ = normalize_symbol("BTCUSDT", raw / "BTCUSDT", write=False)
    assert ledger[0]["classification"] == "INVALID_VALUE"
    assert rows == []

    raw2 = tmp_path / "raw2"
    drift = _month_rows("2024-06")
    drift[9] = drift[9] + ",extra"
    _write_month(raw2, "BTCUSDT", "2024-06", drift)
    ledger2, rows2, _ = normalize_symbol("BTCUSDT", raw2 / "BTCUSDT", write=False)
    assert ledger2[0]["classification"] == "INVALID_VALUE"
    assert rows2 == []


# --------------------------------------------------------------- daily supplement
def test_daily_supplement_closes_a_monthly_shortfall(tmp_path: pathlib.Path) -> None:
    raw = tmp_path / "raw"
    daily = tmp_path / "daily"
    # 2024-01 must be complete so 2024-02 is NOT the first month
    _write_month(raw, "SOLUSDT", "2024-01", _month_rows("2024-01"))
    feb = _month_rows("2024-02")
    _write_month(raw, "SOLUSDT", "2024-02", feb[:-288])  # drop the last day
    for date in ("2024-02-29",):
        _write_day(daily, "SOLUSDT", date, _day_rows(date))
    ledger, rows, _ = normalize_symbol("SOLUSDT", raw / "SOLUSDT", write=False, daily_root=daily)
    cls = {e["month"]: e["classification"] for e in ledger if "month" in e}
    assert cls["2024-02"] == "VALID_WITH_DAILY_SUPPLEMENT"
    assert len(rows) == 31 * 288 + 29 * 288


def test_daily_supplement_requires_a_valid_daily_archive(tmp_path: pathlib.Path) -> None:
    raw = tmp_path / "raw"
    daily = tmp_path / "daily"
    _write_month(raw, "SOLUSDT", "2024-01", _month_rows("2024-01"))
    _write_month(raw, "SOLUSDT", "2024-02", _month_rows("2024-02")[:-288])
    # day present but with a WRONG checksum sidecar
    _write_day(daily, "SOLUSDT", "2024-02-29", _day_rows("2024-02-29"), checksum=False)
    (daily / "SOLUSDT" / "2024-02-29" / "SOLUSDT-5m-2024-02-29.zip.CHECKSUM").write_text(
        "0" * 64 + "  SOLUSDT-5m-2024-02-29.zip\n", encoding="utf-8"
    )
    ledger, rows, _ = normalize_symbol("SOLUSDT", raw / "SOLUSDT", write=False, daily_root=daily)
    cls = {e["month"]: e["classification"] for e in ledger if "month" in e}
    assert cls["2024-02"] == "INVALID_GAP"
    assert len(rows) == 31 * 288


def test_parse_daily_archive_rejects_short_days(tmp_path: pathlib.Path) -> None:
    daily = tmp_path / "daily"
    _write_day(daily, "BTCUSDT", "2024-01-02", _day_rows("2024-01-02", bars=287))
    assert parse_daily_archive(daily / "BTCUSDT" / "2024-01-02" / "BTCUSDT-5m-2024-01-02.zip") is None
    _write_day(daily, "BTCUSDT", "2024-01-03", _day_rows("2024-01-03"))
    assert parse_daily_archive(daily / "BTCUSDT" / "2024-01-03" / "BTCUSDT-5m-2024-01-03.zip") is not None


def test_day_shortfalls_ignores_pre_launch_days_only_for_the_first_month() -> None:
    month = "2020-09"
    days = 30
    start = month_first_open_ms(month)
    # a pure leading truncation: contiguous from 2020-09-14 00:00 to month end
    rows = [
        {"t": start + 13 * DAY_MS + i * NBAR_MS}
        for i in range((days - 13) * 288)
    ]
    assert day_shortfalls(rows, month, is_first_month=True) == {}
    later = day_shortfalls(rows, month, is_first_month=False)
    assert later  # a late start is a real coverage gap for a non-first month
    assert len(later) == 13


# --------------------------------------------------------------------- features
def _shock_partition(**overrides: object) -> Kline5m:
    return arc03_pit.build_partition(overrides=arc03_pit.shock_overrides(direction="up"))


def test_participation_shock_requires_a_strict_record() -> None:
    k = _shock_partition()
    pos = k.index[arc03_pit.slot_open_ms(arc03_pit.SHOCK_DAY, arc03_pit.SHOCK_SLOT)]
    assert evaluate_bar(k, pos)["participation_shock"] is True
    # equal to the reference max is NOT a shock
    t = k.t[pos]
    k2 = arc03_pit.build_partition(
        overrides={**arc03_pit.shock_overrides(direction="up"), t: {"o": 100.0, "h": 101.5, "l": 99.0, "c": 100.2, "v": 1000.0}}
    )
    ev = evaluate_bar(k2, k2.index[t])
    assert ev["participation_shock"] is False
    assert ev["reason"] == "NO_PARTICIPATION_SHOCK"


def test_exhaustion_direction_semantics_are_contrarian() -> None:
    up = _shock_partition()
    pos = up.index[arc03_pit.slot_open_ms(arc03_pit.SHOCK_DAY, arc03_pit.SHOCK_SLOT)]
    assert evaluate_bar(up, pos)["result"] == "SHORT"
    down = arc03_pit.build_partition(overrides=arc03_pit.shock_overrides(direction="down"))
    pos_d = down.index[arc03_pit.slot_open_ms(arc03_pit.SHOCK_DAY, arc03_pit.SHOCK_SLOT)]
    assert evaluate_bar(down, pos_d)["result"] == "LONG"


def test_exactly_half_retracement_is_not_exhaustion() -> None:
    k = arc03_pit.build_partition(
        overrides={
            **arc03_pit.shock_overrides(direction="up"),
            arc03_pit.slot_open_ms(arc03_pit.SHOCK_DAY, arc03_pit.SHOCK_SLOT): {
                "o": arc03_pit.SHOCK_O,
                "h": arc03_pit.SHOCK_H,
                "l": arc03_pit.SHOCK_L,
                "c": (arc03_pit.SHOCK_H + arc03_pit.SHOCK_L) / 2.0,
                "v": arc03_pit.SHOCK_V,
            },
        }
    )
    pos = k.index[arc03_pit.slot_open_ms(arc03_pit.SHOCK_DAY, arc03_pit.SHOCK_SLOT)]
    assert evaluate_bar(k, pos)["reason"] == "NO_EXHAUSTION"


def test_missing_reference_observation_fails_closed() -> None:
    ref = arc03_pit.slot_open_ms(arc03_pit.SHOCK_DAY, arc03_pit.SHOCK_SLOT) - DAY_MS
    k = arc03_pit.build_partition(overrides=arc03_pit.shock_overrides(direction="up"), drop={ref})
    pos = k.index[arc03_pit.slot_open_ms(arc03_pit.SHOCK_DAY, arc03_pit.SHOCK_SLOT)]
    ev = evaluate_bar(k, pos)
    assert ev["reason"] == "REFERENCE_HISTORY_INCOMPLETE"
    assert ev["emitted"] is False


def test_no_signal_precedence_is_frozen() -> None:
    assert NO_SIGNAL_PRECEDENCE[0] == "OUTSIDE_COMMON_WINDOW"
    assert NO_SIGNAL_PRECEDENCE[-1] == "INSUFFICIENT_FORWARD_PRICE_DATA"
    assert len(set(NO_SIGNAL_PRECEDENCE)) == len(NO_SIGNAL_PRECEDENCE)


def test_entry_is_strictly_after_decision_time() -> None:
    k = arc03_pit.build_partition()
    pos = 10
    decision = k.ct[pos]
    nxt = k.first_index_strictly_after(decision)
    assert nxt is not None and k.t[nxt] > decision


# ------------------------------------------------------------------------- PIT
def test_pit_battery_passes() -> None:
    checks = arc03_pit.run_battery()
    failed = [c["check"] for c in checks if not c["pass"]]
    assert not failed, f"PIT battery failures: {failed}"
    assert len(checks) >= 25


def test_reader_fails_closed_on_duplicate_slot(tmp_path: pathlib.Path) -> None:
    rec = {
        "t": 1_700_000_000_000,
        "ct": 1_700_000_299_999,
        "o": "1",
        "h": "2",
        "l": "1",
        "c": "1",
        "v": "1",
        "qv": "1",
        "n": 1,
        "tb": "1",
        "tq": "1",
        "sym": "BTCUSDT",
        "ms": "2023-11",
    }
    line = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    (tmp_path / "BTCUSDT.jsonl").write_bytes((line + "\n" + line + "\n").encode("utf-8"))
    with pytest.raises(ValueError):
        load_partition("BTCUSDT", partition_dir=tmp_path)


def test_data_root_must_be_absolute() -> None:
    with pytest.raises(ValueError):
        resolve_partition_dir("relative/path")


# ------------------------------------------------------- real authority binding
def _partitions_present() -> bool:
    d = resolve_partition_dir()
    return all((d / f"{s}.jsonl").exists() for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"))


@pytest.mark.skipif(not MANIFEST_PATH.exists(), reason="data-authority manifest not built")
def test_real_partitions_match_recorded_fingerprint() -> None:
    if not _partitions_present():
        pytest.skip("ARC-03 partitions not materialised in this checkout (gitignored data root)")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    parts = {s: load_partition(s) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}
    fp = partition_fingerprint(parts)
    assert fp["partition_sha256"] == manifest["partition_sha256"]
    assert fp["rows"] == {
        e["symbol"]: e["admitted_rows"]
        for e in (
            json.loads(l)
            for l in (MANIFEST_PATH.parent / "ARC03_DATA_QUALITY_LEDGER.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if l.strip()
        )
        if e.get("kind") == "SYMBOL_SUMMARY"
    }


@pytest.mark.skipif(not MANIFEST_PATH.exists(), reason="data-authority manifest not built")
def test_real_partitions_are_contiguous_and_unique() -> None:
    if not _partitions_present():
        pytest.skip("ARC-03 partitions not materialised in this checkout (gitignored data root)")
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        k = load_partition(sym)
        assert len(set(k.t)) == len(k.t)
        assert k.t == tuple(sorted(k.t))
        breaks = sum(1 for a, b in zip(k.t, k.t[1:]) if b - a != BAR_MS)
        assert breaks == 0, f"{sym} has {breaks} cadence breaks"
        assert all(ct == t + BAR_MS - 1 for t, ct in zip(k.t, k.ct))


@pytest.mark.skipif(not MANIFEST_PATH.exists(), reason="data-authority manifest not built")
def test_recorded_common_window_matches_partitions() -> None:
    if not _partitions_present():
        pytest.skip("ARC-03 partitions not materialised in this checkout (gitignored data root)")
    recorded = json.loads((MANIFEST_PATH.parent / "ARC03_COMMON_CAUSAL_WINDOW.json").read_text(encoding="utf-8"))
    parts = {s: load_partition(s) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}
    observed = common_causal_window(parts)
    assert observed["start_ms"] == recorded["start_ms"]
    assert observed["end_ms"] == recorded["end_ms"]


# ------------------------------------------------------------- canonical writing
def test_canonical_json_is_byte_stable(tmp_path: pathlib.Path) -> None:
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    write_json_bytes(a, {"b": 1, "a": [2, 3]})
    write_json_bytes(b, {"a": [2, 3], "b": 1})
    assert a.read_bytes() == b.read_bytes()
    assert b"\r\n" not in a.read_bytes()


def test_jsonl_writer_counts_rows_and_uses_lf(tmp_path: pathlib.Path) -> None:
    p = tmp_path / "x.jsonl"
    n = write_jsonl_bytes(p, [{"t": 1}, {"t": 2}])
    assert n == 2
    assert p.read_bytes().count(b"\n") == 2
    assert b"\r\n" not in p.read_bytes()


def test_admitted_classifications_constant() -> None:
    assert ADMITTED_CLASSIFICATIONS == {"VALID", "VALID_INITIAL_PARTIAL", "VALID_WITH_DAILY_SUPPLEMENT"}
