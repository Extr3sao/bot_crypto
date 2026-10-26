"""Adversarial fixtures for ``scripts/exp004a_verify.py``.

Each test builds a small, internally consistent evidence tree, then breaks exactly one property
and asserts that the verifier names the break. The invariant under test is RFC-051's
``FALSE_SUCCESS = 0``: a mutated, missing, stale, mislabelled or over-claimed artifact must never
come back as ``PASS``.

The fixtures are synthetic and are never presented as market observations. Nothing here reads or
writes ``data/exp004a`` or ``data/forward``; every path is inside ``tmp_path``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import exp004a_verify as verify  # noqa: E402

DAY_MS = 86_400_000
INTERVAL_MS = {"1h": 3_600_000, "15m": 900_000}
DAY_ONE = "2026-03-01"
DAY_TWO = "2026-03-02"


def _epoch(day: str) -> int:
    from datetime import UTC, datetime

    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000)


def _write_bars(path: Path, day: str, *, late: bool, lookahead: bool = False) -> int:
    """Append one UTC day of hourly bars; return the file length after the append."""
    path.parent.mkdir(parents=True, exist_ok=True)
    start = _epoch(day)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        for hour in range(24):
            ts = start + hour * INTERVAL_MS["1h"]
            close = ts + INTERVAL_MS["1h"]
            # One millisecond past the declared bound: exactly-at-the-bound is still "timely",
            # and a fixture that sat on the boundary would not be backfilled at all.
            fetched = close + (7_200_001 if late else 60_000)
            if lookahead:
                fetched = close - 60_000
            bar = {
                "closed": True,
                "fetched_at_ms": fetched,
                "interval": "1h",
                "ts": ts,
                "payload_sha256": "0" * 64,
            }
            handle.write(json.dumps(bar, sort_keys=True) + "\n")
    return path.stat().st_size


def _record(
    day: str,
    seq: int,
    prev: str,
    series: dict[str, dict[str, Any]],
    *,
    label: str,
    admissible: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "admissible": admissible,
        "class": label,
        "coverage_required": 0.9,
        "day": day,
        "lag_bounds_ms": {"1h": 7_200_000},
        "prev_sha256": prev,
        "sealed_at_utc": "2026-03-03T00:00:00Z",
        "seq": seq,
        "series": series,
        "version": "PROSPECTIVE_ATTESTATION_V1",
    }
    payload["sha256"] = verify.record_digest(payload)
    return payload


def build_evidence(
    base: Path,
    *,
    late_day_two: bool = True,
    lookahead: bool = False,
    label_two: str | None = None,
) -> dict[str, Path]:
    """A consistent two-day 1h lane: day one backfilled, day two timely (or as asked)."""
    evidence = base / "evidence"
    store = evidence / "data/forward/edge03"
    ledger_path = evidence / "data/exp004a/admission_1h.jsonl"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    day_one: dict[str, dict[str, Any]] = {}
    for asset in ("BTC", "ETH", "SOL"):
        path = store / f"1h/{asset}.jsonl"
        end = _write_bars(path, DAY_ONE, late=True)
        day_one[f"1h:{asset}"] = {
            "asset": asset,
            "byte_end": end,
            "expected_bars": 24,
            "interval": "1h",
            "sha256": verify.sha256_file(path, end),
            "stored_bars": 24,
        }

    day_two: dict[str, dict[str, Any]] = {}
    for asset in ("BTC", "ETH", "SOL"):
        path = store / f"1h/{asset}.jsonl"
        end = _write_bars(path, DAY_TWO, late=late_day_two, lookahead=lookahead)
        day_two[f"1h:{asset}"] = {
            "asset": asset,
            "byte_end": end,
            "expected_bars": 24,
            "interval": "1h",
            "sha256": verify.sha256_file(path, end),
            "stored_bars": 24,
        }

    one = _record(DAY_ONE, 1, "0" * 64, day_one, label="DENSE_BUT_BACKFILLED", admissible=False)
    two = _record(
        DAY_TWO,
        2,
        one["sha256"],
        day_two,
        label=label_two or ("PROSPECTIVELY_OBSERVED" if not late_day_two else "DENSE_BUT_BACKFILLED"),
        admissible=not late_day_two,
    )
    ledger_path.write_text(
        json.dumps(one, sort_keys=True) + "\n" + json.dumps(two, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    inventory = {
        "admission": {
            "lanes": {
                "1h": {
                    "chain_tip_sha256": two["sha256"],
                    "records": 2,
                    "admissible": int(not late_day_two),
                }
            },
            "capture": {"start_utc": "2026-10-22T00:00:00Z", "end_utc": "2027-01-20T00:00:00Z"},
        },
        "tracked_references": {},
    }
    handoff = evidence / "docs/agentic/exp004a/handoff"
    handoff.mkdir(parents=True, exist_ok=True)
    (handoff / "EVIDENCE_INVENTORY.json").write_text(
        json.dumps(inventory, sort_keys=True), encoding="utf-8", newline="\n"
    )
    return {"evidence": evidence, "ledger": ledger_path, "store": store, "handoff": handoff}


def _ctx(base: Path, evidence: Path) -> verify.Context:
    return verify.Context(base, evidence, base / "out")


def _rows(path: Path) -> list[dict[str, Any]]:
    return verify.load_jsonl(path)[0]


def _ledgers(path: Path) -> dict[str, list[dict[str, Any]]]:
    return {"1h": _rows(path), "1h+15m": []}


# --------------------------------------------------------------------------- #
# V-DATA  (T-04, T-05, T-18)
# --------------------------------------------------------------------------- #
def test_t04_a_rewritten_bar_breaks_its_sealed_prefix(tmp_path: Path) -> None:
    built = build_evidence(tmp_path)
    assert verify.check_prefix_sweep(_ctx(tmp_path, built["evidence"]), _ledgers(built["ledger"])).status == "PASS"

    bar_file = built["store"] / "1h/BTC.jsonl"
    original = bar_file.read_bytes()
    # Same length, same line count, inside the sealed prefix: only the bytes change. Appending a
    # line would be legitimate growth and must *not* be reported, which is why it is not used here.
    bar_file.write_bytes(original.replace(b'"interval": "1h"', b'"interval": "1H"', 1))

    finding = verify.check_prefix_sweep(_ctx(tmp_path, built["evidence"]), _ledgers(built["ledger"]))
    assert finding.status == "FAIL"
    assert finding.reason_code == "DIGEST_MISMATCH"


def test_t04b_an_appended_bar_is_growth_not_tampering(tmp_path: Path) -> None:
    built = build_evidence(tmp_path)
    bar_file = built["store"] / "1h/BTC.jsonl"
    bar_file.write_bytes(bar_file.read_bytes() + b'{"closed": true, "ts": 1772323200000}\n')

    finding = verify.check_prefix_sweep(_ctx(tmp_path, built["evidence"]), _ledgers(built["ledger"]))
    assert finding.status == "PASS", "yesterday's attestation must survive today's append"


def test_t05_absent_store_is_blocked_not_passed(tmp_path: Path) -> None:
    built = build_evidence(tmp_path)
    for path in (built["store"] / "1h").glob("*.jsonl"):
        path.unlink()

    finding = verify.check_prefix_sweep(_ctx(tmp_path, built["evidence"]), _ledgers(built["ledger"]))
    assert finding.status == "BLOCKED"
    assert finding.reason_code == "SOURCE_BYTES_UNAVAILABLE"


def test_t18_a_truncated_jsonl_line_is_corruption(tmp_path: Path) -> None:
    built = build_evidence(tmp_path)
    path = built["ledger"]
    payload = path.read_text(encoding="utf-8")
    path.write_text(payload[:-60], encoding="utf-8", newline="\n")

    rows, errors = verify.load_jsonl(path)
    assert errors, "a truncated record must be reported, not silently dropped"
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# V-ADMISSION  (T-06, T-07, T-08, T-09)
# --------------------------------------------------------------------------- #
def _admission_fixture(tmp_path: Path, **kwargs: Any) -> tuple[verify.Context, dict[str, list[dict[str, Any]]], dict[str, Any]]:
    built = build_evidence(tmp_path, **kwargs)
    manifest = {
        "two_phase": {
            "capture": {
                "start_utc": "2026-10-22T00:00:00Z",
                "end_utc": "2027-01-20T00:00:00Z",
                "target_days": 90,
            }
        }
    }
    return _ctx(tmp_path, built["evidence"]), _ledgers(built["ledger"]), manifest


def test_t06_a_backfilled_day_mislabelled_prospective_is_caught(tmp_path: Path) -> None:
    ctx, ledgers, manifest = _admission_fixture(tmp_path, late_day_two=True, label_two="PROSPECTIVELY_OBSERVED")
    finding = verify.check_admission_replay(ctx, ledgers, manifest)
    assert finding.status == "FAIL"
    assert finding.reason_code == "ADMISSION_REPLAY_MISMATCH"
    assert finding.observed["mismatches"][0]["sealed"] == "PROSPECTIVELY_OBSERVED"


def test_t07_a_bar_fetched_before_its_close_is_lookahead(tmp_path: Path) -> None:
    ctx, ledgers, _ = _admission_fixture(tmp_path, late_day_two=False, lookahead=True)
    finding = verify.check_prefix_sweep(ctx, ledgers)
    assert finding.status == "FAIL"
    assert finding.reason_code == "LOOKAHEAD_DETECTED"


def _day_bars(start: int, count: int, *, lag: int) -> list[dict[str, Any]]:
    return [
        {"closed": True, "fetched_at_ms": start + hour * INTERVAL_MS["1h"] + INTERVAL_MS["1h"] + lag, "ts": start + hour * INTERVAL_MS["1h"]}
        for hour in range(count)
    ]


def test_t08_a_gapped_boundary_day_is_incomplete_and_a_full_one_is_prospective() -> None:
    whole = {asset: {DAY_TWO: _day_bars(_epoch(DAY_TWO), 24, lag=60_000)} for asset in ("BTC", "ETH", "SOL")}
    gapped = {asset: {DAY_TWO: _day_bars(_epoch(DAY_TWO), 12, lag=60_000)} for asset in ("BTC", "ETH", "SOL")}
    late = {asset: {DAY_TWO: _day_bars(_epoch(DAY_TWO), 24, lag=7_200_001)} for asset in ("BTC", "ETH", "SOL")}

    assert verify.classify_day(DAY_TWO, {"1h": whole}, {"1h": 7_200_000})["classification"] == "PROSPECTIVELY_OBSERVED"
    assert verify.classify_day(DAY_TWO, {"1h": gapped}, {"1h": 7_200_000})["classification"] == "INCOMPLETE"
    assert verify.classify_day(DAY_TWO, {"1h": late}, {"1h": 7_200_000})["classification"] == "DENSE_BUT_BACKFILLED"
    # A joint lane cannot be satisfied by one interval alone.
    assert verify.classify_day(DAY_TWO, {"1h": whole}, {"1h": 7_200_000, "15m": 1_800_000})["classification"] == "INCOMPLETE"


def test_t09_a_duplicated_day_is_named_and_the_count_does_not_drift(tmp_path: Path) -> None:
    built = build_evidence(tmp_path)
    rows = _rows(built["ledger"])
    duplicated = dict(rows[1])
    duplicated["seq"] = 3
    duplicated["prev_sha256"] = rows[1]["sha256"]
    duplicated["sha256"] = verify.record_digest(duplicated)
    with built["ledger"].open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(duplicated, sort_keys=True) + "\n")

    first = verify.check_chain(_ctx(tmp_path, built["evidence"]), _ledgers(built["ledger"]), {})
    second = verify.check_chain(_ctx(tmp_path, built["evidence"]), _ledgers(built["ledger"]), {})
    assert first.status == "FAIL"
    assert first.reason_code == "LEDGER_DUPLICATE"
    assert first.observed == second.observed, "a replay must not change the verdict or its evidence"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, timeout=120
    )
    return completed.stdout.strip()


def _init_repo(base: Path) -> tuple[Path, str]:
    repo = base / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "x.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "verifier@example.test")
    _git(repo, "config", "user.name", "verifier-b")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "protocol and measurement code")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_t12_code_changed_after_the_evaluated_commit_is_a_stale_report(tmp_path: Path) -> None:
    repo, evaluated = _init_repo(tmp_path)
    (repo / "src" / "x.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "a change after the report")
    report = {"authority": {"evaluated_commit": evaluated, "builder_report_claimed_head": evaluated}}
    manifest = {
        "phase_one_commits": {"protocol_and_measurement_code": evaluated},
        "controls": {"code_scope_paths": ["src"]},
    }

    finding = verify.check_authority(verify.Context(repo, repo, tmp_path / "out"), report, manifest)
    assert finding.status == "FAIL"
    assert finding.reason_code == "REPORT_CODE_STALE"
    assert finding.observed["code_drift_since_evaluated"] == ["src/x.py"]


def test_t02_a_protocol_commit_outside_the_history_breaks_provenance(tmp_path: Path) -> None:
    repo, evaluated = _init_repo(tmp_path)
    _git(repo, "checkout", "-q", "--orphan", "unrelated")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "unrelated root")
    orphan = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", evaluated)
    report = {"authority": {"evaluated_commit": evaluated, "builder_report_claimed_head": evaluated}}
    manifest = {
        "phase_one_commits": {"protocol_and_measurement_code": orphan},
        "controls": {"code_scope_paths": ["src"]},
    }

    finding = verify.check_authority(verify.Context(repo, repo, tmp_path / "out"), report, manifest)
    assert finding.status == "FAIL"
    assert finding.reason_code == "EVALUATED_SOURCE_MISMATCH"
    assert finding.observed["protocol_is_ancestor_of_evaluated"] is False


def test_t03_git_clock_alone_is_not_a_chronology_proof(tmp_path: Path) -> None:
    repo, evaluated = _init_repo(tmp_path)
    (repo / "data/exp004a").mkdir(parents=True)
    manifest = {
        "two_phase": {"capture": {"start_utc": "2026-10-22T00:00:00Z"}},
        "phase_one_commits": {"protocol_and_measurement_code": evaluated},
    }

    finding = verify.check_chronology(verify.Context(repo, repo, tmp_path / "out"), manifest)
    assert finding.status == "BLOCKED"
    assert finding.reason_code == "TIME_PROOF_WEAK"


def test_t17_two_sweeps_of_one_snapshot_agree_exactly(tmp_path: Path) -> None:
    built = build_evidence(tmp_path)
    ctx = _ctx(tmp_path, built["evidence"])
    first = verify.check_prefix_sweep(ctx, _ledgers(built["ledger"]))
    second = verify.check_prefix_sweep(ctx, _ledgers(built["ledger"]))
    assert first.status == second.status == "PASS"
    assert first.observed["verified"] == second.observed["verified"]
    assert first.observed["errors_by_kind"] == second.observed["errors_by_kind"]


# --------------------------------------------------------------------------- #
# V-COST  (T-10, T-11)
# --------------------------------------------------------------------------- #
def _tape(tmp_path: Path, *, size: float, report: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    evidence = tmp_path / "cost"
    tape = evidence / "data/st6/ST6_OBSERVATIONS.jsonl"
    tape.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ask": 100.02,
        "asset": "BTCUSDT",
        "bid": 100.00,
        "depth": {"available": True},
        "impact": {"buy_bps": 0.0, "filled_buy": True, "filled_sell": True, "sell_bps": 0.0, "size_usdt": size},
    }
    tape.write_text(json.dumps(row) + "\n", encoding="utf-8", newline="\n")
    manifest = {"economics": {"taker_fee_bps_per_side": 10.0, "declared_notional_usdt": 500.0}}
    return tape, {"manifest": manifest, "report": report}


def test_t10_a_500_usdt_cost_claim_without_a_walk_is_refused(tmp_path: Path) -> None:
    report = {"cost": {"observed_median_bps": {"BTC": 21.9998}}}
    _, bundle = _tape(tmp_path, size=200.0, report=report)
    ctx = verify.Context(tmp_path, tmp_path / "cost", tmp_path / "out")
    _, size = verify.check_cost(ctx, bundle["manifest"], bundle["report"])
    assert size.status == "PASS", "the honest reading is that the declared size was never walked"
    assert size.observed["declared_size_walked"] is False


def test_t11_an_invented_round_trip_cost_is_scope_unproven(tmp_path: Path) -> None:
    report = {"cost": {"observed_median_bps": {"BTC": 21.9998}}}
    _, bundle = _tape(tmp_path, size=200.0, report=report)
    ctx = verify.Context(tmp_path, tmp_path / "cost", tmp_path / "out")
    cost, _ = verify.check_cost(ctx, bundle["manifest"], bundle["report"])
    assert cost.status == "BLOCKED"
    assert cost.reason_code == "COST_SCOPE_UNPROVEN"
    assert cost.observed["medians"]["BTC"]["median_two_spread"] > cost.observed["medians"]["BTC"]["median_one_spread"]


# --------------------------------------------------------------------------- #
# Independence and write isolation  (T-15, T-16)
# --------------------------------------------------------------------------- #
def test_t16_the_same_principal_cannot_call_itself_independent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = tmp_path / "config/preregistrations"
    manifest.mkdir(parents=True)
    (manifest / "EXP-004A.json").write_text(
        json.dumps({"controls": {"builder_identity": "EXP-004A_BUILDER_A"}}), encoding="utf-8"
    )
    monkeypatch.delenv("EXP004A_VERIFIER_PRINCIPAL", raising=False)
    finding = verify.check_independence(verify.Context(tmp_path, tmp_path, tmp_path / "out"))
    assert finding.status == "BLOCKED"
    assert finding.reason_code == "INDEPENDENCE_NOT_PROVEN"
    assert finding.observed["same_principal_as_builder"] is True


def test_t15_a_mutation_of_watched_evidence_is_reported(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    target = evidence / "data/exp004a/admission_1h.jsonl"
    target.parent.mkdir(parents=True)
    target.write_text("{}\n", encoding="utf-8", newline="\n")
    ctx = verify.Context(tmp_path, evidence, tmp_path / "out")
    before = verify.snapshot(verify.builder_owned(evidence))
    target.write_text('{"mutated": true}\n', encoding="utf-8", newline="\n")

    finding = verify.check_write_isolation(ctx, before)
    assert finding.status == "FAIL"
    assert finding.reason_code == "VERIFIER_MUTATED_SOURCE"


def test_the_containment_primitive_refuses_a_real_junction(tmp_path: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("junction control is Windows-specific")
    inside = tmp_path / "root"
    outside = tmp_path / "outside"
    (inside / "config").mkdir(parents=True)
    outside.mkdir()
    (outside / "secret.json").write_text("{}", encoding="utf-8")
    (inside / "config" / "ok.json").write_text("{}", encoding="utf-8")
    link = inside / "config" / "escape"
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, check=False, timeout=120
    )
    if made.returncode != 0 or not link.exists():
        pytest.skip("this environment cannot create a directory junction")

    assert (link / "secret.json").is_file(), "the link must reach the file for the refusal to mean anything"
    assert not verify.ensure_within(inside, link / "secret.json")
    assert verify.ensure_within(inside, inside / "config" / "ok.json")


# --------------------------------------------------------------------------- #
# Promotion  (T-19, T-20)
# --------------------------------------------------------------------------- #
def test_t19_t20_promotion_stays_closed_while_phase_two_is_open_and_days_are_short() -> None:
    finding = verify.Finding(
        "C-004",
        "PASS",
        None,
        {"recomputed_admissible_inside_window_count": 0},
        [],
    )
    blocks = verify._promotion_blocks({}, [finding])
    assert "PHASE2_CAPTURE_OPEN" in blocks
    assert "INSUFFICIENT_ADMITTED_DAYS" in blocks
    assert "DECLARED_SIZE_NOT_WALKED" in blocks
    assert "ZERO_ADMITTED_DAYS_INSIDE_CAPTURE_WINDOW" in blocks


def test_a_timeout_is_reported_as_a_budget_not_as_idempotence(tmp_path: Path) -> None:
    script = tmp_path / "scripts/exp004a_foundation.py"
    script.parent.mkdir(parents=True)
    script.write_text("import time\ntime.sleep(120)\n", encoding="utf-8")

    outcome = verify._run_bounded([sys.executable, str(script)], tmp_path, 2)
    assert outcome["timed_out"] is True
    assert outcome["exit_code"] is not None, "the tree must be killed, not abandoned"


def test_unstable_reason_codes_are_rejected_at_serialisation() -> None:
    with pytest.raises(AssertionError):
        verify.Finding("C-001", "FAIL", "MADE_UP_CODE", {}, []).to_dict()
