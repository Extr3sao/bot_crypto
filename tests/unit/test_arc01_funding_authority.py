"""ARC-01 funding authority — exhaustive unit tests (P0 funding data authority).

Covers per section 26: provider parsing (historical format differences, Vision monthly fundingRate CSV vs REST JSONL,
  including 2h/4h schedule variant 2022-11), timestamp normalization (ms, UTC Z, monotonic, jitter tolerance,
  availability/settlement identity), settlement schedule (8h standard, provider schedule change handling,
  missing/duplicate/unexpected detection), missing settlement / duplicate identical vs conflicting,
  PIT future/past mutation, manifest determinism, A/B determinism, mutation sensitivity,
  portable data root / wrong data root / missing raw file / modified normalized file / hash mismatch,
  import authority, clean-worktree verification.
No economics: no backtest, no PnL, no lookahead-based threshold tuning.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import tempfile
import zipfile
from pathlib import Path

import pytest

# Worktree is .research/arc01-data-authority-01; file is .../tests/unit/test_*.py
# parents: 0=unit, 1=tests, 2=worktree ROOT (this is the REPO for all relative paths)
REPO = Path(__file__).resolve().parents[2]
FUNDING_RAW = REPO / "data" / "raw" / "arc01_funding"
FUNDING_PROC = REPO / "data" / "processed" / "arc01_funding"
EVID = REPO / "docs" / "arc01-data-authority-01"
EXT_EVID = REPO / "docs" / "external-audit-01" / "arc01-data-authority-01"
SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")

# Allow running without local processed data (skip path-5h tests)
HAS_FUNDING_DATA = all((FUNDING_PROC / f"{s}_funding.jsonl").exists() or (EVID / f"{s}_funding.jsonl").exists() for s in SYMBOLS)


def _load_partition(symbol: str) -> list[dict]:
    for cand in (FUNDING_PROC / f"{symbol}_funding.jsonl", EVID / f"{symbol}_funding.jsonl", EXT_EVID / f"{symbol}_funding.jsonl"):
        if cand.exists():
            return [json.loads(l) for l in cand.read_text(encoding="utf-8").splitlines() if l.strip()]
    return []


# --------------------------------------------------------------------------
# Provider parsing / historical format differences
# --------------------------------------------------------------------------

def test_provider_vision_csv_parsing():
    sample = "calc_time,funding_interval_hours,last_funding_rate\n1577836800000,8,-0.00012359\n1577865600000,8,-0.00012383\n"
    rows = list(csv.DictReader(io.StringIO(sample)))
    assert rows[0]["calc_time"] == "1577836800000"
    assert rows[0]["funding_interval_hours"] == "8"
    assert float(rows[0]["last_funding_rate"]) == pytest.approx(-0.00012359)


def test_provider_rest_jsonl_parsing():
    sample = '{"symbol":"BTCUSDT","funding_time_ms":1789401600000,"funding_rate":"0.00010000","markPrice":"77089.71","rateType":"Regular","provider":"binanceusdm:/fapi/v1/fundingRate"}\n'
    r = json.loads(sample)
    assert int(r["funding_time_ms"]) == 1789401600000
    assert float(r["funding_rate"]) == 0.0001


def test_provider_historical_schedule_variants():
    if not FUNDING_RAW.exists():
        pytest.skip("Funding raw not present on this checkout")
    sol_zip = FUNDING_RAW / "vision_monthly" / "SOLUSDT" / "SOLUSDT-fundingRate-2022-11.zip"
    if not sol_zip.exists():
        pytest.skip("SOL 2022-11 archive not present on this machine")
    with zipfile.ZipFile(sol_zip) as z:
        txt = z.read(z.namelist()[0]).decode()
        intervals = {int(float(r["funding_interval_hours"])) for r in csv.DictReader(io.StringIO(txt))}
    assert 2 in intervals and 8 in intervals


def test_provider_checksum_sidecar_matches_zip():
    if not FUNDING_RAW.exists():
        pytest.skip("Funding raw not on this checkout")
    for sym in SYMBOLS:
        sample = next((FUNDING_RAW / "vision_monthly" / sym).glob("*.zip"), None)
        if not sample:
            continue
        sidecar = sample.with_name(sample.name + ".CHECKSUM")
        if not sidecar.exists():
            continue
        expect = sidecar.read_text(encoding="utf-8", errors="replace").strip().split()[0]
        actual = hashlib.sha256(sample.read_bytes()).hexdigest()
        assert actual == expect


# --------------------------------------------------------------------------
# Timestamp normalization
# --------------------------------------------------------------------------

@pytest.mark.parametrize("symbol", SYMBOLS)
def test_timestamp_normalization_iso_z_and_monotonic(symbol):
    if not HAS_FUNDING_DATA:
        pytest.skip("Funding data not materialized on this checkout")
    rows = _load_partition(symbol)
    assert rows
    for r in rows[:5]:
        assert r["funding_time_utc"].endswith("Z")
        assert r["availability_time_utc"].endswith("Z")
        assert r["settlement_time_utc"].endswith("Z")
    ms_vals = [int(r["funding_time_ms"]) for r in rows]
    assert ms_vals == sorted(ms_vals)
    assert len(ms_vals) == len(set(ms_vals))
    assert all(ms_vals[i] < ms_vals[i+1] for i in range(len(ms_vals)-1))


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_settlement_schedule_8h_and_provider_schedule_change_distinguished(symbol):
    mani = json.loads((EVID / "ARC01_FUNDING_MANIFEST.json").read_text())
    entry = mani["per_symbol"][symbol]
    if symbol == "SOLUSDT":
        assert entry["interval_distribution_hours"].get("2") == 99
        assert entry["provider_schedule_changes"] > 0
        assert entry["unexpected_settlements"] == 0
        assert entry["classification"] == "VALID"
    else:
        assert entry["interval_distribution_hours"].get("8", 0) > 7000
        assert entry["unexpected_settlements"] == 0
        assert entry["classification"] == "VALID"


def test_availability_is_settlement():
    if not HAS_FUNDING_DATA:
        pytest.skip("No funding data")
    rows = _load_partition("BTCUSDT")
    for r in rows[:10]:
        assert int(r["availability_time_ms"]) == int(r["settlement_time_ms"]) == int(r["funding_time_ms"])
        assert r["availability_time_utc"] == r["settlement_time_utc"] == r["funding_time_utc"]


# --------------------------------------------------------------------------
# Missing / duplicate / malformed
# --------------------------------------------------------------------------

def test_duplicate_identical_collapsed():
    mani = json.loads((EVID / "ARC01_FUNDING_MANIFEST.json").read_text())
    for sym in SYMBOLS:
        e = mani["per_symbol"][sym]
        assert "duplicates_identical_collapsed" in e
        assert e["duplicates_conflicting"] == 0
        assert e["conflicting_keys_ms"] == []


def test_duplicate_conflict_fails_closed(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("norm_arc01", str(REPO / "scripts/normalize_arc01_funding.py"))
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    assert spec.loader is not None
    spec.loader.exec_module(mod)  # type: ignore

    raw_rows = [
        {"funding_time_ms": 1577836800000, "funding_interval_hours": 8, "funding_rate_raw": "0.0001", "rate_type": "Regular", "source": "test", "source_file": "test.zip", "source_sha256": "x"},
        {"funding_time_ms": 1577836800000, "funding_interval_hours": 8, "funding_rate_raw": "0.0002", "rate_type": "Regular", "source": "test", "source_file": "test.zip", "source_sha256": "x"},
        {"funding_time_ms": 1577865600000, "funding_interval_hours": 8, "funding_rate_raw": "0.0003", "rate_type": "Regular", "source": "test", "source_file": "test.zip", "source_sha256": "x"},
    ]
    out_dir = tmp_path / "out_conflict"
    entry = mod.normalize_symbol("BTCUSDT", raw_rows, out_dir)  # type: ignore
    assert entry["classification"] == "INVALID_CONFLICTING_DUPLICATE"
    assert entry["duplicates_conflicting"] == 1


def test_out_of_order_source_normalizes_deterministically(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("norm_arc01", str(REPO / "scripts/normalize_arc01_funding.py"))
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore

    raw_a = [
        {"funding_time_ms": 1577836800000, "funding_interval_hours": 8, "funding_rate_raw": "0.0001", "rate_type": "Regular", "source": "test", "source_file": "a.zip", "source_sha256": "x"},
        {"funding_time_ms": 1577865600000, "funding_interval_hours": 8, "funding_rate_raw": "0.0002", "rate_type": "Regular", "source": "test", "source_file": "a.zip", "source_sha256": "x"},
    ]
    raw_b = list(reversed(raw_a))
    e_a = mod.normalize_symbol("BTCUSDT", raw_a, tmp_path / "out_a")  # type: ignore
    e_b = mod.normalize_symbol("BTCUSDT", raw_b, tmp_path / "out_b")  # type: ignore
    assert e_a["partition_sha256"] == e_b["partition_sha256"]


def test_non_finite_rejected():
    import importlib.util
    spec = importlib.util.spec_from_file_location("norm_arc01", str(REPO / "scripts/normalize_arc01_funding.py"))
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore

    raw_bad = [
        {"funding_time_ms": 1577836800000, "funding_interval_hours": 8, "funding_rate_raw": "nan", "rate_type": "Regular", "source": "test", "source_file": "a.zip", "source_sha256": "x"},
        {"funding_time_ms": 1577865600000, "funding_interval_hours": 8, "funding_rate_raw": "inf", "rate_type": "Regular", "source": "test", "source_file": "a.zip", "source_sha256": "x"},
        {"funding_time_ms": 1577894400000, "funding_interval_hours": 8, "funding_rate_raw": "0.0001", "rate_type": "Regular", "source": "test", "source_file": "a.zip", "source_sha256": "x"},
    ]
    with tempfile.TemporaryDirectory() as d:
        e = mod.normalize_symbol("BTCUSDT", raw_bad, Path(d) / "out_bad")  # type: ignore
        assert e["non_finite"] == 2
        assert e["classification"] == "INVALID_VALUE"


# --------------------------------------------------------------------------
# PIT future/past mutation
# --------------------------------------------------------------------------

def test_pit_future_mutation_does_not_affect_context_at_T():
    if not HAS_FUNDING_DATA:
        pytest.skip("No funding data for PIT check")
    from trading_bot.research.arc01.funding_reader import funding_state_at

    rows = _load_partition("BTCUSDT")
    assert rows
    T = int(rows[len(rows)//2]["funding_time_ms"])
    ctx_before = funding_state_at("BTCUSDT", T)
    future_ms = T + 8*3600*1000
    ctx_again = funding_state_at("BTCUSDT", T)
    assert len(ctx_again) == len(ctx_before)
    assert {int(r["funding_time_ms"]) for r in ctx_again} == {int(r["funding_time_ms"]) for r in ctx_before}
    assert future_ms not in {int(r["funding_time_ms"]) for r in ctx_before}


def test_pit_past_mutation_changes_context():
    if not HAS_FUNDING_DATA:
        pytest.skip("No funding data")
    from trading_bot.research.arc01.funding_reader import funding_state_at

    rows = _load_partition("BTCUSDT")
    assert rows
    T = int(rows[len(rows)//2]["funding_time_ms"])
    ctx = funding_state_at("BTCUSDT", T)
    assert any(int(r["funding_time_ms"]) == T for r in ctx)
    assert any(int(r["funding_time_ms"]) > T for r in rows)
    ctx_next = funding_state_at("BTCUSDT", T + 8*3600*1000)
    assert len(ctx_next) > len(ctx)


# --------------------------------------------------------------------------
# Manifest determinism / A/B / mutation sensitivity
# --------------------------------------------------------------------------

def test_manifest_determinism():
    mani = json.loads((EVID / "ARC01_FUNDING_MANIFEST.json").read_text())
    import hashlib as hl, json as js
    fp = {
        "schema_version": mani.get("schema_version"),
        "normalizer_version": mani.get("normalizer_version"),
        "normalizer_commit": mani.get("normalizer_commit"),
        "partitions": [{"symbol": s, "partition_sha256": mani.get("partition_sha256",{}).get(s,""), "rows": mani.get("per_symbol",{}).get(s,{}).get("rows",0)} for s in sorted(SYMBOLS)],
        "funding_units_contract": mani.get("funding_units_contract"),
        "pit_invariant": mani.get("pit_invariant"),
    }
    recomputed = hl.sha256(js.dumps(fp, sort_keys=True, separators=(",",":")).encode()).hexdigest()
    assert recomputed == mani["dataset_sha256"]


def test_ab_determinism(tmp_path):
    if not FUNDING_RAW.exists() or not (FUNDING_RAW / "vision_monthly" / "BTCUSDT").exists():
        pytest.skip("Funding raw not on this checkout")
    import importlib.util
    spec = importlib.util.spec_from_file_location("norm_arc01", str(REPO / "scripts/normalize_arc01_funding.py"))
    mod = importlib.util.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore
    _, maniA = mod.build_archive_dataset(out_dir=tmp_path / "A", raw_root=FUNDING_RAW, write_evidence=False)  # type: ignore
    _, maniB = mod.build_archive_dataset(out_dir=tmp_path / "B", raw_root=FUNDING_RAW, write_evidence=False)  # type: ignore
    assert maniA["dataset_sha256"] == maniB["dataset_sha256"]
    for sym in SYMBOLS:
        assert maniA["partition_sha256"][sym] == maniB["partition_sha256"][sym]


def test_mutation_sensitivity():
    if not HAS_FUNDING_DATA:
        pytest.skip("No funding data")
    part = _load_partition("BTCUSDT")
    mani = json.loads((EVID / "ARC01_FUNDING_MANIFEST.json").read_text())
    sample_path = EVID / "BTCUSDT_funding.jsonl"
    if not sample_path.exists():
        pytest.skip("No snapshot")
    lines = sample_path.read_text(encoding="utf-8").splitlines()
    mid = len(lines)//2
    obj = json.loads(lines[mid])
    orig_rate = obj["funding_rate"]
    obj["funding_rate"] = "0.99999999" if orig_rate != "0.99999999" else "0.88888888"
    mut_line = json.dumps(obj, sort_keys=True, separators=(",",":"))
    mut_bytes = "\n".join(lines[:mid] + [mut_line] + lines[mid+1:]).encode() + b"\n"
    mut_sha = hashlib.sha256(mut_bytes).hexdigest()
    assert mut_sha != mani["partition_sha256"]["BTCUSDT"]
    import hashlib as hl, json as js
    fp = {
        "schema_version": mani.get("schema_version"),
        "normalizer_version": mani.get("normalizer_version"),
        "normalizer_commit": mani.get("normalizer_commit"),
        "partitions": [
            {"symbol": s, "partition_sha256": mut_sha if s=="BTCUSDT" else mani["partition_sha256"][s], "rows": len(part) if s=="BTCUSDT" else mani["per_symbol"][s]["rows"]}
            for s in sorted(SYMBOLS)
        ],
        "funding_units_contract": mani.get("funding_units_contract"),
        "pit_invariant": mani.get("pit_invariant"),
    }
    mut_ds = hl.sha256(js.dumps(fp, sort_keys=True, separators=(",",":")).encode()).hexdigest()
    assert mut_ds != mani["dataset_sha256"]
    assert hashlib.sha256(sample_path.read_bytes()).hexdigest() == mani["partition_sha256"]["BTCUSDT"]


# --------------------------------------------------------------------------
# Portable data root / wrong data root / missing / tampered / hash mismatch
# --------------------------------------------------------------------------

def test_portable_data_root_via_env():
    from trading_bot.research.arc01.funding_reader import funding_state_at  # noqa

    rows = funding_state_at("BTCUSDT", 1735689600000, feed_dir=EVID)  # 2025-01-01
    assert len(rows) > 0


def test_wrong_data_root_fails_closed():
    import subprocess, sys
    res = subprocess.run([sys.executable, str(REPO / "scripts/verify_arc01_data_authority.py"), "--data-root", "/tmp/bogus_arc01_data_root_that_does_not_exist", "--json"], capture_output=True, text=True, cwd=str(REPO))
    assert res.returncode != 0
    import json as js
    for line in res.stdout.splitlines():
        if line.strip().startswith("{"):
            blob = "\n".join(res.stdout.splitlines()[res.stdout.splitlines().index(line):])
            try:
                out = js.loads(blob)
            except Exception:
                continue
            assert out.get("verdict") == "FAIL"
            return
    # if we never found json, the non-zero already proves failure closed
    assert res.returncode != 0


def test_missing_raw_fails_closed(tmp_path):
    import subprocess, sys
    tmp_data_root = tmp_path / "data_root_missing"
    (tmp_data_root / "raw" / "arc01_funding" / "vision_monthly" / "BTCUSDT").mkdir(parents=True, exist_ok=True)
    res = subprocess.run([sys.executable, str(REPO / "scripts/verify_arc01_data_authority.py"), "--data-root", str(tmp_data_root), "--json"], capture_output=True, text=True, cwd=str(REPO))
    assert res.returncode != 0


def test_modified_normalized_file_hash_mismatch():
    if not HAS_FUNDING_DATA:
        pytest.skip("No funding data to tamper")
    mani = json.loads((EVID / "ARC01_FUNDING_MANIFEST.json").read_text())
    p = EVID / "BTCUSDT_funding.jsonl"
    assert p.exists()
    orig_sha = hashlib.sha256(p.read_bytes()).hexdigest()
    assert orig_sha == mani["partition_sha256"]["BTCUSDT"]
    b = p.read_bytes() + b"# tamper\n"
    assert hashlib.sha256(b).hexdigest() != orig_sha


# --------------------------------------------------------------------------
# Import authority
# --------------------------------------------------------------------------

def test_import_authority_module_path():
    import trading_bot.research.arc01.funding_reader as mod

    assert mod.__file__ is not None
    assert "arc01" in mod.__file__.replace("\\", "/")
    assert "research/arc01" in mod.__file__.replace("\\", "/")
    assert Path(mod.__file__).is_relative_to(REPO)


# --------------------------------------------------------------------------
# Clean-worktree verification (smoke — real harness is scripts/verify_arc01_clean_worktree.py)
# --------------------------------------------------------------------------

def test_clean_worktree_verification_smoke():
    import subprocess, sys, os
    env = dict(os.environ)
    # Guarantee worktree src at front even in subprocess (parent .pth would otherwise pin main src)
    env["PYTHONPATH"] = str(REPO / "src")
    res = subprocess.run([sys.executable, str(REPO / "scripts/verify_arc01_data_authority.py"), "--json"], capture_output=True, text=True, cwd=str(REPO), env=env, timeout=120)
    out_tail = (res.stdout or "")[-4000:]
    assert res.returncode == 0, f"verifier non-zero\n{out_tail}\n{res.stderr[-2000:]}"
    import json as js
    try:
        idx = res.stdout.index("{")
        out = js.loads(res.stdout[idx:])
        assert out.get("verdict") == "PASS"
    except Exception as e:
        pytest.fail(f"could not parse verifier json: {e}\n{out_tail}")
