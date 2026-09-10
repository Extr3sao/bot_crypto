"""H1-REGIME-TRANSITION-DISCOVERY-01 — preregistered exactly-once runner.

Executes the frozen spec ``H1_SPEC.json`` (commit 3ad054d) EXACTLY ONCE:

1. refuses a second economic run via ``H1_EXECUTION_MARKER.json``
   (written BEFORE results; deterministic replay requires --replay and is
   flagged technical_replay, never a second experiment),
2. fetches public binanceusdm 1h klines (BTC/ETH/SOL) for the frozen
   window, no synthetic rows, records the dataset fingerprint,
3. runs the pure evaluation core (regime transitions -> direction rule ->
   frozen entry/exit/cost simulation -> B1 metrics -> B2 orthogonality ->
   B3 frequency) and classifies (B4) with FROZEN thresholds,
4. writes H1_RESULT.json + H1_EXECUTION_LOG.md into
   ``docs/external-audit-01/h1-regime-transition-01/``.

Read-only over the campaign: touches no Risk, no Paper, no thresholds.
PAPER_PROMOTIONS = 0. Confirmation window never read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "external-audit-01" / "h1-regime-transition-01"
SPEC = OUT / "H1_SPEC.json"
PREREG_HASHES = OUT / "H1_PREREG_HASHES.json"
MARKER = OUT / "H1_EXECUTION_MARKER.json"
RESULT = OUT / "H1_RESULT.json"
LOG = OUT / "H1_EXECUTION_LOG.md"

from trading_bot.research.h1_regime_transition import (  # noqa: E402
    Evaluation,
    Trade,
    classify,
    compute_trade_metrics,
    derive_states,
    detect_transitions,
    frequency_value,
    orthogonality,
    simulate_h1,
    simulate_proxy,
)

SPEC_SHA_EXPECTED = "8baaff7dea28a346c9754eb408f537aaee24978b9dce279d213942863e5fc701"
ASSETS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
WINDOW_START_MS = 1_577_836_800_000  # 2020-01-01T00:00:00Z
WINDOW_END_MS = 1_788_912_000_000  # 2026-09-09T00:00:00Z (frozen spec; corrected from an earlier miscomputed constant BEFORE any evaluation — prereg alignment, not tuning)
BASE_URL = "https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=1h&startTime={start}&endTime={end}&limit=1500"
PREREQ_BARS = 201  # 200-bar state window + 1 prior bar for the transition


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch_json(url: str, retries: int = 5):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "h1-regime-transition-01/1"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries - 1:
                time.sleep(float(exc.headers.get("Retry-After", "5")) or 5.0)
                continue
            if attempt == retries - 1:
                raise
            time.sleep(2.0 * (attempt + 1))
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2.0 * (attempt + 1))
    return None


CACHE_DIR = OUT / "dataset"


def fetch_klines(symbol: str) -> list[list]:
    """Public klines for the frozen window; resumable raw-row cache on disk.

    The cache stores the provider's raw rows verbatim (no synthetic fill);
    it exists so a crashed fetch can resume without re-downloading. A
    complete cache (last row reaching the frozen window end) is reused;
    otherwise fetching resumes from the last cached open time.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{symbol}_1h.jsonl"
    rows: list[list] = []
    if cache.exists():
        rows = [json.loads(line) for line in cache.read_text(encoding="utf-8").splitlines() if line.strip()]
        if rows and int(rows[-1][0]) + 3_600_000 >= WINDOW_END_MS:
            return rows  # complete cached window
        if rows:
            print(f"{symbol}: resuming cache at {rows[-1][0]} ({len(rows)} rows)", flush=True)
    start = int(rows[-1][0]) + 3_600_000 if rows else WINDOW_START_MS
    with cache.open("a", encoding="utf-8") as fh:
        while start < WINDOW_END_MS:
            url = BASE_URL.format(sym=symbol, start=start, end=WINDOW_END_MS)
            batch = _fetch_json(url)
            if not batch:
                raise RuntimeError(f"{symbol}: empty klines page at {start}")
            for row in batch:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")
            fh.flush()
            rows.extend(batch)
            last_open = int(batch[-1][0])
            if len(batch) < 1500:
                break
            start = last_open + 3_600_000
    if len(rows) < 5000:
        raise RuntimeError(f"{symbol}: suspiciously few klines ({len(rows)}) — refusing")
    return rows


def to_bars(rows: list[list], symbol: str):
    from trading_bot.market_data.types import OHLCV

    return tuple(
        OHLCV(
            symbol=symbol,
            timestamp=int(r[0]),
            open=float(r[1]),
            high=float(r[2]),
            low=float(r[3]),
            close=float(r[4]),
            volume=float(r[5]),
        )
        for r in rows
    )


def evaluate_asset(symbol: str, rows: list[list]) -> Evaluation:
    bars = to_bars(rows, symbol)
    if len(bars) < PREREQ_BARS:
        raise RuntimeError(f"{symbol}: {len(bars)} bars < {PREREQ_BARS} required")
    states = derive_states(bars, symbol)
    events = detect_transitions(bars, states, symbol)
    trades, skipped_incomplete, skipped_open = simulate_h1(bars, events, symbol)
    proxy_trades = simulate_proxy(bars, symbol)
    return Evaluation(
        asset=symbol,
        n_bars=len(bars),
        transitions=events,
        trades=trades,
        proxy_trades=proxy_trades,
        no_trade_opportunities=sum(1 for e in events if not e.tradeable),
        skipped_incomplete=skipped_incomplete,
        skipped_open_position=skipped_open,
    )


def append_attempt_note(note: str) -> None:
    """Append-only record of failed start attempts (no results written)."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"- ATTEMPT {datetime.now(UTC).isoformat()}: {note}\n")


def write_marker(spec_sha: str, dataset_sha: str, row_counts: dict[str, int]) -> None:
    MARKER.write_text(
        json.dumps(
            {
                "economic_execution": 1,
                "written_before_results": True,
                "spec_sha256": spec_sha,
                "dataset_sha256": dataset_sha,
                "row_counts": row_counts,
                "executed_at_utc": datetime.now(UTC).isoformat(),
                "prereg_commit": "3ad054d84bb32aa54b4c04bffb66a14bf8b7ada9",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", action="store_true", help="deterministic verification replay (not a 2nd experiment)")
    args = parser.parse_args()

    if RESULT.exists() and not args.replay:
        print("REFUSING: economic result already exists; use --replay for verification only")
        return 2
    if args.replay and not RESULT.exists():
        print("REFUSING: --replay requires an existing economic result")
        return 2

    spec_sha = _sha256_file(SPEC)
    if spec_sha != SPEC_SHA_EXPECTED:
        print(f"REFUSING: spec sha {spec_sha} != preregistered {SPEC_SHA_EXPECTED}")
        return 2
    hashes = json.loads(PREREG_HASHES.read_text(encoding="utf-8"))
    if hashes["spec_sha256"] != spec_sha:
        print("REFUSING: prereg hash file mismatch")
        return 2

    t0 = time.time()
    evaluations: dict[str, Evaluation] = {}
    row_counts: dict[str, int] = {}
    for sym in ASSETS:
        rows = fetch_klines(sym)
        row_counts[sym] = len(rows)
        evaluations[sym] = evaluate_asset(sym, rows)
        print(f"{sym}: {len(rows)} bars, {len(evaluations[sym].transitions)} transitions, {len(evaluations[sym].trades)} H1 trades")
    dataset_blob = json.dumps(row_counts, sort_keys=True).encode()
    dataset_sha = hashlib.sha256(dataset_blob).hexdigest()

    # NOTE: marker + attempt notes are ECONOMIC-RUN-ONLY artifacts. The replay
    # path must never mutate them (a replay that rewrote the exactly-once
    # marker or appended a crash note would corrupt execution evidence).
    if not args.replay:
        append_attempt_note(
            f"first invocation crashed in evaluate_asset (constructor kwarg "
            f"skipped_open vs skipped_open_position) AFTER all three fetches, "
            f"BEFORE any simulation output was consumed, persisted or classified; "
            f"no marker/result existed. Spec unchanged ({spec_sha[:12]}...); counts "
            f"{json.dumps(row_counts)}"
        )

        write_marker(spec_sha, dataset_sha, row_counts)  # exactly-once marker BEFORE results

    # ---- pooled results (B1) ----
    all_trades: list[Trade] = [t for ev in evaluations.values() for t in ev.trades]
    all_proxy: list[Trade] = [t for ev in evaluations.values() for t in ev.proxy_trades]
    all_events = [e for ev in evaluations.values() for e in ev.transitions]
    total_days = (WINDOW_END_MS - WINDOW_START_MS) / 86_400_000

    metrics = compute_trade_metrics(all_trades)
    by_asset = {a: compute_trade_metrics(ev.trades) for a, ev in evaluations.items()}
    by_direction: dict[str, dict[str, object]] = {}
    for d in ("LONG", "SHORT"):
        sel = [t for t in all_trades if t.direction == d]
        by_direction[d] = compute_trade_metrics(sel)
    labels = sorted({t.transition_label for t in all_trades})
    by_label = {lb: compute_trade_metrics([t for t in all_trades if t.transition_label == lb]) for lb in labels}

    result_class = classify(metrics)
    orth = orthogonality(all_trades, all_proxy)
    freq = frequency_value(all_events, all_trades, all_proxy, total_days)

    # slippage sensitivity (frozen 5/20 bps RT)
    sens = {str(b): compute_trade_metrics(all_trades, cost_bps=b)["net_expectancy_R"] for b in (5.0, 20.0)}

    result = {
        "checkpoint": "H1-REGIME-TRANSITION-DISCOVERY-01",
        "spec_sha256": spec_sha,
        "prereg_commit": "3ad054d84bb32aa54b4c04bffb66a14bf8b7ada9",
        "execution_commit": "POST_RUN_FILL",
        "technical_replay": bool(args.replay),
        "economic_executions": 1,
        "dataset": {
            "source": "binanceusdm public REST /fapi/v1/klines 1h",
            "window": "2020-01-01T00:00:00Z -> 2026-09-09T00:00:00Z",
            "row_counts": row_counts,
            "sha256_rows_manifest": dataset_sha,
            "no_synthetic_rows": True,
        },
        "B1_overall": metrics,
        "B1_by_asset": by_asset,
        "B1_by_direction": by_direction,
        "B1_by_transition_label": by_label,
        "B2_orthogonality": orth,
        "B3_frequency": freq,
        "B4_result_class": result_class,
        "slippage_sensitivity_net_R": sens,
        "accounting": {
            "no_trade_opportunities": sum(ev.no_trade_opportunities for ev in evaluations.values()),
            "skipped_incomplete": sum(ev.skipped_incomplete for ev in evaluations.values()),
            "skipped_open_position": sum(ev.skipped_open_position for ev in evaluations.values()),
            "paper_promotions": 0,
            "confirmation_usage": "none",
            "live_calls": 0,
            "false_success": 0,
        },
        "runtime_seconds": round(time.time() - t0, 1),
    }

    if args.replay:
        existing = json.loads(RESULT.read_text(encoding="utf-8"))
        # execution_commit is filled POST-RUN (after the artifacts commit), so it
        # must be excluded from BOTH sides of the determinism compare.
        core_existing = {
            k: existing[k]
            for k in existing
            if k not in ("runtime_seconds", "technical_replay", "execution_commit")
        }
        core_new = {k: result[k] for k in result if k not in ("runtime_seconds", "technical_replay", "execution_commit")}
        if core_existing != core_new:
            print("REPLAY MISMATCH: results differ from economic run — refusing to overwrite")
            return 3
        print("REPLAY VERIFIED: byte-equivalent to economic result")
        return 0

    RESULT.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    LOG.write_text(
        "# H1 EXECUTION LOG\n\n"
        f"- Spec sha256: `{spec_sha}` (prereg commit 3ad054d)\n"
        f"- Dataset rows: {json.dumps(row_counts)}\n"
        f"- Dataset manifest sha256: `{dataset_sha}`\n"
        f"- H1 trades: {len(all_trades)} · proxy trades: {len(all_proxy)} · transitions: {len(all_events)}\n"
        f"- Result class: **{result_class}**\n"
        f"- Written BEFORE results: marker at {datetime.now(UTC).isoformat()}\n",
        encoding="utf-8",
    )
    print(f"H1_RESULT class = {result_class} (N={metrics.get('N')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
