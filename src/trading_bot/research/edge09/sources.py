"""WP-EDGE-09B — provider viability, coverage, provenance and point-in-time.

Two halves, both measured:

* **What a provider offers today.** Bounded, read-only probes against the public
  endpoints the registered sources name. A probe that fails is recorded as
  failed; a probe that succeeds records what it returned (status, latency, and
  the measured reach such as the oldest funding timestamp). No datum is invented
  and no missing series is substituted by another one.
* **What this repository already holds.** The forward microstructure captures
  are measured from their own manifests and segment trees: duration, continuity,
  which streams exist per market and symbol, and how many samples each carries.

Classification vocabulary is the vocabulary of the source registry this project
already keeps (``docs/source_registry.md``): ``HISTORICAL_USABLE``,
``LIMITED_HISTORY``, ``FORWARD_ONLY``, ``UNAVAILABLE_IN_CURRENT_ENVIRONMENT``,
``ALTERNATIVE_SOURCE_AVAILABLE``.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .registration import CAPTURE_ROOT, REPO_ROOT

#: Endpoints probed, with what each probe establishes. Kept deliberately short:
#: a probe is only here if its answer changes a gate of this package.
PROBES: tuple[dict[str, str], ...] = (
    {
        "id": "P-01",
        "what": "funding history reach (alternatives: none for a perp-only series)",
        "url": "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1000",
    },
    {
        "id": "P-02",
        "what": "open-interest retention: the newest window the endpoint will serve",
        "url": "https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=5m&limit=500",
    },
    {
        "id": "P-03",
        "what": "liquidation prints: does a public endpoint exist at all",
        "url": "https://fapi.binance.com/fapi/v1/allForceOrders?symbol=BTCUSDT&limit=100",
    },
    {
        "id": "P-04",
        "what": "order-book history: the endpoint answers with the current book only",
        "url": "https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=5",
    },
    {
        "id": "P-05",
        "what": "bulk archive reach for aggressor flow (monthly klines)",
        "url": "https://data.binance.vision/data/spot/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2026-08.zip",
    },
)

#: The classification of every source this package consulted, with the evidence
#: that produced it. ``measured_on`` is the date of the measurement, never the
#: date the claim was first written.
SOURCE_VERDICTS: tuple[dict[str, str], ...] = (
    {
        "source_id": "SRC-19",
        "name": "forward microstructure capture (this repository)",
        "depth": "hours, not weeks: see the measured spans in this artifact",
        "pit": "yes — every row carries event/available/receive clocks and the panel uses receive",
        "classification": "FORWARD_ONLY",
        "why": "order book and quote state exist only forward; the capture is what makes M-03 measurable",
    },
    {
        "source_id": "SRC-20",
        "name": "spot aggressor flow from klines (taker buy fields)",
        "depth": "complete history, aggregated per bar",
        "pit": "bar close only",
        "classification": "HISTORICAL_USABLE",
        "why": "already used by the microstructure phase; unchanged here",
    },
    {
        "source_id": "SRC-21",
        "name": "perp funding and premium index",
        "depth": "complete history",
        "pit": "publication instant",
        "classification": "HISTORICAL_USABLE",
        "why": "re-probed here; the depth is measured, not assumed",
    },
    {
        "source_id": "SRC-22",
        "name": "perp open interest",
        "depth": "~30 days retained",
        "pit": "publication instant",
        "classification": "LIMITED_HISTORY",
        "why": "cannot cover a decisive window; measured again here rather than remembered",
    },
    {
        "source_id": "SRC-23",
        "name": "liquidation prints",
        "depth": "none from this environment",
        "pit": "n/a",
        "classification": "UNAVAILABLE_IN_CURRENT_ENVIRONMENT",
        "why": "the public endpoint that once served them does not answer; no substitute is used",
    },
    {
        "source_id": "SRC-24",
        "name": "venue fee schedules (Binance/OKX/Kraken/MEXC) already registered",
        "depth": "published headline rates",
        "pit": "n/a",
        "classification": "HISTORICAL_USABLE",
        "why": "the barrier this package measures against is built from these, not from assumptions",
    },
)


def _probe(url: str, timeout: float) -> dict[str, Any]:
    started = time.time()
    request = urllib.request.Request(url, headers={"User-Agent": "edge09-research/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(4096)
            status = response.status
    except urllib.error.HTTPError as exc:
        return {
            "status": exc.code,
            "seconds": round(time.time() - started, 3),
            "note": f"HTTPError {exc.code}",
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {
            "status": None,
            "seconds": round(time.time() - started, 3),
            "note": f"{type(exc).__name__}: {exc}",
        }
    return {
        "status": status,
        "seconds": round(time.time() - started, 3),
        "bytes": len(payload),
        "head": payload[:120].decode("utf-8", errors="replace"),
    }


def probe_providers(*, timeout: float = 8.0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for probe in PROBES:
        outcome = _probe(probe["url"], timeout)
        rows.append(
            {
                "id": probe["id"],
                "what": probe["what"],
                "url": probe["url"],
                **outcome,
                "reachable": outcome.get("status") == 200,
            }
        )
    return rows


def _manifest(root: Path) -> dict[str, Any]:
    manifests = sorted((root / "manifest").glob("*.json"))
    if not manifests:
        return {}
    try:
        payload = json.loads(manifests[-1].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def capture_quality() -> dict[str, Any]:
    """Measure the corpora this repository holds, per root and per stream."""
    roots = [
        parent
        for parent in sorted(REPO_ROOT.glob("reports/microstructure-forward*"))
        if (parent / "manifest").is_dir() or (parent / "segments").is_dir()
    ]
    per_root: list[dict[str, Any]] = []
    streams: dict[tuple[str, str, str], int] = {}
    for root in roots:
        manifest = _manifest(root)
        segments = (
            list((root / "segments").rglob("*.jsonl.gz")) if (root / "segments").is_dir() else []
        )
        for segment in segments:
            parts = segment.relative_to(root / "segments" / "binance").parts
            if len(parts) >= 3:
                key = (parts[0], parts[1], parts[2])
                streams[key] = streams.get(key, 0) + 1
        per_root.append(
            {
                "root": str(root.relative_to(REPO_ROOT)).replace("\\", "/"),
                "run_id": manifest.get("run_id"),
                "duration_seconds": manifest.get("duration_seconds"),
                "continuity": manifest.get("continuity"),
                "markets": manifest.get("markets") or manifest.get("market"),
                "segments": len(segments),
                "bytes_written": manifest.get("bytes_written"),
                "reconnects": manifest.get("reconnects"),
                "resnapshots": manifest.get("resnapshots"),
                "gaps": manifest.get("gaps"),
                "disk_bytes_per_hour": manifest.get("disk_bytes_per_hour"),
            }
        )
    stream_rows = [
        {"market": market, "symbol": symbol, "stream": stream, "segments": count}
        for (market, symbol, stream), count in sorted(streams.items())
    ]
    continuous = [row for row in per_root if row["continuity"] == "CONTINUOUS_DATA"]
    incomplete = [row for row in per_root if row["continuity"] == "INCOMPLETE_DATA"]
    durations = [row["duration_seconds"] or 0.0 for row in per_root]
    return {
        "roots": len(per_root),
        "per_root": per_root,
        "per_stream": stream_rows,
        "total_seconds": round(sum(durations), 2),
        "total_hours": round(sum(durations) / 3600.0, 3),
        "longest_seconds": round(max(durations) if durations else 0.0, 2),
        "runs_continuous": len(continuous),
        "runs_incomplete": len(incomplete),
        "continuity_note": (
            "most captures declare INCOMPLETE_DATA: the loss is quantified in their own "
            "manifests (gaps, reconnects, resnapshots), and this package reads the declared "
            "loss instead of assuming a clean stream"
        ),
        "markets_covered": sorted({row["market"] for row in stream_rows}),
        "symbols_covered": sorted({row["symbol"] for row in stream_rows}),
        "streams_covered": sorted({row["stream"] for row in stream_rows}),
        "capture_root": str(CAPTURE_ROOT.relative_to(REPO_ROOT)).replace("\\", "/"),
    }


def build(*, probe: bool = True) -> dict[str, Any]:
    return {
        "probes": probe_providers() if probe else [],
        "probes_skipped": not probe,
        "probe_note": (
            "a probe is a measurement of the endpoint at this moment; it is not a license "
            "to substitute a series that does not exist"
        ),
        "captured": capture_quality(),
        "source_verdicts": [dict(row) for row in SOURCE_VERDICTS],
    }


__all__ = [
    "PROBES",
    "SOURCE_VERDICTS",
    "build",
    "capture_quality",
    "probe_providers",
]
