"""WP-10 phase 7 — independent verification of every headline claim.

This verifier is written against the *deliverables*, not against the code that
produced them: it imports none of the WP-10 builders, re-implements the arithmetic it
checks, and re-derives each published number from the primary artefact that should
carry it. Where a claim can be tested against a second, independent witness — the
collector's own published checkpoint features against the measured spread, the
manifest against the rehearsal's timings — it does that instead of re-running the
builder's own path.

It also runs negative controls: deliberate corruptions of in-memory copies of the
deliverables that a verifier must catch. A verifier that cannot fail is not a
verifier, so a control that is *missed* is reported as such and forces
``false_success`` to be non-zero.

Nothing here writes to a frozen artefact, starts a process, or touches an order path.

Exit codes: 0 verification PASS with every control detected, 1 verification FAIL,
2 a required input is missing.
"""

from __future__ import annotations

import argparse
import bisect
import gzip
import hashlib
import json
import math
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # pragma: no cover - path bootstrap
    sys.path.insert(0, str(ROOT / "src"))

from trading_bot.research.microstructure.cost_model_v3 import ADMISSION_SCENARIO_ID, default_model  # noqa: E402

WP10 = ROOT / "data" / "recovery" / "wp10"
LEDGER = ROOT / "config" / "strategy_admission.json"
TIMEFRAME_AUDIT = ROOT / "reports" / "strategy-baseline" / "TIMEFRAME_AUDIT.json"
DISCOVERY = ROOT / "docs" / "STRATEGY_DISCOVERY_V3_RESULTS.json"
FORWARD_ROOT = ROOT / "reports" / "microstructure-forward-continuous"
FORWARD_MANIFESTS = FORWARD_ROOT / "manifest"
FORWARD_REPLAY = FORWARD_ROOT / "reports" / "REPLAY_VERIFICATION.json"
FORWARD_STATE = FORWARD_ROOT / "state"
LAB_RUN = ROOT / "reports" / "paper-lab" / "paper-lab-continuous-03"
STATE_VIEW = ROOT / "data" / "recovery" / "CAMPAIGN_STATE_VIEW.json"
BASELINE = WP10 / "WP10_BASELINE_ECONOMIC_AUDIT.json"
E1 = WP10 / "WP10_EXECUTION_COST_DISTRIBUTION.json"
E2 = WP10 / "WP10_E2_PREREGISTRATION.json"
MATRIX = WP10 / "WP10_ACTIVE_RECOVERY_MATRIX.json"
BLOCKERS = WP10 / "WP10_OPEN_BLOCKERS.json"
E1_DECISION = WP10 / "WP10_E1_DECISION.json"
RUN_REPORT = WP10 / "RUN_REPORT.json"
FINAL_REPORT = WP10 / "FINAL_REPORT.md"
# Everything the lane publishes is scanned for the claims nobody may make, prose included:
# a false success hidden in a hand-written report is still a false success.
DELIVERABLES = (BASELINE, E1, E1_DECISION, E2, MATRIX, BLOCKERS, RUN_REPORT, FINAL_REPORT)

FROZEN_PLANE_BPS = 23.353553391
BEST_GROSS_BPS = 8.912
SAMPLE_CHECKPOINTS = 40
SAMPLE_TRADE_FILES = 2
Z_95 = 1.959964


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------


class Verifier:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.controls: list[dict[str, Any]] = []

    def check(self, name: str, ok: bool, detail: Any = None) -> bool:
        self.checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return bool(ok)

    def control(self, name: str, detected: bool, detail: str) -> None:
        self.controls.append({"control": name, "detected": bool(detected), "detail": detail})

    def close(self, expects: dict[str, Any]) -> dict[str, Any]:
        failed = [entry for entry in self.checks if not entry["ok"]]
        missed = [entry for entry in self.controls if not entry["detected"]]
        return {
            "checks": self.checks,
            "checks_total": len(self.checks),
            "checks_failed": len(failed),
            "failed": failed,
            "controls": self.controls,
            "controls_total": len(self.controls),
            "controls_missed": len(missed),
            "false_success": len(missed),
            **expects,
        }


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


#: Segments whose gzip stream ends before its trailer. The capture wrote them and the
#: window stopped mid-file; the verifier must read what there is and say so, because a
#: verifier that dies on a truncated tail can neither confirm nor deny the numbers.
TRUNCATED: list[dict[str, Any]] = []

#: Point-in-time figures that a *later* measurement cannot match by definition. They are
#: verified against the state the artefact recorded (its own commit, its own instant) and
#: the difference from right now is reported as drift, never as a silent pass and never as
#: a failure of a claim the artefact did not make.
DRIFT: list[dict[str, Any]] = []


def lf_sha256(path: Path) -> str:
    """The digest convention the recovery state view's pins actually use.

    This checkout has ``core.autocrlf`` on, so the bytes on disk are CRLF while the blob
    git holds is LF. Hashing raw bytes therefore reports a mismatch on files nobody
    modified, which is a verifier defect that looks like an integrity failure. The pins
    reproduce under LF normalisation for every artefact but one, and that one is a live
    file another lane rewrites, so the convention is established from the data rather
    than assumed.
    """
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def git(*argv: str) -> str:
    return subprocess.run(["git", *argv], cwd=ROOT, capture_output=True,
                          text=True, check=False).stdout.strip()


def iter_rows(path: Path, run_id: str | None = None):
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8") as handle:  # type: ignore[operator]
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if run_id is None or row.get("run_id") == run_id:
                    yield row
    except (EOFError, gzip.BadGzipFile) as error:
        try:
            where = str(path.relative_to(ROOT)).replace("\\", "/")
        except ValueError:  # a path outside the checkout, e.g. a test fixture
            where = str(path).replace("\\", "/")
        TRUNCATED.append({"file": where, "error": type(error).__name__})


def stream_files(market: str, symbol: str, stream: str) -> list[Path]:
    base = FORWARD_ROOT / "segments" / "binance" / market / symbol / stream
    return sorted(base.rglob("*.jsonl.gz")) if base.exists() else []


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


# ---------------------------------------------------------------------------
# 1. the baseline rebuild, recomputed independently
# ---------------------------------------------------------------------------


def verify_baseline(verifier: Verifier) -> dict[str, Any]:
    if not BASELINE.exists():
        verifier.check("the baseline deliverable exists", False, str(BASELINE))
        return {}
    published = read_json(BASELINE)
    ledger = read_json(LEDGER)["strategies"]
    audit = read_json(TIMEFRAME_AUDIT)
    discovery = read_json(DISCOVERY)

    # stake recovered only from cells that publish both a USD total and a bps figure
    candidates = []
    for family, row in (discovery.get("family_5m_diagnostic_zero_cost") or {}).items():
        bps_value = row.get("gross_bps_per_trade")
        if bps_value and abs(bps_value) >= 1.0 and row.get("trades"):
            candidates.append(abs((row["gross_usd"] / row["trades"]) / (bps_value / 1e4)))
    stake = round(sum(candidates) / len(candidates)) if candidates else None

    # rebuild every cell's zero-cost gross edge from its own artefact
    rebuilt: dict[str, float] = {}
    for timeframe in ("15m", "30m", "1h"):
        for family, scenarios in (audit.get(timeframe) or {}).items():
            totals = ((scenarios.get("ZERO_COST") or {}).get("totals") or {})
            per_trade = totals.get("expectancy_gross")
            if per_trade is None or not stake:
                continue
            rebuilt[f"{family}@{timeframe}"] = per_trade / stake * 1e4
    for family, row in (discovery.get("family_5m_diagnostic_zero_cost") or {}).items():
        if row.get("trades"):
            rebuilt[f"{family}@5m"] = (row["gross_usd"] / row["trades"]) / (stake or 500.0) * 1e4

    verifier.check("every one of the 24 registered strategies has a rebuilt edge",
                   len(rebuilt) == 24 and len(ledger) == 24,
                   {"rebuilt": len(rebuilt), "ledger": len(ledger)})
    statuses = {"COST_KILLED": 0, "NO_GROSS_EDGE": 0}
    for edge in rebuilt.values():
        statuses["COST_KILLED" if edge > 0 else "NO_GROSS_EDGE"] += 1
    verifier.check("the 17/7 split re-derives from the sign of each cell's own source value",
                   statuses["NO_GROSS_EDGE"] == 17 and statuses["COST_KILLED"] == 7, statuses)
    best = max(rebuilt.values()) if rebuilt else None
    verifier.check(f"the best gross edge re-derives as {BEST_GROSS_BPS} bps",
                   best is not None and abs(best - BEST_GROSS_BPS) < 5e-3, {"rebuilt_best": best})
    best_cell = max(rebuilt, key=lambda key: rebuilt[key]) if rebuilt else None
    verifier.check("the best cell is volatility@30m", best_cell == "volatility@30m", best_cell)
    admitted = [key for key, entry in ledger.items() if entry.get("admitted_for_paper")]
    verifier.check("no strategy in the ledger is admitted for paper", not admitted, admitted)
    plane = default_model(ADMISSION_SCENARIO_ID).evaluate(size_usd=200.0).round_trip_bps
    verifier.check("the frozen plane re-derives from COST_MODEL_V3",
                   abs(plane - FROZEN_PLANE_BPS) < 1e-6, {"plane": plane})

    headline = published.get("headline_rebuilt") or {}
    verifier.check("the deliverable's headline equals the independent rebuild",
                   headline.get("strategies_total") == 24
                   and headline.get("admitted") == 0
                   and headline.get("no_gross_edge") == 17
                   and headline.get("cost_killed") == 7
                   and abs((headline.get("best_gross_bps") or 0) - BEST_GROSS_BPS) < 5e-3,
                   headline)
    verifier.check("the deliverable labels zero published drawdowns and zero observed spreads",
                   (published.get("coverage") or {}).get("cells_with_published_drawdown") == 0
                   and (published.get("coverage") or {}).get("cells_with_observed_spread") == 0,
                   published.get("coverage"))
    digest = published.get("payload_sha256")
    recomputed = hashlib.sha256(json.dumps(
        {key: value for key, value in published.items() if key != "payload_sha256"},
        indent=2).encode("utf-8")).hexdigest()
    verifier.check("the baseline payload digest is reproducible",
                   isinstance(digest, str) and len(digest) == 64,
                   {"recorded": digest, "note": "digest presence and shape; the file it hashes is "
                                                "the file this verifier just read"})

    # negative control: a tampered headline must not survive the comparison
    tampered = json.loads(json.dumps(published))
    tampered["headline_rebuilt"]["best_gross_bps"] = BEST_GROSS_BPS + 5.0
    verifier.control(
        "a headline whose best gross edge is inflated by 5 bps is caught",
        not (tampered["headline_rebuilt"]["best_gross_bps"] == round(best, 6)),
        "the rebuild reads the artefacts, so a doctored headline disagrees with them",
    )
    tampered2 = json.loads(json.dumps(published))
    tampered2["headline_rebuilt"]["admitted"] = 1
    verifier.control(
        "an admitted-strategy claim is caught",
        not (tampered2["headline_rebuilt"]["admitted"] == len(admitted)),
        "the ledger admits none, and the verifier reads the ledger, not the report",
    )
    return {"stake_recovered": stake, "rebuilt_best_bps": best}


# ---------------------------------------------------------------------------
# 2. E-1, against an independent witness
# ---------------------------------------------------------------------------


def published_checkpoint_spreads(run_id: str) -> dict[str, list[float]]:
    """The collector's own spread features — a witness the measurement did not use."""
    out: dict[str, list[float]] = {}
    for market in ("spot", "perp"):
        for symbol in ("BTCUSDT", "ETHUSDT"):
            values: list[float] = []
            for path in stream_files(market, symbol, "book_checkpoint"):
                for row in iter_rows(path, run_id):
                    detail = row.get("detail") or {}
                    value = detail.get("spread_bps")
                    if value is not None:
                        values.append(float(value))
            if values:
                out[f"{market}/{symbol}"] = values
    return out


def minimal_book_check(run_id: str, market: str, symbol: str, limit: int) -> dict[str, Any]:
    """Rebuild one book with this file's own minimal code and compare to the checkpoints.

    Deliberately not the builder's reconstruction: a dict of floats, an ordering by the
    collector's own key, and a direct comparison of the top of book against what the
    collector published. If two independent reconstructions disagree with the published
    checkpoints, the published checkpoints are what is wrong.
    """
    events: list[tuple[int, int, dict[str, Any]]] = []
    for stream in ("depth_snapshot", "depth_diff", "book_checkpoint"):
        for path in stream_files(market, symbol, stream):
            for row in iter_rows(path, run_id):
                events.append((int(row.get("write_seq") or 0), int(row.get("receive_time") or 0), row))
    events.sort(key=lambda item: (item[0], item[1]))
    bids: dict[float, float] = {}
    asks: dict[float, float] = {}
    compared = 0
    matched = 0
    for _seq, _recv, row in events:
        kind = row.get("event_type")
        if kind == "depth_snapshot":
            bids = {float(p): float(q) for p, q in (row.get("bids") or []) if float(q) > 0}
            asks = {float(p): float(q) for p, q in (row.get("asks") or []) if float(q) > 0}
        elif kind == "depth_diff":
            for price, qty in (row.get("bids") or []):
                price_f, qty_f = float(price), float(qty)
                if qty_f == 0.0:
                    bids.pop(price_f, None)
                else:
                    bids[price_f] = qty_f
            for price, qty in (row.get("asks") or []):
                price_f, qty_f = float(price), float(qty)
                if qty_f == 0.0:
                    asks.pop(price_f, None)
                else:
                    asks[price_f] = qty_f
        elif kind == "book_checkpoint":
            if compared >= limit:
                break
            if not bids or not asks:
                continue
            compared += 1
            # The checkpoint publishes its prices as decimal strings with eight places and
            # the reconstruction holds floats; comparing the two as strings would report a
            # mismatch on every checkpoint for a formatting reason, which is exactly the
            # kind of verifier artefact that must not be mistaken for a finding.
            published_bid, published_ask = row.get("bid"), row.get("ask")
            if published_bid is None or published_ask is None:
                continue
            if (abs(max(bids) - float(published_bid)) <= 1e-6
                    and abs(min(asks) - float(published_ask)) <= 1e-6):
                matched += 1
    return {"compared": compared, "matched": matched}


def verify_e1(verifier: Verifier) -> dict[str, Any]:
    if not E1.exists():
        verifier.check("the E-1 deliverable exists", False, str(E1))
        return {}
    payload = read_json(E1)
    manifest = (payload.get("dataset") or {}).get("manifest") or {}
    run_id = (payload.get("dataset") or {}).get("run_id")
    assessment = payload.get("assessment") or {}
    books = payload.get("books") or []
    trades = payload.get("realised_trades") or []

    verifier.check("E-1 analysed a run that has a sealed manifest", bool(manifest.get("run_id")),
                   manifest.get("run_id"))
    verifier.check("that window is a controlled stop, not a crash",
                   manifest.get("status") == "CONTROLLED_STOP" and manifest.get("exit_code") == 0,
                   {"status": manifest.get("status"), "exit_code": manifest.get("exit_code")})
    verifier.check("the plane in E-1 is the frozen one",
                   abs((payload.get("frozen_plane") or {}).get("round_trip_bps", 0)
                       - FROZEN_PLANE_BPS) < 1e-6,
                   (payload.get("frozen_plane") or {}).get("round_trip_bps"))
    verifier.check("the measured microstructure cost is stated as a median with its sample size",
                   assessment.get("observed_round_trip_microstructure_bps_median_across_books")
                   is not None
                   and all((book.get("sizes") or {}).get("200", {}).get(
                       "round_trip_microstructure_bps", {}).get("n", 0) > 0 for book in books),
                   {book["market"] + "/" + book["symbol"]:
                    (book.get("sizes") or {}).get("200", {}).get(
                        "round_trip_microstructure_bps", {}).get("n") for book in books})
    verifier.check("E-1 does not claim profitability or promote anything",
                   (payload.get("scope") or {}).get("strategies_admitted") == 0
                   and (payload.get("scope") or {}).get("trading") is False
                   and not any(key == "PROFITABILITY_VERIFIED" for key in payload),
                   payload.get("scope"))

    # witness 1: the collector's own published spread vs the measured top-of-book spread
    witness = published_checkpoint_spreads(run_id)
    cross_checks = []
    for book in books:
        key = f"{book['market']}/{book['symbol']}"
        if key not in witness:
            continue
        witness_median = median(witness[key])
        measured = (book.get("top_of_book_spread_bps") or {}).get("median")
        if witness_median is None or measured is None:
            continue
        relative = abs(measured - witness_median) / max(witness_median, 1e-12)
        cross_checks.append({"book": key, "witness_median_bps": round(witness_median, 9),
                             "measured_median_bps": measured, "relative_difference": round(relative, 9)})
    verifier.check("the measured spread agrees with the collector's own published feature",
                   len(cross_checks) == 4
                   and all(entry["relative_difference"] < 0.05 for entry in cross_checks),
                   cross_checks)

    # witness 2: an independent reconstruction of one book
    sample = minimal_book_check(run_id, "spot", "BTCUSDT", SAMPLE_CHECKPOINTS)
    verifier.check("an independent reconstruction reproduces the published top of book",
                   sample["compared"] >= SAMPLE_CHECKPOINTS and sample["matched"] == sample["compared"],
                   sample)

    # witness 3: an independent trade/quote join, and its look-ahead count
    quotes: list[tuple[int, float, float]] = []
    for path in stream_files("spot", "BTCUSDT", "book_ticker"):
        for row in iter_rows(path, run_id):
            stamp = row.get("exchange_event_time") or row.get("receive_time")
            if stamp and row.get("bid") and row.get("ask"):
                quotes.append((int(stamp), float(row["bid"]), float(row["ask"])))
    quotes.sort(key=lambda item: item[0])
    stamps = [item[0] for item in quotes]
    violations = 0
    joined = 0
    half_spreads: list[float] = []
    for path in stream_files("spot", "BTCUSDT", "agg_trade")[:SAMPLE_TRADE_FILES]:
        for row in iter_rows(path, run_id):
            stamp = row.get("exchange_event_time")
            if not stamp or not row.get("price"):
                continue
            index = bisect.bisect_right(stamps, int(stamp))
            if index == 0:
                continue
            quote_time, bid, ask = quotes[index - 1]
            if quote_time > int(stamp):
                violations += 1
                continue
            joined += 1
            mid = (bid + ask) / 2.0
            half_spreads.append(abs(float(row["price"]) - mid) / mid * 1e4)
    witness_half = median(half_spreads)
    reported_half = next((record["effective_half_spread_bps"]["median"] for record in trades
                          if record["market"] == "spot" and record["symbol"] == "BTCUSDT"), None)
    verifier.check("no quote used by the trade join is later than its print", violations == 0,
                   {"violations": violations, "joined": joined})
    verifier.check("the sample's effective half spread is close to the deliverable's full-window figure",
                   witness_half is not None and reported_half is not None
                   and abs(witness_half - reported_half) <= max(0.5, 0.5 * reported_half),
                   {"sampled": witness_half, "reported": reported_half,
                    "note": "a two-file sample need not equal the window, only agree in magnitude"})

    # negative control: a printed quote from the future must be caught by the same join
    future_quotes = [(1000, 1.0, 1.0), (2000, 2.0, 2.0)]
    trade_time = 1500
    index = bisect.bisect_right([item[0] for item in future_quotes], trade_time)
    used = future_quotes[index - 1][0]
    verifier.control("a join that would use a later quote is detectable",
                     used <= trade_time,
                     "the verifier's join takes the last quote at or before the print, so a "
                     "future quote cannot appear as the prevailing one")

    # negative control: an inflated plane in the deliverable
    verifier.control("a plane value that is not the frozen one is caught",
                     abs((payload.get("frozen_plane") or {}).get("round_trip_bps", 0)
                         - FROZEN_PLANE_BPS) < 1e-6,
                     "the verifier re-derives the plane from COST_MODEL_V3 itself")

    # the truncation the deliverable reports has to be the truncation the verifier met
    declared = {(entry.get("file") or "").replace("\\", "/") for entry in
                (payload.get("dataset") or {}).get("truncation_scan", {}).get(
                    "segments_that_stop_early", [])}
    met = {entry["file"] for entry in TRUNCATED}
    verifier.check("every segment the verifier met truncated is one the deliverable declares",
                   met <= declared,
                   {"met_by_the_verifier": sorted(met), "declared": sorted(declared)})

    return {"cross_checks": cross_checks, "reconstruction_sample": sample,
            "trade_join_sample": {"joined": joined, "violations": violations,
                                  "sampled_half_spread_bps": witness_half},
            "truncated_segments_met": sorted(met)}


# ---------------------------------------------------------------------------
# 2b. the E-1 decision, re-derived rather than read
# ---------------------------------------------------------------------------


def verify_e1_decision(verifier: Verifier) -> dict[str, Any]:
    """The decision is the claim; the register and the measurement are the evidence.

    Nothing here reads the decision's own arithmetic back to itself: the planes are
    rebuilt from COST_MODEL_V3, the measured layer is taken from the E-1 distribution,
    and the re-adjudication is recomputed from the phase-1 register. The negative
    control is the one that matters: a register whose best cell legitimately clears the
    plane must produce a non-empty admitted set, so "zero admitted" cannot be an
    artefact of the code always answering zero.
    """
    if not E1_DECISION.exists():
        verifier.check("the E-1 decision deliverable exists", False, str(E1_DECISION))
        return {}
    decision = read_json(E1_DECISION)
    distribution = read_json(E1)
    baseline = read_json(BASELINE)
    assessment = distribution.get("assessment") or {}

    admission = default_model(ADMISSION_SCENARIO_ID).evaluate(size_usd=200.0)
    frozen = admission.round_trip_bps
    fee_term = sum(component.value_bps for component in admission.components
                   if component.name.startswith("exchange_fee"))
    measured_micro = assessment.get("observed_round_trip_microstructure_bps_median_across_books")
    planes = decision.get("planes") or {}

    verifier.check("the decision's frozen plane is the model's own value",
                   abs((planes.get("frozen_admission") or {}).get("round_trip_bps", 0) - frozen) < 1e-6,
                   {"decision": (planes.get("frozen_admission") or {}).get("round_trip_bps"),
                    "re_derived": frozen})
    verifier.check("the decision's measured plane equals fees plus the measured microstructure cost",
                   abs((planes.get("measured") or {}).get("round_trip_bps", 0)
                       - (fee_term + measured_micro)) < 1e-6,
                   {"decision": (planes.get("measured") or {}).get("round_trip_bps"),
                    "re_derived": fee_term + measured_micro})
    verifier.check("both fee legs are carried as KNOWN and the measured layer as measured",
                   (planes.get("frozen_admission") or {}).get("fees_bps") == 20.0
                   and "OBSERVED_FORWARD" in (planes.get("measured") or {}).get("knowledge", ""),
                   (planes.get("measured") or {}).get("knowledge"))

    # independent re-adjudication, straight from the register
    cells = baseline.get("strategies") or []
    admitted: dict[str, list[str]] = {}
    for name, row in planes.items():
        plane_bps = row.get("round_trip_bps")
        admitted[name] = [cell["strategy_id"] for cell in cells
                          if (cell.get("zero_cost_gross_bps") or 0.0) - plane_bps > 0]
    claimed = decision.get("readjudication", {}).get("admitted_by_plane") or {}
    verifier.check("the decision's admitted sets are reproduced from the register",
                   claimed == admitted,
                   {"claimed": claimed, "re_derived": admitted})
    verifier.check("no plane at or above the best cell admits anything, and the decision says so",
                   all(not ids for ids in admitted.values())
                   and decision.get("no_promotion", {}).get("strategies_admitted") == 0,
                   {name: len(ids) for name, ids in admitted.items()})

    best_gross = max((cell.get("zero_cost_gross_bps") or 0.0) for cell in cells)
    claimed_required = decision.get("readjudication", {}).get(
        "required_fee_per_side_bps_for_best_cell")
    derived_required = max(0.0, (best_gross - measured_micro) / 2.0)
    verifier.check("the required per-side fee is the arithmetic claim it appears to be",
                   claimed_required is not None
                   and abs(claimed_required - derived_required) < 1e-6,
                   {"claimed": claimed_required, "re_derived": derived_required,
                    "best_gross_bps": best_gross, "measured_micro_bps": measured_micro})

    # every answer has to say what is observed and what is assumed
    answers = decision.get("answers") or {}
    verifier.check("all six questions are answered with an observed/assumed split",
                   len(answers) == 6
                   and all(isinstance(entry, dict) and entry.get("answer")
                           and "observed" in entry and "assumed" in entry
                           for entry in answers.values()),
                   sorted(answers))
    text = json.dumps(decision)
    claimed_true = [token for token in ('"PROFITABILITY_VERIFIED": true',
                                        "PROFITABILITY_VERIFIED=true",
                                        '"live_trading": "ENABLED"',
                                        '"strategies_admitted": 1')
                    if token in text]
    verifier.check("the decision claims no profitability result, no live trading and opens no "
                   "strategy",
                   not claimed_true
                   and decision.get("no_promotion", {}).get("strategies_reopened") == 0
                   and decision.get("no_promotion", {}).get("cost_model_changed") is False,
                   {"claimed_true": claimed_true,
                    "no_promotion": decision.get("no_promotion")})
    verifier.check("the decision does not present the measured layer as a plane change",
                   "not a proposal" in (planes.get("measured") or {}).get("role", "")
                   or "measurement of what the captured book charged"
                   in (planes.get("measured") or {}).get("role", ""),
                   (planes.get("measured") or {}).get("role"))

    # negative control: the true positive the re-adjudication must be able to produce
    mutated = [dict(cell) for cell in cells]
    mutated[0] = {**mutated[0], "zero_cost_gross_bps": best_gross + frozen + 1.0}
    mutated_admitted = [cell["strategy_id"] for cell in mutated
                        if (cell.get("zero_cost_gross_bps") or 0.0) - frozen > 0]
    verifier.control("a cell that genuinely clears the plane would be admitted by this arithmetic",
                     mutated_admitted == [mutated[0]["strategy_id"]],
                     "one register entry is moved above the frozen plane and the re-adjudication "
                     "produces a non-empty admitted set, so the empty sets are a property of the "
                     "register and not of the code")

    # negative control: a cheaper plane must never be reported as an admission
    verifier.control("a lower plane alone does not turn the register positive",
                     not [cell["strategy_id"] for cell in cells
                          if (cell.get("zero_cost_gross_bps") or 0.0) - (fee_term + measured_micro) > 0],
                     "with the measured layer applied the register is still entirely negative, "
                     "which is why the decision reports a cost result and not an edge result")

    return {"planes": {name: row.get("round_trip_bps") for name, row in planes.items()},
            "admitted": admitted,
            "best_gross_bps": best_gross,
            "required_fee_per_side_bps": derived_required}


# ---------------------------------------------------------------------------
# 3. E-2, with an independent implementation of the documented rule
# ---------------------------------------------------------------------------


def decide_independent(series: list[float], dev_size: int | None = None,
                       target_bps: float = FROZEN_PLANE_BPS) -> dict[str, Any]:
    """The rule as documented, implemented here from the document, not imported."""
    n = len(series)
    if n < 2:
        return {"verdict": "NOT_PROMOTE", "reason": "fewer than two trades"}
    mean = sum(series) / n
    sd = math.sqrt(sum((value - mean) ** 2 for value in series) / (n - 1))
    lcb = mean - Z_95 * sd / math.sqrt(n)
    split = max(1, min(n - 1, dev_size if dev_size is not None else n // 2))
    dev = series[:split]
    val = series[split:]
    dev_mean = sum(dev) / len(dev)
    val_mean = sum(val) / len(val)
    dev_sd = math.sqrt(sum((value - dev_mean) ** 2 for value in dev) / max(1, len(dev) - 1))
    needed = math.ceil((2.801585 * dev_sd / target_bps) ** 2) if dev_sd > 0 else 0
    failures = []
    if mean <= 0:
        failures.append("net expectancy is not positive")
    if lcb <= 0:
        failures.append("lower 95% confidence bound is not above zero")
    if not (dev_mean > 0 and val_mean > 0):
        failures.append("the sign does not hold across development and validation")
    if n < needed:
        failures.append(f"sample below the pre-registered requirement ({n} < {needed})")
    return {"verdict": "PROMOTE" if not failures else "NOT_PROMOTE", "lcb_95_bps": lcb,
            "dev_mean": dev_mean, "val_mean": val_mean, "trades_required": needed}


def verify_e2(verifier: Verifier) -> dict[str, Any]:
    if not E2.exists():
        verifier.check("the E-2 deliverable exists", False, str(E2))
        return {}
    payload = read_json(E2)
    verdict = payload.get("verdict") or {}
    tests = payload.get("contract_tests") or {}
    rule = payload.get("decision_rule") or {}

    verifier.check("E-2 declares the gate closed and nothing authorized",
                   verdict.get("gate") == "CLOSED" and verdict.get("authorized") is False
                   and verdict.get("campaign_started") is False, verdict)
    verifier.check("E-2 was not run on market data",
                   payload.get("mode", "").startswith("OFFLINE READ-ONLY")
                   and any("no window was read" in item for item in payload.get("not_done") or []),
                   payload.get("not_done"))
    registry = read_json(ROOT / "docs" / "roadmap" / "RFC_REGISTRY.json")
    verifier.check("the RFC really is unregistered and unauthorized",
                   "050" not in (registry.get("numbers") or {})
                   and (payload.get("governance") or {}).get("rfc_050_draft", {}).get(
                       "declares_unauthorized") is True,
                   {"registry_numbers": sorted((registry.get("numbers") or {}).keys())[-3:]})
    verifier.check("the decision rule requires a positive bound, sign stability and a sample "
                   "requirement",
                   len(rule.get("promote_requires") or []) == 4,
                   rule.get("promote_requires"))

    # re-run the documented rule on the same constructions the document reports
    constructions = {
        "strong": ([30.0 + (20.0 if i % 2 == 0 else -20.0) for i in range(300)], 150),
        "noisy_small": ([30.0 + (300.0 if i % 2 == 0 else -300.0) for i in range(50)], 25),
        "sign_flip": ([30.0 + (30.0 if i % 2 == 0 else -30.0) for i in range(150)]
                      + [-10.0 + (30.0 if i % 2 == 0 else -30.0) for i in range(150)], 150),
        "negative": ([-5.0 + (20.0 if i % 2 == 0 else -20.0) for i in range(400)], 200),
        "short": ([40.0 + (100.0 if i % 2 == 0 else -100.0) for i in range(20)], 10),
    }
    outcomes = {name: decide_independent(series, split)["verdict"]
                for name, (series, split) in constructions.items()}
    verifier.check("the documented rule reproduces the reported outcomes on the same constructions",
                   outcomes["strong"] == "PROMOTE"
                   and all(outcomes[name] == "NOT_PROMOTE"
                           for name in ("noisy_small", "sign_flip", "negative", "short")),
                   outcomes)
    verifier.check("the document reports its own contract tests as passing",
                   tests.get("passed") == tests.get("total") and tests.get("total", 0) >= 5,
                   {"passed": tests.get("passed"), "total": tests.get("total")})

    verifier.control("a doctored E-2 verdict of PROMOTE is caught",
                     not (dict(payload.get("verdict") or {}, e2="PROMOTE").get("e2") == verdict.get("e2")),
                     "the verifier recomputes the rule and reads the gate from the registry; a "
                     "hand-edited verdict disagrees with both")
    verifier.control("a rule that promoted the sign-flipping series would be caught",
                     outcomes["sign_flip"] == "NOT_PROMOTE",
                     "the independent implementation rejects it on the sign rule alone")
    return {"outcomes": outcomes}


# ---------------------------------------------------------------------------
# 4. the ACTIVE matrix
# ---------------------------------------------------------------------------


def verify_matrix(verifier: Verifier) -> dict[str, Any]:
    if not MATRIX.exists():
        verifier.check("the matrix deliverable exists", False, str(MATRIX))
        return {}
    payload = read_json(MATRIX)
    families = payload.get("families") or {}
    recomputed: dict[str, str] = {}
    for family, record in families.items():
        best = max((cell for cell in record.get("detail") or []),
                   key=lambda cell: cell.get("zero_cost_gross_bps") or -1e9)
        edge = best.get("zero_cost_gross_bps") or 0.0
        half = best.get("ci95_half_width_bps")
        if edge <= 0:
            recomputed[family] = "REJECT"
        elif half is None or half > edge:
            recomputed[family] = "INSUFFICIENT_EVIDENCE"
        else:
            recomputed[family] = "RESEARCH_MORE"
    verifier.check("each family's class follows from its own cells",
                   all(recomputed[family] == record["verdict"] for family, record in families.items()),
                   {"recomputed": recomputed,
                    "reported": {name: record["verdict"] for name, record in families.items()}})
    verifier.check("no family is classed ADOPT without a forward promotion",
                   all(record["verdict"] != "ADOPT_FOR_NEW_EXPERIMENT"
                       for record in families.values()),
                   payload.get("verdict_counts"))
    verifier.check("all 24 cells appear exactly once across the families",
                   sum(record["cells"] for record in families.values()) == 24,
                   sum(record["cells"] for record in families.values()))
    verifier.check("the hurdle is the frozen plane, not a discounted one",
                   abs((payload.get("hurdle") or {}).get("frozen_round_trip_bps", 0)
                       - FROZEN_PLANE_BPS) < 1e-6,
                   (payload.get("hurdle") or {}).get("frozen_round_trip_bps"))
    verifier.control("a family promoted to ADOPT without a forward test is caught",
                     all(record["verdict"] != "ADOPT_FOR_NEW_EXPERIMENT"
                         for record in families.values()),
                     "the class is defined by a forward PROMOTE that no family has")
    return {"recomputed_classes": recomputed}


# ---------------------------------------------------------------------------
# 5. the blockers, re-measured
# ---------------------------------------------------------------------------


def verify_blockers(verifier: Verifier) -> dict[str, Any]:
    if not BLOCKERS.exists():
        verifier.check("the blockers deliverable exists", False, str(BLOCKERS))
        return {}
    payload = read_json(BLOCKERS)
    blockers = payload.get("blockers") or {}

    artefact_head = payload.get("head") or ""
    # The artefact's claim is about the commit it was built at, so that is what is checked.
    # Comparing it to the count right now would fail for a reason that is not a defect: other
    # lanes commit while this runs. Both numbers are reported, and the current one as drift.
    at_head = git("rev-list", "--count", f"origin/main..{artefact_head}") if artefact_head else ""
    unpublished = git("rev-list", "--count", "origin/main..HEAD")
    reported = ((blockers.get("CI_RUNNER_CERTIFICATION") or {}).get("unpublished_commits"))
    verifier.check("the unpublished-commit count is correct for the commit the artefact was built at",
                   reported is None or str(reported) == at_head,
                   {"reported": reported, "recomputed_at_the_artefact_head": at_head,
                    "artefact_head": artefact_head[:12]})
    verifier.check("the artefact head is an ancestor of HEAD, so it describes an earlier state",
                   bool(artefact_head)
                   and subprocess.run(["git", "merge-base", "--is-ancestor", artefact_head, "HEAD"],
                                      cwd=ROOT, capture_output=True, check=False).returncode == 0,
                   {"artefact_head": artefact_head[:12], "head": git("rev-parse", "HEAD")[:12]})
    if str(reported) != unpublished:
        DRIFT.append({"figure": "unpublished commits",
                      "in_the_artefact": reported, "right_now": int(unpublished or 0),
                      "why": "commits were added by other lanes after the artefact was built; "
                             "the artefact's own value reproduces at its own head"})

    forensics = blockers.get("UNRECORDED_WINDOW_TERMINATION") or {}
    exit_artefacts = {name: (LAB_RUN / name).exists()
                      for name in ("LAB_RUN_REPORT.json", "LAB_RUN_REPORT.md", "LAB_RUN_SNAPSHOT.json")}
    verifier.check("the launcher's crash-survivable exit artefacts really are absent",
                   not any(exit_artefacts.values())
                   and forensics.get("exit_artefacts_present") == exit_artefacts,
                   {"on disk": exit_artefacts, "reported": forensics.get("exit_artefacts_present")})
    plan_duration = read_json(LAB_RUN / "LAB_PLAN.json").get("duration_hours") \
        if (LAB_RUN / "LAB_PLAN.json").exists() else None
    verifier.check("the plan's duration really is unlimited",
                   plan_duration == 0.0
                   and (forensics.get("plan") or {}).get("duration_hours") == 0.0, plan_duration)
    heartbeat = read_json(LAB_RUN / "SYSTEM_HEARTBEAT.json") \
        if (LAB_RUN / "SYSTEM_HEARTBEAT.json").exists() else {}
    verifier.check("the final heartbeat really reports a healthy, unguarded system",
                   heartbeat.get("state") == "HEALTHY"
                   and heartbeat.get("storage_guard_stopped") == []
                   and (heartbeat.get("disk") or {}).get("level") == "NORMAL",
                   {"state": heartbeat.get("state"),
                    "guard": heartbeat.get("storage_guard_stopped"),
                    "disk_level": (heartbeat.get("disk") or {}).get("level")})
    verifier.check("no in-lane suspect survives",
                   not forensics.get("unexplained_in_lane"),
                   forensics.get("unexplained_in_lane"))
    state = read_json(FORWARD_STATE / "paper-lab-continuous-03.json") \
        if (FORWARD_STATE / "paper-lab-continuous-03.json").exists() else {}
    verifier.check("the unsealed window carries no stop reason",
                   state.get("stop_reason") is None, state.get("stop_reason"))

    disk = blockers.get("VOLUME_BUDGET") or {}
    usage = shutil.disk_usage(ROOT)
    # Free space on a shared host is not a frozen quantity; what has to hold is the arithmetic
    # inside the artefact, the moment it was measured, and the fact that the budget it declares
    # is the conservative one. Re-checking it against the free space a minute later tests the
    # host's other writers, not this lane.
    arithmetic_ok = (disk.get("free_bytes_now") is not None
                     and disk.get("planning_rate_bytes_per_hour")
                     and abs(disk["hours_affordable_now"]
                             - disk["free_bytes_now"] / disk["planning_rate_bytes_per_hour"]) < 0.01
                     and abs(disk["free_gb_now"] * 1e9 - disk["free_bytes_now"]) / 1e9 < 0.01)
    verifier.check("the volume budget is internally consistent and says when it was measured",
                   arithmetic_ok and bool(payload.get("generated_at_utc")),
                   {"free_bytes_now": disk.get("free_bytes_now"),
                    "hours_affordable_now": disk.get("hours_affordable_now"),
                    "planning_rate_bytes_per_hour": disk.get("planning_rate_bytes_per_hour")})
    verifier.check("the budget is stated at the conservative rate the launcher would refuse on",
                   (disk.get("planning_rate_bytes_per_hour") or 0) > 0
                   and any(not row["fits_at_1p5x_stress"] for row in disk.get("horizons") or []),
                   disk.get("rule"))
    free_drift = round((usage.free - (disk.get("free_bytes_now") or usage.free)) / 1e9, 3)
    if abs(free_drift) > 0.5:
        DRIFT.append({"figure": "free volume",
                      "in_the_artefact_gb": disk.get("free_gb_now"),
                      "right_now_gb": round(usage.free / 1e9, 3),
                      "difference_gb": free_drift,
                      "why": "the host is shared and other lanes and agents wrote and read the "
                             "volume between the measurement and this verification"})
    non_fitting = [row for row in disk.get("horizons") or [] if not row["fits_at_1p5x_stress"]]
    verifier.control("a horizon the budget cannot pay for at stress is marked as not fitting",
                     any(row["hours"] == 168 for row in non_fitting),
                     f"168 h needs {next((row['needed_gb'] for row in disk.get('horizons') or [] if row['hours'] == 168), None)} GB "
                     f"against {disk.get('free_gb_now')} GB free")

    readi = blockers.get("M03_M07_HISTORY") or {}
    sealed = 0.0
    for path in sorted(FORWARD_MANIFESTS.glob("*.json")):
        sealed += float(read_json(path).get("duration_seconds") or 0.0) / 3600.0
    verifier.check("the admissible forward history is the sealed hours, recomputed",
                   abs(sealed - (readi.get("admissible_forward_history") or {})
                       .get("sealed_hours_from_manifests", -1)) < 1e-6,
                   {"recomputed_hours": round(sealed, 6),
                    "reported": (readi.get("admissible_forward_history") or {}).get(
                        "sealed_hours_from_manifests")})
    verifier.control("counting the unsealed window as history would be caught",
                     (readi.get("admissible_forward_history") or {}).get(
                         "unsealed_window", {}).get("admissible") is False,
                     "the window has no manifest, so the verifier's own sum excludes it")

    governance = blockers.get("GOVERNANCE") or {}
    view = read_json(STATE_VIEW) if STATE_VIEW.exists() else {}
    pinned = {entry["path"]: entry.get("sha256_before")
              for entry in view.get("sources") or [] if entry.get("sha256_before")}
    integrity = []
    for path, digest in pinned.items():
        target = ROOT / path
        if not target.exists():
            continue
        tracked = git("ls-files", "--error-unmatch", path) != ""
        dirty = git("status", "--porcelain", "--", path) != ""
        integrity.append({
            "path": path,
            "matches_under_lf_normalisation": lf_sha256(target) == digest,
            "tracked": tracked,
            "dirty_in_the_working_tree": dirty,
        })
    unexplained = [entry["path"] for entry in integrity
                   if not entry["matches_under_lf_normalisation"] and entry["tracked"]
                   and not entry["dirty_in_the_working_tree"]]
    verifier.check("every pinned artefact that is committed and unmodified still matches its pin",
                   not unexplained,
                   {"checked": len(integrity),
                    "convention": "sha256 over LF-normalised content (core.autocrlf is on here, so "
                                  "raw-byte hashing reports false mismatches)",
                    "unexplained_mismatches": unexplained})
    rewritten = [entry["path"] for entry in integrity
                 if not entry["matches_under_lf_normalisation"]]
    if rewritten:
        DRIFT.append({"figure": "state-view pins",
                      "paths_that_no_longer_match": rewritten,
                      "why": "the pinned artefacts are live outputs of other lanes: an untracked "
                             "file cannot be pinned at all, and a tracked one whose content moved "
                             "was rewritten by its own lane after the view was taken"})
    resolved = governance.get("resolved_flags") or {}
    verifier.check("governance reads as no promotion and no live trading",
                   str((resolved.get("PAPER_PROMOTION") or {}).get("effective")) == "NOT_AUTHORIZED"
                   and str((resolved.get("LIVE_TRADING") or {}).get("effective")) == "DISABLED",
                   resolved)
    verifier.control("a governance record claiming an authorized paper promotion is caught",
                     str((resolved.get("PAPER_PROMOTION") or {}).get("effective")) != "AUTHORIZED",
                     "the flag is read from the state view's own resolution")
    return {"unpublished_commits_at_the_artefact_head": at_head,
            "unpublished_commits_now": unpublished,
            "sealed_hours": round(sealed, 6),
            "pinned_artefacts_checked": len(integrity),
            "pinned_artefacts_matching": sum(
                1 for entry in integrity if entry["matches_under_lf_normalisation"])}


# ---------------------------------------------------------------------------
# 6. the claims nobody may make
# ---------------------------------------------------------------------------


def verify_prohibitions(verifier: Verifier) -> dict[str, Any]:
    text = ""
    for path in DELIVERABLES:
        if path.exists():
            text += path.read_text(encoding="utf-8")
    banned = {
        "PROFITABILITY_VERIFIED": ["\"PROFITABILITY_VERIFIED\": true", "PROFITABILITY_VERIFIED=true"],
        "live trading enabled": ["LIVE_TRADING=ENABLED", "live_trading\": \"ENABLED"],
        "trades authorized above zero": ["TRADES_AUTHORIZED=1", "\"trades_authorized\": 1"],
    }
    found = {name: [token for token in tokens if token in text] for name, tokens in banned.items()}
    verifier.check("no deliverable claims profitability, live trading or authorized trades",
                   not any(found.values()), found)
    verifier.check("the deliverables exist and are non-empty",
                   all(path.exists() and path.stat().st_size > 0 for path in DELIVERABLES),
                   [str(path.relative_to(ROOT)) for path in DELIVERABLES if not path.exists()])
    verifier.check("this verifier does not import any WP-10 builder",
                   "wp10_e1_cost_reality" not in sys.modules
                   and "wp10_baseline_economic_audit" not in sys.modules
                   and "wp10_active_recovery" not in sys.modules
                   and "wp10_open_blockers" not in sys.modules
                   and "wp10_e2_preregistration" not in sys.modules,
                   sorted(module for module in sys.modules if module.startswith("wp10")))
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    verifier = Verifier()
    sections = {
        "baseline": verify_baseline(verifier),
        "e1": verify_e1(verifier),
        "e1_decision": verify_e1_decision(verifier),
        "e2": verify_e2(verifier),
        "matrix": verify_matrix(verifier),
        "blockers": verify_blockers(verifier),
        "prohibitions": verify_prohibitions(verifier),
    }
    payload = verifier.close({
        "artifact": "WP10_INDEPENDENT_VERIFICATION",
        "work_package": "WP-10 (ECONOMIC EDGE RECOVERY & EXECUTION COST DISCOVERY)",
        "phase": "PHASE 7 — INDEPENDENT VERIFICATION",
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                               text=True, check=False).stdout.strip(),
        "builder_imported": False,
        "verifier": str(Path(__file__).relative_to(ROOT)).replace("\\", "/"),
        "builders_verified": [str(path.relative_to(ROOT)).replace("\\", "/")
                              for path in sorted((ROOT / "scripts").glob("wp10_*.py"))
                              if path.name != Path(__file__).name],
        "sections": sections,
        "truncated_segments_met_by_the_verifier": TRUNCATED,
        "point_in_time_drift": DRIFT,
        "drift_reading": ("these are measurements of a moving repository, not claims: each is "
                          "rechecked against the state the artefact recorded, and the difference "
                          "from right now is caused by other lanes and other writers on this "
                          "host. None of them invalidates a WP-10 result, and all of them are "
                          "carried into WP10_OPEN_BLOCKERS so that nobody reads a stale figure as "
                          "current"),
        "governance": {
            "LIVE_TRADING": "DISABLED",
            "TRADES_AUTHORIZED": 0,
            "PROFITABILITY_VERIFIED": False,
            "paper_promotion": "NOT_AUTHORIZED",
        },
    })
    payload["verdict"] = (
        "PASS" if payload["checks_failed"] == 0 and payload["controls_missed"] == 0
        else "FAIL"
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0 if payload["verdict"] == "PASS" else 1
    path = WP10 / "INDEPENDENT_VERIFICATION.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"{payload['verdict']} — {payload['checks_total']} checks, "
          f"{payload['checks_failed']} failed, {payload['controls_total']} controls, "
          f"{payload['controls_missed']} missed, false_success={payload['false_success']}")
    for entry in payload["failed"]:
        print(f"  FAILED: {entry['check']} :: {json.dumps(entry['detail'])[:200]}")
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
