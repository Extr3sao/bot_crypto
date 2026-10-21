"""EXP-004A phase-2 slice extractor: the ``generator_command`` the dataset registration names.

``config/preregistrations/EXP-004A.datasets.json`` declares four phase-2 datasets and the command
that is supposed to produce each one::

    python scripts/exp004a_capture.py --slice 1h:BTC

Until this file existed, that command was a promise with no implementation behind it: the
declaration's ``generator_code_commit`` is the zero SHA and nothing in the repository answered to
the name. This script makes the declared command real without inventing its contract, because the
contract already exists elsewhere:

* the **row schema** is the forward store's own schema, parsed by
  :func:`trading_bot.research.prospective.store.index_series`. A slice is a projection of bytes the
  observer already stored, never a re-normalisation and never a download.
* the **window** is the ``period_start_utc`` / ``period_end_utc`` pair in the declaration.
* the **fenceposts** are ``period_start_utc <= bar open < period_end_utc``: the closing instant of
  the window belongs to no declared day.
* the **lag** is ``fetched_at_ms - (ts + interval)``, the store's own definition. It is recorded,
  not enforced: a late bar is *kept* in the slice so that admission can reject its day. An extractor
  that dropped late bars would convert "observed late" into "absent" and let coverage arithmetic
  admit a day that RFC-050 §3 requires to fail.

Three refusals carry the provenance argument:

1. an **empty selection is an error**, not an empty dataset — before the capture window opens there
   is nothing to write, and a zero-row file named as evidence is worse than no file;
2. an **existing target is never overwritten**, because a dataset that can be regenerated in place
   is a dataset whose digest certifies nothing;
3. the **ST-6 tape slice is refused** (``st6:tape``): its declared unit is a "4h slot, 3 rounds of
   15s", not a bar in a series, and no rule in the declaration says which rounds belong to which
   window. Implementing that rule here would freeze one, unilaterally, into the preregistration.

Research only: reads local files, writes local files, makes no network call, places no order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.research.prospective.store import (  # noqa: E402
    DEFAULT_LAG_BOUND_MS,
    INTERVAL_MS,
    StoreError,
    index_series,
)

DECLARATION = REPO / "config" / "preregistrations" / "EXP-004A.datasets.json"
DEFAULT_OUT = REPO / "data" / "exp004a"
SCHEMA_VERSION = "1.0"

EXIT_OK = 0
EXIT_CONTRACT = 2
EXIT_EMPTY = 3
EXIT_SOURCE = 4


class SliceError(RuntimeError):
    """The slice cannot be produced without inventing something, so it is not produced."""


@dataclass(frozen=True, slots=True)
class SliceSpec:
    """What the declaration asks for, resolved to paths that actually exist."""

    dataset_id: str
    asset: str
    interval: str
    source: Path
    period_start_ms: int
    period_end_ms: int
    lag_bound_ms: int
    coverage_required: float
    generator_command: str
    raw_file: str | None
    normalized_file: str


def _ms(value: str, field: str) -> int:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as error:
        raise SliceError(f"{field} is not an ISO timestamp: {value!r}") from error
    if moment.tzinfo is None:
        raise SliceError(f"{field} is naive; a window without a zone is not a window")
    return int(moment.astimezone(UTC).timestamp() * 1000)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_declaration(path: Path = DECLARATION) -> dict[str, Any]:
    if not path.is_file():
        raise SliceError(f"{path} does not exist; the slices have no declared contract")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SliceError(f"{path} is not JSON: {error}") from error
    entries = document.get("entries")
    if not isinstance(entries, list) or not entries:
        raise SliceError(f"{path} declares no entries")
    return document


def resolve_spec(
    spec: str,
    declaration: dict[str, Any],
    *,
    period_start: str | None = None,
    period_end: str | None = None,
    source: Path | None = None,
) -> SliceSpec:
    """Match ``1h:BTC`` against the declaration's own ``generator_command``."""
    wanted = spec.strip()
    if ":" not in wanted:
        raise SliceError(f"--slice wants <interval>:<asset>, got {spec!r}")
    interval, asset = wanted.split(":", 1)
    match: dict[str, Any] | None = None
    known: list[str] = []
    for entry in declaration["entries"]:
        command = str(entry.get("generator_command") or "")
        tail = command.split("--slice", 1)[1].strip() if "--slice" in command else ""
        if tail:
            known.append(tail)
        if tail == wanted:
            match = entry
    if match is None:
        raise SliceError(f"{spec!r} is not declared; declared slices are {sorted(known)}")

    declared_interval = str(match.get("timeframe") or "")
    if declared_interval not in INTERVAL_MS:
        raise SliceError(
            f"{match.get('dataset_id')} declares timeframe {declared_interval!r}, which is not a "
            "bar series; a slice rule for it is not defined by the declaration. Refusing rather "
            "than inventing one (this is the st6:tape case)."
        )
    if declared_interval != interval:
        raise SliceError(
            f"{spec!r} asks for {interval!r} but {match.get('dataset_id')} declares "
            f"{declared_interval!r}"
        )
    resolved_source = source or REPO / "data" / "forward" / "edge03" / interval / f"{asset}.jsonl"
    parameters = match.get("generator_parameters") or {}
    lag_bound = int(parameters.get("lag_bound_ms") or DEFAULT_LAG_BOUND_MS[interval])
    coverage = float(parameters.get("coverage_required") or 0.0)
    return SliceSpec(
        dataset_id=str(match["dataset_id"]),
        asset=asset,
        interval=interval,
        source=resolved_source,
        period_start_ms=_ms(period_start or match["period_start_utc"], "period_start_utc"),
        period_end_ms=_ms(period_end or match["period_end_utc"], "period_end_utc"),
        lag_bound_ms=lag_bound,
        coverage_required=coverage,
        generator_command=str(match["generator_command"]),
        raw_file=match.get("raw_file"),
        normalized_file=str(match.get("normalized_file") or ""),
    )


def build_slice(spec: SliceSpec) -> tuple[bytes, dict[str, Any]]:
    """Return the selected bytes, unmodified, plus the manifest that describes them."""
    if spec.period_end_ms <= spec.period_start_ms:
        raise SliceError("the window ends before it starts")
    try:
        index = index_series(spec.source, spec.asset, spec.interval)
    except StoreError as error:
        raise SliceError(str(error)) from error

    opens = [bar.open_ms for bar in index.bars]
    if len(set(opens)) != len(opens):
        raise SliceError(f"{spec.source} repeats a bar open instant; duplicates are not evidence")
    if opens != sorted(opens):
        raise SliceError(f"{spec.source} is not ordered by bar open; offsets would not be a prefix")

    selected = [
        position
        for position, bar in enumerate(index.bars)
        if spec.period_start_ms <= bar.open_ms < spec.period_end_ms
    ]
    if not selected:
        raise SliceError(
            f"no bar of {spec.source.name} opens inside the declared window; an empty slice is not "
            "a dataset (the capture window may not have started yet)"
        )
    unclosed = [position for position in selected if not index.bars[position].closed]
    if unclosed:
        raise SliceError(
            f"{len(unclosed)} selected bar(s) are not closed yet; a dataset of unsettled bars "
            "would be re-read after the fact"
        )

    raw = spec.source.read_bytes()
    chunks: list[bytes] = []
    for position in selected:
        start = index.byte_ends[position - 1] if position else 0
        chunk = raw[start : index.byte_ends[position]]
        if not chunks:
            chunk = chunk.lstrip(b"\r\n")
        if not chunk.endswith(b"\n"):
            chunk += b"\n"
        chunks.append(chunk)
    payload = b"".join(chunks)

    bars = [index.bars[position] for position in selected]
    lags = [bar.lag_ms for bar in bars]
    prefix_bytes = index.byte_ends[selected[-1]]
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": spec.dataset_id,
        "asset": spec.asset,
        "interval": spec.interval,
        "period": {
            "start_utc": _iso(spec.period_start_ms),
            "end_utc": _iso(spec.period_end_ms),
            "fencepost": "bar_open >= start_utc and bar_open < end_utc",
        },
        "row_count": len(bars),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "first_open_utc": _iso(bars[0].open_ms),
        "last_open_utc": _iso(bars[-1].open_ms),
        "source": {
            "path": _relative(spec.source),
            "bars_in_source": len(index.bars),
            "prefix_bytes": prefix_bytes,
            "prefix_sha256": hashlib.sha256(raw[:prefix_bytes]).hexdigest(),
            "total_bytes_at_read": index.total_bytes,
            "sha256_at_read": hashlib.sha256(raw).hexdigest(),
        },
        "declaration": {
            "path": _relative(DECLARATION),
            "generator_command": spec.generator_command,
            "lag_bound_ms": spec.lag_bound_ms,
            "coverage_required": spec.coverage_required,
            "declared_raw_file": spec.raw_file,
            "declared_normalized_file": spec.normalized_file,
            "declaration_sha256": _sha256_file(DECLARATION),
        },
        "observed": {
            "max_lag_ms": max(lags),
            "min_lag_ms": min(lags),
            "bars_outside_lag_bound": sum(1 for lag in lags if not 0 <= lag <= spec.lag_bound_ms),
            "bars_with_negative_lag": sum(1 for lag in lags if lag < 0),
            "late_bars_kept": True,
        },
        "generator": {
            "script": "scripts/exp004a_capture.py",
            "script_sha256": _sha256_file(Path(__file__).resolve()),
            "argv": [
                "python",
                "scripts/exp004a_capture.py",
                "--slice",
                f"{spec.interval}:{spec.asset}",
            ],
        },
        "note": (
            "Bytes are the forward store's own lines, selected by bar open instant. Late bars are "
            "retained so admission, not the extractor, decides the day. No timestamp is written "
            "into this manifest, so re-extracting an unchanged source yields identical bytes."
        ),
    }
    return payload, manifest


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def write_slice(payload: bytes, manifest: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset = out_dir / f"{manifest['dataset_id']}.jsonl"
    manifest_path = out_dir / f"{manifest['dataset_id']}.MANIFEST.json"
    for target in (dataset, manifest_path):
        if target.exists():
            raise SliceError(f"{target} already exists; a dataset is written once, not regenerated")
    dataset.write_bytes(payload)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return dataset, manifest_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--slice", dest="slice_spec", required=True, help="<interval>:<asset>, e.g. 1h:BTC"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--period-start", default=None, help="override period_start_utc (ISO-8601)")
    parser.add_argument("--period-end", default=None, help="override period_end_utc (ISO-8601)")
    parser.add_argument("--dry-run", action="store_true", help="measure without writing")
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="rehearsal override of the series file; the declared command does not pass it",
    )
    args = parser.parse_args(argv)

    try:
        declaration = load_declaration()
        spec = resolve_spec(
            args.slice_spec,
            declaration,
            period_start=args.period_start,
            period_end=args.period_end,
            source=args.source,
        )
        payload, manifest = build_slice(spec)
        if not args.dry_run:
            dataset, manifest_path = write_slice(payload, manifest, Path(args.out))
            manifest["written"] = {
                "dataset": _relative(dataset),
                "manifest": _relative(manifest_path),
            }
        else:
            manifest["written"] = None
    except SliceError as error:
        message = str(error)
        code = EXIT_EMPTY if "empty slice is not a dataset" in message else EXIT_CONTRACT
        if "does not exist" in message or "holds no bars" in message or "is not JSON" in message:
            code = EXIT_SOURCE
        print(
            json.dumps({"ok": False, "error": message, "slice": args.slice_spec}), file=sys.stderr
        )
        return code

    print(json.dumps({"ok": True, "slice": args.slice_spec, "manifest": manifest}, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
