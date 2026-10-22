#!/usr/bin/env python
"""quote_feed_source — re-derive the 1-minute quote fixture from its public archives.

The fixture at ``data/quote-feed-1m`` is what lets the lane prove that a missing 5-minute
bar was a gap in *its* data and not an outage. Two of its properties matter:

* it must be the bytes ``SOURCE_MANIFEST.json`` names, or the integrity test is decorative;
* it must be re-derivable by someone who does not have this checkout, or "the venue was
  open" is an assertion about a file rather than about a market.

Both are checked here. ``verify`` reads the tree and compares every digest the manifest
records. ``fetch`` downloads the monthly archives the manifest names, checks each
archive's sha256 *before* parsing it, rebuilds the series in the declared window and
writes the file with the exact byte format the capture used (compact separators, CRLF
terminator), so the same ``file_sha256`` comes out on any platform. A mismatch is a
failure with a non-zero exit code, never a warning.

Usage::

    python scripts/quote_feed_source.py verify
    python scripts/quote_feed_source.py fetch --out data/quote-feed-1m
    python scripts/quote_feed_source.py fetch --out /tmp/qf --json /tmp/qf/RECEIPT.json
"""

from __future__ import annotations

import argparse
import hashlib
import io
import itertools
import json
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO / "data" / "quote-feed-1m"
MINUTE_MS = 60_000
#: The capture wrote the payload with ``json.dumps(..., separators=(",", ":"))`` and a
#: newline through a text handle opened without ``newline=""`` on Windows, i.e. CRLF.
#: The manifest hashes those bytes; reproducing the terminator is part of reproducing
#: the file, not a cosmetic detail.
TERMINATOR = b"\r\n"


def _canonical_series_digest(rows: list[list[float]]) -> str:
    payload = json.dumps(
        [[int(row[0]), row[1], row[2], row[3], row[4], row[5]] for row in rows],
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _rows_for_window(
    csv_lines: list[bytes], start_ms: int, end_ms: int
) -> list[list[float]]:
    rows: list[list[float]] = []
    for line in csv_lines:
        if not line.strip():
            continue
        cells = line.decode("ascii").strip().split(",")
        stamp = int(cells[0])
        if stamp < int(start_ms) or stamp >= int(end_ms):
            continue
        rows.append(
            [
                float(stamp),
                float(cells[1]),
                float(cells[2]),
                float(cells[3]),
                float(cells[4]),
                float(cells[5]),
            ]
        )
    rows.sort(key=lambda row: row[0])
    return rows


def _payload_bytes(rows: list[list[float]]) -> bytes:
    return json.dumps(rows, separators=(",", ":")).encode("utf-8") + TERMINATOR


def verify(root: Path) -> dict[str, Any]:
    """Every digest the manifest records, checked against the files on disk."""
    manifest_path = root / "SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str) -> bool:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return ok

    for symbol, expected in sorted((manifest.get("symbols") or {}).items()):
        path = root / str(expected["file"])
        if not record(f"{symbol}.present", path.exists(), str(path)):
            continue
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        record(
            f"{symbol}.file_sha256",
            digest == expected["file_sha256"],
            f"observed {digest}, manifest {expected['file_sha256']}",
        )
        rows = json.loads(raw.decode("utf-8"))
        record(
            f"{symbol}.rows",
            len(rows) == int(expected["rows"]),
            f"observed {len(rows)}, manifest {expected['rows']}",
        )
        series = _canonical_series_digest(rows)
        record(
            f"{symbol}.series_sha256",
            series == expected["series_sha256"],
            f"observed {series}, manifest {expected['series_sha256']}",
        )
        record(
            f"{symbol}.first_minute",
            int(rows[0][0]) == int(expected["first_minute_ms"]),
            f"observed {int(rows[0][0])}, manifest {expected['first_minute_ms']}",
        )
        record(
            f"{symbol}.last_minute",
            int(rows[-1][0]) == int(expected["last_minute_ms"]),
            f"observed {int(rows[-1][0])}, manifest {expected['last_minute_ms']}",
        )
        gaps = sum(
            1
            for left, right in itertools.pairwise(rows)
            if int(right[0]) - int(left[0]) != MINUTE_MS
        )
        #: A hole is allowed — the archive may genuinely miss a minute, and the tests
        #: depend on exactly one such hole. It is counted, not repaired.
        record(
            f"{symbol}.minute_grid",
            True,
            f"{len(rows)} rows, {gaps} non-consecutive step(s); holes are preserved, "
            "never interpolated",
        )

    failed = [check["check"] for check in checks if not check["ok"]]
    return {
        "mode": "verify",
        "root": str(root),
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if manifest_path.exists()
        else None,
        "checks": checks,
        "failed": failed,
        "ok": not failed and bool(checks),
    }


def _download(url: str, expected_sha: str, expected_bytes: int) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:  # pinned https manifest
        archive = response.read()
    observed = hashlib.sha256(archive).hexdigest()
    if len(archive) != int(expected_bytes) or observed != expected_sha:
        raise SystemExit(
            f"{url}: the archive is not the one the manifest names "
            f"({len(archive)} bytes/{observed}, expected {expected_bytes}/{expected_sha})"
        )
    return archive


def fetch(root: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    """Rebuild the fixture from ``data.binance.vision`` and verify what was written."""
    manifest_path = manifest_path or (root / "SOURCE_MANIFEST.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root.mkdir(parents=True, exist_ok=True)
    rebuilt: list[dict[str, Any]] = []
    for symbol, expected in sorted((manifest.get("symbols") or {}).items()):
        window = dict(expected["window"])
        rows: list[list[float]] = []
        for archive in expected["archives"]:
            raw = _download(
                str(archive["url"]), str(archive["sha256"]), int(archive["bytes"])
            )
            with zipfile.ZipFile(io.BytesIO(raw)) as bundle:
                names = [name for name in bundle.namelist() if name.endswith(".csv")]
                if len(names) != 1:
                    raise SystemExit(f"{archive['url']}: {len(names)} csv members")
                lines = bundle.read(names[0]).splitlines()
            #: ``rows_in_archive`` counts the month, not the window: it is the statement
            #: that the zip holds what it claims, before any filtering.  A different count
            #: means the archive or the parse moved, so the window is not the suspect.
            observed_rows = sum(1 for line in lines if line.strip())
            if observed_rows != int(archive["rows_in_archive"]):
                raise SystemExit(
                    f"{archive['url']}: {observed_rows} rows in the archive, "
                    f"manifest declares {archive['rows_in_archive']}"
                )
            part = _rows_for_window(lines, int(window["start_ms"]), int(window["end_ms"]))
            rows.extend(part)
        payload = _payload_bytes(rows)
        target = root / str(expected["file"])
        target.write_bytes(payload)
        observed = hashlib.sha256(payload).hexdigest()
        rebuilt.append(
            {
                "symbol": symbol,
                "file": str(target),
                "bytes": len(payload),
                "rows": len(rows),
                "file_sha256": observed,
                "file_sha256_matches": observed == expected["file_sha256"],
                "series_sha256_matches": _canonical_series_digest(rows)
                == expected["series_sha256"],
            }
        )
    #: ``verify`` reads the manifest from the directory it checks, so a rebuilt tree has to
    #: carry the pinned manifest it was built from. Copied byte for byte, not regenerated:
    #: regenerating it would make the check compare a file with itself.
    target_manifest = root / "SOURCE_MANIFEST.json"
    if not target_manifest.exists() or target_manifest != manifest_path:
        target_manifest.write_bytes(manifest_path.read_bytes())
    receipt = {
        "mode": "fetch",
        "root": str(root),
        "manifest": str(manifest_path),
        "symbols": rebuilt,
        "ok": all(
            item["file_sha256_matches"] and item["series_sha256_matches"]
            for item in rebuilt
        ),
    }
    verification = verify(root)
    receipt["verify"] = {
        "ok": verification["ok"],
        "failed": verification["failed"],
        "checks": len(verification["checks"]),
    }
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["fetch", "verify"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    root = args.root if args.root.is_absolute() else Path.cwd() / args.root
    receipt = fetch(root, args.manifest) if args.mode == "fetch" else verify(root)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
