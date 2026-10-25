"""exp_003m_tape — download and reduce the observed trade tape for the frozen signals.

    ./.venv/Scripts/python.exe scripts/exp_003m_tape.py
    ./.venv/Scripts/python.exe scripts/exp_003m_tape.py --check

The tape is the only new evidence EXP-003M adds. It comes from `data.binance.vision`,
the exchange's own public archive, for exactly the (symbol, UTC day) pairs that contain a
pre-registered signal. Inside those days every trade in [decision - 60 s, decision + 16
min] is kept: no price filter, no side filter, no outcome filter. A signal whose fill
window is missing from the archive is an error, never a silently dropped signal.

Three products per (symbol, day):

* ``dataset/tape``   — the raw aggregate trades in the windows, byte-for-byte as published
                       (agg id, price, qty, microsecond stamp, buyer-is-maker flag).
* ``dataset/klines`` — the 1-minute bars of the same day from a *second* endpoint, used to
                       prove the frozen EXP-003K bars are the market's bars and not this
                       repository's opinion of them.
* ``dataset/depth``  — USD-M futures band depth in the same windows. Calibration only: it
                       is a different venue and cannot declare a spot fill.

Nothing here writes into another experiment, opens the holdout, or touches a credential.
Downloads are cached and their digests recorded, so a second run performs no network I/O
and produces byte-identical files.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

OUT = REPO / "reports" / "ai-bots" / "EXP-003M-MAKER-FILL-REALITY-001"
DATASET_SOURCE = REPO / "reports" / "ai-bots" / "EXP-003K-CANDIDATE-001" / "dataset"

SCHEMA = "AI_BOTS_003M_TAPE_MANIFEST_V1"
DAY_MS = 86_400_000
#: Computed, never typed: the guard has to be right on the day it fires.
HOLDOUT_START_MS = int(datetime(2026, 8, 6, tzinfo=UTC).timestamp() * 1000)
HOLDOUT_END_MS = int(datetime(2026, 8, 20, tzinfo=UTC).timestamp() * 1000)
USER_AGENT = "trading-agentic-portable/exp-003m (+research, no credentials)"


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=UTC).strftime("%Y-%m-%d")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _gzip_lines(path: Path, rows: list[list[Any]]) -> None:
    """Deterministic gzip: no filename, no mtime, sorted keys, one row per line."""

    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", compresslevel=9, mtime=0) as handle:
        for row in rows:
            handle.write((json.dumps(row, separators=(",", ":")) + "\n").encode("utf-8"))
    path.write_bytes(buffer.getvalue())


def load_plan(out: Path) -> tuple[dict[str, Any], dict[str, Any], dict[tuple[str, str], list[tuple[int, int]]]]:
    design = _read_json(out / "design" / "DESIGN.json")
    signals = _read_json(out / "analysis" / "SIGNALS.json")
    before = int(design["market_data_plan"]["window_before_ms"])
    after = int(design["market_data_plan"]["window_after_ms"])

    windows: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for signal in signals["signals"]:
        start = int(signal["decision_ts_ms"]) - before
        end = int(signal["decision_ts_ms"]) + after
        if HOLDOUT_START_MS <= start < HOLDOUT_END_MS or HOLDOUT_START_MS < end <= HOLDOUT_END_MS:
            raise SystemExit(
                f"[003m-tape] REFUSED — signal {signal['position_id']} falls in the holdout window"
            )
        for day_index in range((end // DAY_MS) - (start // DAY_MS) + 1):
            day_ms = (start // DAY_MS) * DAY_MS + day_index * DAY_MS
            if day_ms > end:
                break
            key = (str(signal["symbol"]).replace("/", ""), _day(day_ms))
            windows.setdefault(key, []).append((start, end))
    for key, spans in windows.items():
        windows[key] = sorted(set(spans))
        if HOLDOUT_START_MS <= spans[0][0] < HOLDOUT_END_MS:
            raise SystemExit(f"[003m-tape] REFUSED — {key} touches the holdout")
    return design, signals, windows


def _download(url: str, destination: Path) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            size = 0
            with destination.open("wb") as handle:
                while True:
                    block = response.read(1 << 20)
                    if not block:
                        break
                    digest.update(block)
                    handle.write(block)
                    size += len(block)
            headers = {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as error:
        raise SystemExit(f"[003m-tape] BLOCKED — {url} returned HTTP {error.code}") from error
    return {
        "url": url,
        "bytes": size,
        "sha256": digest.hexdigest(),
        "etag": headers.get("etag", ""),
        "last_modified": headers.get("last-modified", ""),
        "content_length_header": headers.get("content-length", ""),
    }


def _windows_for(spans: list[tuple[int, int]], ts_ms: int) -> bool:
    return any(start <= ts_ms <= end for start, end in spans)


def reduce_agg_trades(
    zipped: Path, spans: list[tuple[int, int]], destination: Path, day: str
) -> dict[str, Any]:
    """Stream the archive, keep only rows inside the windows, and validate the stream.

    Validation is over the *whole* day file, not just the kept rows: a tape whose ids go
    backwards anywhere is not a tape, and truncating the check to the kept rows would hide
    exactly the corruption this experiment has to rule out.
    """

    kept: list[list[Any]] = []
    rows_in_day = 0
    last_id: int | None = None
    last_ts = 0
    day_start_ms = int(
        datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=UTC).timestamp() * 1000
    )
    day_end_ms = day_start_ms + DAY_MS
    with zipfile.ZipFile(zipped) as archive:
        names = archive.namelist()
        if len(names) != 1:
            raise SystemExit(f"[003m-tape] FAIL — {zipped.name} holds {len(names)} members")
        with archive.open(names[0]) as raw:
            stream = io.TextIOWrapper(raw, encoding="utf-8", newline="")
            header = stream.readline()
            if header and not header[0].isdigit():
                header = ""
            for line in _with_first(stream, header):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) < 7:
                    raise SystemExit(f"[003m-tape] FAIL — malformed aggTrade row {line[:80]!r}")
                agg_id = int(parts[0])
                price = float(parts[1])
                qty = float(parts[2])
                ts_ms = int(parts[5]) // 1000
                is_buyer_maker = parts[6].strip().lower() == "true"
                rows_in_day += 1
                if price <= 0 or qty <= 0:
                    raise SystemExit(f"[003m-tape] FAIL — non-positive price/qty in {zipped.name}")
                if last_id is not None and agg_id <= last_id:
                    raise SystemExit(f"[003m-tape] FAIL — agg ids not increasing at {agg_id}")
                if ts_ms < last_ts:
                    raise SystemExit(f"[003m-tape] FAIL — timestamps go backwards at {agg_id}")
                if not (day_start_ms - DAY_MS < ts_ms < day_end_ms + DAY_MS):
                    raise SystemExit(f"[003m-tape] FAIL — {agg_id} outside its UTC day")
                last_id = agg_id
                last_ts = ts_ms
                if _windows_for(spans, ts_ms):
                    kept.append([agg_id, price, qty, ts_ms, is_buyer_maker])
    if rows_in_day == 0:
        raise SystemExit(f"[003m-tape] FAIL — {zipped.name} is empty")
    _gzip_lines(destination, kept)
    covered = {span: any(span[0] <= row[3] <= span[1] for row in kept) for span in spans}
    return {
        "rows_in_day": rows_in_day,
        "rows_kept": len(kept),
        "first_ts_ms": kept[0][3] if kept else None,
        "last_ts_ms": kept[-1][3] if kept else None,
        "windows_present": [
            {"start_utc": _utc(span[0]), "end_utc": _utc(span[1]), "has_trades": covered[span]}
            for span in spans
        ],
        "validation": {
            "agg_ids_monotonic": True,
            "timestamps_monotonic": True,
            "positive_prices_and_quantities": True,
            "inside_utc_day": True,
            "whole_day_streamed": True,
        },
    }


def _with_first(stream: io.TextIOWrapper, first: str) -> Any:
    if first:
        yield first
    yield from stream


def reduce_klines(zipped: Path, destination: Path) -> dict[str, Any]:
    rows: list[list[Any]] = []
    with zipfile.ZipFile(zipped) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as raw:
            for line in io.TextIOWrapper(raw, encoding="utf-8", newline=""):
                parts = line.strip().split(",")
                if len(parts) < 6 or not parts[0]:
                    continue
                try:
                    open_ms = int(parts[0])
                except ValueError:
                    continue  # header row
                # The archive publishes microseconds on this endpoint while the frozen
                # EXP-003K dataset (REST /api/v3/klines) is in milliseconds. Normalising
                # here is what makes the provenance check a comparison and not a test of
                # which unit happened to be written down.
                if open_ms > 10**14:
                    open_ms //= 1000
                rows.append(
                    [
                        open_ms,
                        float(parts[1]),
                        float(parts[2]),
                        float(parts[3]),
                        float(parts[4]),
                        float(parts[5]),
                    ]
                )
    if not rows:
        raise SystemExit(f"[003m-tape] FAIL — {zipped.name} has no klines")
    _gzip_lines(destination, rows)
    return {"rows": len(rows), "first_open_ms": rows[0][0], "last_open_ms": rows[-1][0]}


def reduce_depth(zipped: Path, spans: list[tuple[int, int]], destination: Path) -> dict[str, Any]:
    """Band depth at the tightest published percentage, inside the signal windows only."""

    rows: list[list[Any]] = []
    percentages: set[float] = set()
    with zipfile.ZipFile(zipped) as archive:
        name = archive.namelist()[0]
        with archive.open(name) as raw:
            for line in io.TextIOWrapper(raw, encoding="utf-8", newline=""):
                parts = line.strip().split(",")
                if len(parts) < 4 or not parts[0] or parts[0] == "timestamp":
                    continue
                stamp = datetime.strptime(parts[0], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                ts_ms = int(stamp.timestamp() * 1000)
                pct = float(parts[1])
                percentages.add(round(abs(pct), 4))
                if _windows_for(spans, ts_ms):
                    rows.append([ts_ms, pct, float(parts[2]), float(parts[3])])
    tightest = min(percentages) if percentages else None
    if tightest is not None:
        rows = [row for row in rows if round(abs(row[1]), 4) == tightest]
    _gzip_lines(destination, rows)
    return {"rows": len(rows), "tightest_band_pct": tightest, "bands_seen": sorted(percentages)[:8]}


def build_entry(
    *,
    symbol: str,
    day: str,
    spans: list[tuple[int, int]],
    design: dict[str, Any],
    out: Path,
    raw: Path,
    keep_zips: bool,
) -> dict[str, Any]:
    plan = design["market_data_plan"]
    base = out / "dataset"
    entry: dict[str, Any] = {"symbol": symbol, "day": day, "windows": len(spans)}

    tape_url = plan["tape_source"].format(symbol=symbol, day=day)
    tape_zip = raw / f"{symbol}-{day}.aggTrades.zip"
    if not tape_zip.exists():
        entry["tape_source"] = _download(tape_url, tape_zip)
    else:
        entry["tape_source"] = {
            "url": tape_url,
            "bytes": tape_zip.stat().st_size,
            "sha256": _sha256(tape_zip),
            "cached": True,
        }
    tape_path = base / "tape" / f"{symbol}-{day}.jsonl.gz"
    stats = reduce_agg_trades(tape_zip, spans, tape_path, day)
    entry["tape"] = {
        "file": str(tape_path.relative_to(out)).replace("\\", "/"),
        "sha256": _sha256(tape_path),
        "bytes": tape_path.stat().st_size,
        **stats,
    }
    if not keep_zips:
        tape_zip.unlink(missing_ok=True)

    klines_url = plan["klines_source"].format(symbol=symbol, day=day)
    klines_zip = raw / f"{symbol}-{day}.1m.zip"
    if not klines_zip.exists():
        entry["klines_source"] = _download(klines_url, klines_zip)
    else:
        entry["klines_source"] = {
            "url": klines_url,
            "bytes": klines_zip.stat().st_size,
            "sha256": _sha256(klines_zip),
            "cached": True,
        }
    klines_path = base / "klines" / f"{symbol}-{day}.jsonl.gz"
    entry["klines"] = {
        "file": str(klines_path.relative_to(out)).replace("\\", "/"),
        **reduce_klines(klines_zip, klines_path),
        "sha256": _sha256(klines_path),
    }
    if not keep_zips:
        klines_zip.unlink(missing_ok=True)

    depth_url = plan["depth_source"].format(symbol=symbol, day=day)
    depth_zip = raw / f"{symbol}-{day}.depth.zip"
    depth_path = base / "depth" / f"{symbol}-{day}.jsonl.gz"
    try:
        if not depth_zip.exists():
            entry["depth_source"] = _download(depth_url, depth_zip)
        else:
            entry["depth_source"] = {
                "url": depth_url,
                "bytes": depth_zip.stat().st_size,
                "sha256": _sha256(depth_zip),
                "cached": True,
            }
        stats = reduce_depth(depth_zip, spans, depth_path)
        entry["depth"] = {
            "file": str(depth_path.relative_to(out)).replace("\\", "/"),
            "sha256": _sha256(depth_path),
            **stats,
            "role": "CALIBRATION_ONLY_FUTURES_BAND_DEPTH",
        }
        if not keep_zips:
            depth_zip.unlink(missing_ok=True)
    except SystemExit as error:
        entry["depth"] = {"status": "NOT_AVAILABLE", "detail": str(error)}
    return entry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--check", action="store_true", help="verify the cache, download nothing")
    parser.add_argument("--keep-zips", action="store_true")
    parser.add_argument("--pair", nargs=2, action="append", default=None, help="debug: SYMBOL DAY")
    args = parser.parse_args(argv)

    out = Path(args.out)
    design, signals, windows = load_plan(out)
    manifest_path = out / "dataset" / "TAPE_MANIFEST.json"
    previous = _read_json(manifest_path) if manifest_path.exists() else {"pairs": {}}
    pairs = previous.get("pairs", {})

    selected = sorted(windows.items())
    if args.pair:
        wanted = {(symbol.upper(), day) for symbol, day in args.pair}
        selected = [item for item in selected if item[0] in wanted]

    entries: dict[str, dict[str, Any]] = {}
    for (symbol, day), spans in selected:
        key = f"{symbol}-{day}"
        known = pairs.get(key)
        if args.check:
            if known is None:
                print(f"[003m-tape] MISSING — {key}", file=sys.stderr)
                return 1
            target = out / known["tape"]["file"]
            if not target.exists() or _sha256(target) != known["tape"]["sha256"]:
                print(f"[003m-tape] TAMPERED — {known['tape']['file']}", file=sys.stderr)
                return 1
            entries[key] = known
            continue
        if known is not None:
            target = out / known["tape"]["file"]
            if target.exists() and _sha256(target) == known["tape"]["sha256"]:
                entries[key] = known
                print(f"[003m-tape] cached {key} ({known['tape']['rows_kept']} rows)")
                continue
        entry = build_entry(
            symbol=symbol,
            day=day,
            spans=spans,
            design=design,
            out=out,
            raw=out / "raw",
            keep_zips=args.keep_zips,
        )
        entries[key] = entry
        print(
            f"[003m-tape] {key}: kept {entry['tape']['rows_kept']} of "
            f"{entry['tape']['rows_in_day']} trades, klines {entry['klines']['rows']}, "
            f"depth {entry['depth'].get('rows', 'n/a')}"
        )

    if args.check:
        print(f"[003m-tape] cache verified: {len(entries)} pairs")
        return 0

    dataset_digests = {
        symbol: {
            "file": f"{symbol}.1m.jsonl.gz",
            "sha256": _sha256(DATASET_SOURCE / f"{symbol}.1m.jsonl.gz"),
        }
        for symbol in design["dataset"]["symbols"]
    }
    payload = {
        "schema_version": SCHEMA,
        "experiment": "EXP-003M-MAKER-FILL-REALITY-001",
        "candidate_signals": len(signals["signals"]),
        "signals_file_sha256": _sha256(out / "analysis" / "SIGNALS.json"),
        "design_sha256": _sha256(out / "design" / "DESIGN.json"),
        "dataset_source": dataset_digests,
        "selection_rule": design["market_data_plan"]["selection_rule"],
        "holdout_guard": {
            "start_utc": design["holdout"]["start_utc"],
            "end_utc": design["holdout"]["end_utc"],
            "status": "ENFORCED_AT_PLAN_TIME",
        },
        "pairs": dict(sorted(entries.items())),
        "totals": {
            "pairs": len(entries),
            "rows_kept": sum(entry["tape"]["rows_kept"] for entry in entries.values()),
            "rows_in_days": sum(entry["tape"]["rows_in_day"] for entry in entries.values()),
            "download_bytes": sum(int(entry["tape_source"]["bytes"]) for entry in entries.values())
            + sum(int(entry["klines_source"]["bytes"]) for entry in entries.values()),
        },
    }
    _write_json(manifest_path, payload)
    print(
        f"[003m-tape] manifest: {payload['totals']['pairs']} pairs, "
        f"{payload['totals']['rows_kept']} rows kept of {payload['totals']['rows_in_days']} "
        f"({payload['totals']['download_bytes'] / 1048576:.1f} MiB downloaded)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
