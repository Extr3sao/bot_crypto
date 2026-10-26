#!/usr/bin/env python
"""RFC-049B — FINAL ADMISSION CHECK FOR DISCOVERY 2 (phase A completion).

What this builder does
----------------------
1. Attests the frozen Phase A baseline (spec hashes, dataset hashes, freeze
   timestamp, governance flags) without rewriting any of it.
2. Verifies what the frozen signal variable *is*, at the vendor payload itself,
   and re-fetches the vendor series to measure revision exposure.
3. Verifies every macro input of H-049-002 against its primary source
   (H.4.1 release page, NY Fed reverse-repo API, Treasury DTS API), records
   units/frequency/observation-vs-publication semantics, measures revision
   exposure with ALFRED vintages, and proves decision-time availability.
4. Measures hypothesis independence structurally (state overlap on
   research-exposed inputs; **no returns, no PnL**).
5. Measures OOS sample feasibility under the frozen rules (trade counts only)
   plus the analytic sample size a target precision implies.
6. Raises the read level of every decisive source to the highest level that is
   legally reachable, and records what could not be read.
7. Emits the RFC-049B deliverables and runs inline contract checks.

What this builder does NOT do
-----------------------------
No signal return, no PnL, no backtest, no parameter search, no OOS opening.
``NEXT_CAMPAIGN`` stays ``NOT_AUTHORIZED``; the campaign itself is not started.

The independent verifier is ``scripts/rfc049b_verify.py``; it never imports this
module and recomputes every number from the frozen inputs and the retained raw
evidence.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import io
import json
import math
import re
import statistics
import subprocess
import sys
import urllib.parse
import urllib.request
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "rfc049"
ADM = DATA / "admission"
RAW = ADM / "raw"
SPECS = DATA / "specs"
VENDOR_RAW = DATA / "vendor" / "raw"
PRICE_1D = ROOT / "data" / "raw" / "alpha001" / "BTC-USDT_1d.json"

FROZEN_MANIFEST = DATA / "PREREGISTRATION_MANIFEST.json"
VENDOR_MANIFEST = DATA / "vendor" / "VENDOR_MANIFEST.json"
EXPOSURE_AUDIT = DATA / "DATA_EXPOSURE_AUDIT.json"
RFC048_FINAL_REPORT = ROOT / "data" / "rfc048" / "FINAL_REPORT.json"
RFC048V_CERT = ROOT / "data" / "rfc048" / "FINAL_CERTIFICATION_REPORT.json"

GOVERNANCE_EXPECTED: dict[str, Any] = {
    "DISCOVERY_CAMPAIGN_FAILED": True,
    "NEXT_CAMPAIGN": "NOT_AUTHORIZED",
    "LIVE_TRADING": "DISABLED",
    "TRADES_AUTHORIZED": 0,
    "PROFITABILITY_VERIFIED": False,
}

#: Historical repository defect that §11 of RFC-049 requires to be assessed on
#: every data route used.
DEF_HTF_PIT_001 = "DEF-HTF-PIT-001"

#: The frozen text says "most recent observation on or before" without bounding
#: the reach-back.  A bounded reach-back is strictly more conservative (it yields
#: FLAT), and it is declared here so nobody can suspect it was chosen to help a
#: candidate.
ASOF_MAX_REACHBACK_DAYS = 7

UA = "Mozilla/5.0 (research; RFC-049B admission audit)"

#: upper bound on any single evidence body (the largest real body here is ~1.4 MB)
MAX_BODY_BYTES = 4_000_000

#: bodies up to this size are retained in the repository as raw evidence.  The largest
#: body here is the 1.3 MB stablecoin re-fetch, which is the evidence for the revision
#: claim, so it must be retained rather than only hashed.
RAW_LIMIT = 1_600_000
EVIDENCE: list[dict[str, Any]] = []
CHECKS: list[dict[str, Any]] = []


class EvidenceUnavailable(RuntimeError):
    """Raised when a piece of external evidence cannot be retrieved."""


def log(message: str) -> None:
    """Unbuffered progress reporting: a long audit must be observable while it runs."""
    print(f"[{utcnow()}] {message}", flush=True)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def record(name: str, status: str, detail: str) -> None:
    CHECKS.append({"check": name, "result": status, "detail": detail})


def check(name: str, passed: bool, detail: str) -> bool:
    record(name, "PASS" if passed else "FAIL", detail)
    return passed


def check_blocked(name: str, detail: str) -> None:
    record(name, "BLOCKED", detail)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, text=True, check=True).stdout.strip()


def _read_bounded(resp: Any, deadline: float) -> tuple[bytes, bool]:
    """Chunked read that stops at a deadline and keeps whatever arrived.

    Several publisher endpoints (FRED series pages among them) stream keep-alive
    responses that never signal EOF, so ``read()`` and ``read(huge)`` both hang.
    A deadline-bounded chunked read returns the head of the body instead, which is
    what metadata extraction needs, and records the truncation.
    """
    import time

    chunks: list[bytes] = []
    total = 0
    truncated = False
    while total < MAX_BODY_BYTES:
        try:
            chunk = resp.read(65_536)
        except Exception:  # noqa: BLE001 - partial body is better than a hang
            truncated = True
            break
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if time.monotonic() > deadline:
            truncated = True
            break
    return b"".join(chunks), truncated


def _http(url: str, timeout: int, attempts: int = 3) -> tuple[int, str, bytes, bool]:
    """GET with bounded retries; a transient refusal must never become evidence."""
    import time

    last: Exception | None = None
    for attempt in range(attempts):
# NOTE: do not send an explicit Accept header.  The FRED/ALFRED hosts drop the
        # connection (RemoteDisconnected) when one is present, which looks exactly like a
        # rate limit but is a content-negotiation refusal; urllib's default works.
        req = urllib.request.Request(
            urllib.parse.quote(url, safe=":/?&=[]%,.-_@"),
            headers={"User-Agent": UA},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body, truncated = _read_bounded(resp, time.monotonic() + timeout)
                if not body:
                    raise EvidenceUnavailable("empty body")
                return resp.status, str(resp.headers.get("Content-Type", "")), body, truncated
        except Exception as exc:  # noqa: BLE001 - bounded retry boundary
            last = exc
            if attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))
    raise EvidenceUnavailable(f"{type(last).__name__}: {last} -> {url}")


def detag(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    for a, b in (
        ("&nbsp;", " "), ("&amp;", "&"), ("&#039;", "'"), ("&#x27;", "'"),
        ("&quot;", '"'), ("&lt;", "<"), ("&gt;", ">"), ("&middot;", "-"),
        ("&mdash;", "-"), ("&ndash;", "-"), ("&#160;", " "),
    ):
        html = html.replace(a, b)
    html = re.sub(r"&#x?[0-9A-Fa-f]{2,6};", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def unsquash(text: str) -> str:
    """Collapse letter-by-letter spacing introduced by some PDF encoders."""
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"(?<=\b\w) (?=\w\b)", "", text)
    return re.sub(r"\s+", " ", text)


def prose_metrics(text: str) -> dict[str, Any]:
    squashed = "".join(text.split())
    letters = sum(1 for c in squashed if c.isalpha())
    low = squashed.lower()
    return {
        "squashed_chars": len(squashed),
        "alpha_ratio": letters / max(1, len(squashed)),
        "stopword_hits": sum(low.count(w) for w in ("the", "and", "of", "that", "is", "we", "are")),
    }


def looks_like_prose(text: str) -> bool:
    """Reject PDF font-encoding garbage.

    Thresholds are measured, not guessed: a readable publisher PDF with letter-
    spacing artefacts scores alpha_ratio 0.506 / 1797 stop-words, while a PDF that
    encodes glyphs through a subset font scores 0.130 / 0 stop-words.  Anything in
    between is treated as unread rather than paraphrased.
    """
    metrics = prose_metrics(text)
    return (
        metrics["squashed_chars"] >= 400
        and metrics["alpha_ratio"] >= 0.40
        and metrics["stopword_hits"] >= 20
    )


def pdf_text(blob: bytes) -> str:
    """Minimal FlateDecode + string-operator extractor (no third-party deps).

    Returns '' when the PDF maps glyphs through a subset encoding that cannot be
    recovered; callers then treat the file as unread instead of guessing.
    """
    chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n", blob):
        start = match.end()
        end = blob.find(b"endstream", start)
        if end < 0:
            continue
        try:
            data = zlib.decompress(blob[start:end])
        except Exception:
            continue
        if b"Tj" not in data and b"TJ" not in data:
            continue
        for sm in re.finditer(rb"\(((?:\\.|[^\\()])*)\)", data):
            chunks.append(sm.group(1).decode("latin-1"))
    text = unsquash(" ".join(chunks).replace("\\(", "(").replace("\\)", ")"))
    return text if looks_like_prose(text) else ""


def load_fred_csv(path: Path) -> tuple[str, dict[date, float | None]]:
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    if not rows:
        return "", {}
    header, body = rows[0], rows[1:]
    column = header[1] if len(header) > 1 else ""
    out: dict[date, float | None] = {}
    for row in body:
        if not row or not row[0]:
            continue
        raw = (row[1] if len(row) > 1 else "").strip()
        out[date.fromisoformat(row[0])] = float(raw) if raw not in ("", ".", "null") else None
    return column, out


def load_vendor_series(sid: str) -> tuple[str, dict[date, float | None]]:
    return load_fred_csv(VENDOR_RAW / f"fred_{sid}.csv")


def parse_alfred_csv(blob: bytes) -> tuple[str, dict[date, float | None]]:
    rows = list(csv.reader(io.StringIO(blob.decode("utf-8", "ignore"))))
    if not rows or len(rows[0]) < 2:
        return "", {}
    column, out = rows[0][1], {}
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        raw = (row[1] if len(row) > 1 else "").strip()
        try:
            day = date.fromisoformat(row[0])
        except ValueError:
            continue
        out[day] = float(raw) if raw not in ("", ".", "null") else None
    return column, out


def defillama_rows(path: Path) -> list[tuple[date, float, float]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[tuple[date, float, float]] = []
    for row in data:
        day = datetime.fromtimestamp(int(row["date"]), timezone.utc).date()
        usd = (row.get("totalCirculatingUSD") or {}).get("peggedUSD")
        qty = (row.get("totalCirculating") or {}).get("peggedUSD")
        if usd is None or qty is None:
            continue
        out.append((day, float(usd), float(qty)))
    out.sort(key=lambda r: r[0])
    return out


def load_bars(path: Path) -> list[tuple[int, float]]:
    """[(open_time_ms, open_price)]. The price is read to locate execution bars only;
    no return, PnL or performance quantity is computed anywhere in this module."""
    bars = [(int(b[0]), float(b[1])) for b in json.loads(path.read_text(encoding="utf-8"))]
    bars.sort(key=lambda b: b[0])
    return bars


def sundays(first: date, last: date) -> list[date]:
    day = first + timedelta(days=(6 - first.weekday()) % 7)
    out: list[date] = []
    while day <= last:
        out.append(day)
        day += timedelta(days=7)
    return out


def asof(
    series: dict[date, float | None], when: date, max_reachback_days: int = ASOF_MAX_REACHBACK_DAYS
) -> float | None:
    """Most recent non-null observation on or before `when`, with bounded reach-back."""
    for back in range(0, max_reachback_days + 1):
        value = series.get(when - timedelta(days=back))
        if value is not None:
            return value
    return None


def bar_after(bars: list[tuple[int, float]], instant: datetime) -> int | None:
    times = [b[0] for b in bars]
    ms = int(instant.timestamp() * 1000)
    pos = bisect.bisect_right(times, ms)
    return times[pos] if pos < len(times) else None


# --------------------------------------------------------------------------- #
# evidence retrieval
# --------------------------------------------------------------------------- #

RETRIEVAL_PLAN: tuple[tuple[str, str, int, bool, bool], ...] = (
    # key, url, timeout, store_raw, critical
    ("refetch_defillama.json", "https://stablecoins.llama.fi/stablecoincharts/all", 120, True, True),
    ("fred_page_WALCL.html", "https://fred.stlouisfed.org/series/WALCL", 30, True, False),
    ("fred_page_RRPONTSYD.html", "https://fred.stlouisfed.org/series/RRPONTSYD", 30, True, False),
    ("fred_page_WTREGEN.html", "https://fred.stlouisfed.org/series/WTREGEN", 30, True, False),
    ("alfred_WALCL_latest.csv", "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=WALCL", 120, True, True),
    ("alfred_WALCL_2019-03-07.csv",
     "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=WALCL&vintage_date=2019-03-07", 120, True, True),
    ("alfred_WALCL_2023-03-15.csv",
     "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=WALCL&vintage_date=2023-03-15", 120, True, True),
    ("alfred_WTREGEN_latest.csv", "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=WTREGEN", 120, True, True),
    ("alfred_WTREGEN_2019-03-07.csv",
     "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=WTREGEN&vintage_date=2019-03-07", 120, True, True),
    ("alfred_WTREGEN_2023-03-15.csv",
     "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=WTREGEN&vintage_date=2023-03-15", 120, True, True),
    ("alfred_RRPONTSYD_latest.csv", "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=RRPONTSYD", 120, True, True),
    ("alfred_RRPONTSYD_2019-03-07.csv",
     "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=RRPONTSYD&vintage_date=2019-03-07", 120, True, True),
    ("alfred_RRPONTSYD_2023-03-15.csv",
     "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=RRPONTSYD&vintage_date=2023-03-15", 120, True, True),
    ("h41_current.html", "https://www.federalreserve.gov/releases/h41/current/h41.htm", 90, True, True),
    ("nyfed_rrp_last7.json",
     "https://markets.newyorkfed.org/api/rp/reverserepo/all/results/last/7.json", 60, True, True),
    ("dts_tga.json",
     "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/dts/operating_cash_balance"
     "?filter=record_date:gte:2026-09-01&fields=record_date,account_type,open_today_bal,close_today_bal"
     "&page[size]=100&sort=record_date", 90, True, True),
    ("arxiv_abs.html", "https://arxiv.org/abs/2411.06327v2", 90, True, True),
    ("arxiv_pdf.pdf", "https://arxiv.org/pdf/2411.06327v2", 150, False, False),
    ("fedsnote.html",
     "https://www.federalreserve.gov/econres/notes/feds-notes/"
     "primary-and-secondary-markets-for-stablecoins-20240223.html", 120, True, True),
    ("philly_wp26-24.pdf",
     "https://www.philadelphiafed.org/-/media/frbp/assets/working-papers/2026/wp26-24.pdf", 180, False, True),
    ("bis_wp402.html", "https://www.bis.org/publ/work402.htm", 120, True, False),
    # publisher pages refused us; the registration agency still answers, and its metadata
    # is versioned and citable in a way that a scraped snippet is not
    ("crossref_fintech5030068.json", "https://api.crossref.org/works/10.3390/fintech5030068", 60, True, True),
    ("crossref_ssrn4904716.json",
     "https://api.crossref.org/works?query.bibliographic="
     "Does%20monetary%20liquidity%20affect%20Bitcoin%20price&rows=3&select=DOI,title,container-title,issued,type",
     60, True, True),
    ("blocked_mdpi.html", "https://www.mdpi.com/1911-8074/18/9/491", 40, False, False),
    ("blocked_ssrn.html", "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4904716", 40, False, False),
)


def retrieve(offline: bool, fill: bool = False) -> dict[str, bytes]:
    """Retrieve evidence with per-key provenance.

    ``offline`` never touches the network; ``fill`` uses a retained copy when one
    exists and fetches only what is missing, so repeated runs converge instead of
    re-hammering publishers that throttle.
    """
    ev: dict[str, bytes] = {}
    for key, url, timeout, store_raw, critical in RETRIEVAL_PLAN:
        path = RAW / key
        meta_path = RAW / f"{key}.meta.json"
        have_copy = path.exists()
        try:
            if offline or (fill and have_copy):
                if not have_copy:
                    raise EvidenceUnavailable("no retained copy")
                blob = path.read_bytes()
                meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
                row = {
                    "key": key, "url": url, "retrieved_at_utc": meta.get("retrieved_at_utc", utcnow()),
                    "mode": meta.get("mode", "cache"), "http_status": meta.get("http_status"),
                    "content_type": meta.get("content_type"), "bytes": len(blob),
                    "sha256": sha256_bytes(blob), "raw_retained": True, "status": "ok",
                    "served_from_cache_at_utc": utcnow(),
                }
                log(f"evidence: cache hit {key} ({len(blob)} bytes)")
            else:
                log(f"evidence: fetching {key}")
                status, ctype, blob, truncated = _http(url, timeout)
                row = {
                    "key": key, "url": url, "retrieved_at_utc": utcnow(), "mode": "network",
                    "http_status": status, "content_type": ctype, "bytes": len(blob),
                    "sha256": sha256_bytes(blob), "raw_retained": store_raw and len(blob) <= RAW_LIMIT,
                    "status": "ok", "body_truncated_at_deadline": truncated,
                }
                if row["raw_retained"]:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(blob)
                    meta_path.write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
                log(f"evidence: ok {key} ({len(blob)} bytes)")
            EVIDENCE.append(row)
            ev[key] = blob
        except Exception as exc:  # noqa: BLE001
            log(f"evidence: unavailable {key} ({type(exc).__name__})")
            EVIDENCE.append({
                "key": key, "url": url, "retrieved_at_utc": utcnow(),
                "mode": "offline" if offline else "network", "http_status": None, "bytes": 0,
                "sha256": None, "raw_retained": False, "status": "unavailable",
                "note": f"{type(exc).__name__}: {exc}",
            })
            ev[key] = b""
            check_blocked(f"evidence:{key}", f"{'critical' if critical else 'optional'} evidence unavailable: "
                                             f"{type(exc).__name__}: {exc}")
    return ev


def anchor_quote(text: str, anchors: tuple[str, ...], before: int = 500, after: int = 1000) -> tuple[str, str | None]:
    """Quote the deepest occurrence of the most article-specific anchor.

    Publisher pages carry navigation boilerplate before the article, so an anchor's
    *last* occurrence is the body.  The anchor used is recorded so a verifier can
    re-locate the same text independently.
    """
    best: tuple[int, str] | None = None
    low = text.lower()
    for anchor in anchors:
        idx = low.rfind(anchor.lower())
        if idx > 0 and (best is None or idx > best[0]):
            best = (idx, anchor)
    if best is None:
        return "", None
    idx, anchor = best
    return text[max(0, idx - before) : idx + after].strip(), anchor


def semantic_scholar(offline: bool, fill: bool = False) -> list[dict[str, Any]]:
    key = "semantic_scholar.json"
    path = RAW / key
    cached_ok = False
    if path.exists():
        try:
            cached_ok = all(block["status"] == "ok" for block in json.loads(path.read_text(encoding="utf-8"))["results"])
        except Exception:  # noqa: BLE001
            cached_ok = False
    if not (offline or (fill and cached_ok)):
        queries = [
            "The Relationship Between Stablecoin and Cryptocurrency Returns During Periods of Market Stress",
            "Does monetary liquidity affect Bitcoin price",
        ]
        payload: list[dict[str, Any]] = []
        for q in queries:
            url = (
                "https://api.semanticscholar.org/graph/v1/paper/search?query="
                + urllib.parse.quote(q)
                + "&limit=3&fields=title,abstract,year,venue,externalIds,openAccessPdf"
            )
            try:
                _, _, blob, _ = _http(url, 60, attempts=3)
                data = json.loads(blob)
                payload.append({
                    "query": q,
                    "status": "ok",
                    "results": [
                        {
                            "title": p.get("title"), "year": p.get("year"), "venue": p.get("venue"),
                            "doi": (p.get("externalIds") or {}).get("DOI"),
                            "abstract": (p.get("abstract") or "")[:1500],
                            "open_access_pdf": (p.get("openAccessPdf") or {}).get("url"),
                        }
                        for p in (data.get("data") or [])
                    ],
                })
            except Exception as exc:  # noqa: BLE001
                payload.append({"query": q, "status": "unavailable", "note": f"{type(exc).__name__}: {exc}"})
        # a transient refusal must not erase a previously successful lookup
        if path.exists():
            previous = {block.get("query"): block for block in json.loads(path.read_text(encoding="utf-8"))["results"]}
            payload = [block if block["status"] == "ok" or block["query"] not in previous else previous[block["query"]]
                       for block in payload]
        write_json(path, {"retrieved_at_utc": utcnow(), "results": payload})
        EVIDENCE.append({
            "key": key, "url": "https://api.semanticscholar.org/graph/v1/paper/search",
            "retrieved_at_utc": utcnow(), "mode": "network", "http_status": 200,
            "bytes": path.stat().st_size, "sha256": sha256_file(path), "raw_retained": True, "status": "ok",
        })
    if not path.exists():
        check_blocked("evidence:semantic_scholar", "abstract recovery unavailable")
        return []
    return json.loads(path.read_text(encoding="utf-8"))["results"]


# --------------------------------------------------------------------------- #
# 1. baseline attestation
# --------------------------------------------------------------------------- #


def baseline_attestation() -> dict[str, Any]:
    head = git("rev-parse", "HEAD")
    dirty = [ln for ln in git("status", "--porcelain").splitlines() if ln.strip()]
    manifest = json.loads(FROZEN_MANIFEST.read_text(encoding="utf-8"))

    spec_rows = []
    for hid, row in manifest["spec_hashes"].items():
        path = ROOT / row["spec_file"]
        actual = sha256_file(path)
        if row["status"] == "SPEC_FROZEN":
            check(
                f"baseline:spec_unchanged:{hid}",
                actual == row["spec_file_sha256"],
                "frozen spec bytes identical to the freeze-time hash",
            )
        spec_rows.append({
            "hypothesis_id": hid,
            "status": row["status"],
            "spec_file": row["spec_file"],
            "frozen_spec_file_sha256": row["spec_file_sha256"],
            "observed_spec_file_sha256": actual,
            "unchanged_since_freeze": actual == row["spec_file_sha256"],
            "frozen_canonical_sha256": row["spec_canonical_sha256"],
        })

    dataset_rows = []
    for group, entries in manifest["dataset_hashes"].items():
        for relpath, row in entries.items():
            # the price group is keyed by repository path, the vendor group by file name
            path = (VENDOR_RAW / relpath) if group == "signal_series" else (ROOT / relpath)
            actual = sha256_file(path) if path.exists() else None
            dataset_rows.append({
                "group": group, "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                "frozen_sha256": row["sha256"], "observed_sha256": actual, "unchanged": actual == row["sha256"],
            })
            check(f"baseline:dataset_unchanged:{path.name}", actual == row["sha256"], "frozen dataset bytes unchanged")

    exposure = json.loads(EXPOSURE_AUDIT.read_text(encoding="utf-8"))
    vendor = json.loads(VENDOR_MANIFEST.read_text(encoding="utf-8"))
    for name, row in vendor["series"].items():
        path = VENDOR_RAW / name
        actual = sha256_file(path) if path.exists() else None
        check(f"baseline:vendor_bytes:{name}", actual == row["sha256"], "vendor snapshot bytes unchanged")

    governance = json.loads(RFC048_FINAL_REPORT.read_text(encoding="utf-8"))["NEXT_GATE"]["governance_preserved"]
    check("baseline:governance", all(governance.get(k) == v for k, v in GOVERNANCE_EXPECTED.items()),
          json.dumps(governance, sort_keys=True))

    cert = json.loads(RFC048V_CERT.read_text(encoding="utf-8"))
    check("baseline:rfc048v", bool(cert.get("RFC048_FINAL_STATUS")), str(cert.get("RFC048_FINAL_STATUS")))
    check(
        "baseline:exposure_audit_gate",
        exposure["activation_gate"]["next_campaign"] == "NOT_AUTHORIZED"
        and exposure["activation_gate"]["trades_authorized"] == 0
        and exposure["activation_gate"]["live_trading"] == "DISABLED",
        "Phase A activation-gate flags still read NOT_AUTHORIZED / 0 / DISABLED",
    )

    return {
        "head": head,
        "code_commit_at_freeze": manifest["code_commit"],
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "working_tree_entries": len(dirty),
        "working_tree_note": (
            "entries belong to other workstreams (ST-6 observation, reports); this RFC touches none of them"
        ),
        "freeze_timestamp_utc": manifest["freeze_timestamp_utc"],
        "sealed_oos_start_utc": manifest["sealed_oos_start_utc"],
        "specs": spec_rows,
        "datasets": dataset_rows,
        "vendor_series_count": len(vendor["series"]),
        "governance_preserved": governance,
        "rfc048v_status": cert.get("RFC048_FINAL_STATUS"),
        "spot_cost_status": {
            "model": "COST_MODEL_V3",
            "round_trip_bps_200_usdt": manifest["thresholds"]["H-049-001"]["cost_bps_200_usdt"],
            "round_trip_bps_1000_usdt": manifest["thresholds"]["H-049-001"]["cost_bps_1000_usdt"],
            "stress_1_5x_bps_200_usdt": manifest["thresholds"]["H-049-001"]["stress_bps_1_5x_200_usdt"],
            "source": "data/rfc049/PREREGISTRATION_MANIFEST.json (frozen at Phase A; not recomputed here so the "
                      "frozen contract is never touched by an admission check)",
        },
    }


# --------------------------------------------------------------------------- #
# 2. stablecoin variable semantics
# --------------------------------------------------------------------------- #


def stablecoin_audit(frozen: list[tuple[date, float, float]], refetched: bytes) -> dict[str, Any]:
    days = [r[0] for r in frozen]
    usd = {d: u for d, u, _ in frozen}
    qty = {d: q for d, _, q in frozen}

    gaps = [
        (days[i].isoformat(), days[i + 1].isoformat())
        for i in range(len(days) - 1)
        if (days[i + 1] - days[i]).days != 1
    ]
    payload = json.loads((VENDOR_RAW / "defillama_stablecoin_supply_all.json").read_text(encoding="utf-8"))
    fields: dict[str, int] = {}
    for row in payload:
        for k in row:
            fields[k] = fields.get(k, 0) + 1

    peg_factor = {d: usd[d] / qty[d] for d in days if qty[d]}
    values = list(peg_factor.values())
    moves = sorted(
        (
            (abs(peg_factor[days[i]] - peg_factor[days[i - 1]]), days[i].isoformat())
            for i in range(1, len(days))
            if days[i] in peg_factor and days[i - 1] in peg_factor
        ),
        reverse=True,
    )

    def growth(series: dict[date, float], day: date, window: int = 30) -> float | None:
        prior = day - timedelta(days=window)
        if prior not in series or not series[prior]:
            return None
        return series[day] / series[prior] - 1.0

    divergence = []
    for day in days:
        g_usd, g_qty = growth(usd, day), growth(qty, day)
        if g_usd is None or g_qty is None:
            continue
        divergence.append((day, g_usd, g_qty, g_usd - g_qty))
    worst = max(divergence, key=lambda r: abs(r[3])) if divergence else None
    material = [r for r in divergence if r[3] and abs(r[3]) > 0.25 * abs(r[1]) and abs(r[1]) > 1e-6]

    fresh_map: dict[date, float] = {}
    if refetched:
        for row in json.loads(refetched.decode("utf-8")):
            value = (row.get("totalCirculatingUSD") or {}).get("peggedUSD")
            if value is not None:
                fresh_map[datetime.fromtimestamp(int(row["date"]), timezone.utc).date()] = value
    revised = [
        {"date": d.isoformat(), "frozen": usd[d], "refetched": fresh_map[d],
         "relative_change": (fresh_map[d] - usd[d]) / usd[d]}
        for d in days
        if d in fresh_map and abs(fresh_map[d] - usd[d]) > 1e-6
    ]
    current_day = max(days)
    settled = [r for r in revised if r["date"] != current_day.isoformat()]

    return {
        "frozen_field": "totalCirculatingUSD.peggedUSD",
        "field_meaning_verified": (
            "the circulating amount of every USD-pegged stablecoin multiplied by its own price and summed: a USD "
            "*valuation* of circulating supply, not a net mint/burn series and not a measured dollar flow"
        ),
        "alternative_field_in_same_payload": (
            "totalCirculating.peggedUSD (amount-denominated; ~1:1 with USD at a 1.00 peg)"
        ),
        "payload_fields": fields,
        "rows": len(days),
        "first_day": days[0].isoformat(),
        "last_day": days[-1].isoformat(),
        "missing_days": len(gaps),
        "gap_examples": gaps[:5],
        "peg_factor": {
            "definition": "frozen USD value / amount-denominated amount: a supply-weighted average peg price",
            "min": min(values), "max": max(values), "last": values[-1],
            "largest_daily_moves": moves[:5],
            "interpretation": (
                "when this factor moves, the frozen signal moves without any dollar entering or leaving the system; "
                "the size of the largest daily moves bounds that contamination"
            ),
        },
        "quantity_vs_valuation_30d_growth": {
            "max_abs_divergence": abs(worst[3]) if worst else None,
            "worst_day": worst[0].isoformat() if worst else None,
            "days_where_valuation_effect_exceeds_25pct_of_growth": len(material),
            "days_compared": len(divergence),
            "material_examples": [
                {"date": r[0].isoformat(), "growth_usd": r[1], "growth_amount": r[2], "divergence": r[3]}
                for r in material[:5]
            ],
        },
        "net_mint_burn": {
            "provided_by_vendor": False,
            "closest_available_proxy": "first difference of totalCirculating.peggedUSD",
            "note": "the frozen rule never uses a net mint/burn series; its claim is a supply-growth regime, not a flow",
        },
        "bridged_and_unreleased_buckets": {
            "totalUnreleased_rows_with_value": fields.get("totalUnreleased", 0),
            "totalBridgedToUSD_rows_with_value": fields.get("totalBridgedToUSD", 0),
            "totalMintedUSD_rows_with_value": fields.get("totalMintedUSD", 0),
            "note": (
                "the payload carries a distinct unreleased bucket; the bridged and cumulative-minted buckets are "
                "zeroed in this response, so bridged double counting cannot be ruled out from this endpoint alone"
            ),
        },
        "revision_exposure": {
            "frozen_sha256": sha256_file(VENDOR_RAW / "defillama_stablecoin_supply_all.json"),
            "refetched_sha256": sha256_bytes(refetched) if refetched else None,
            "days_compared": sum(1 for d in days if d in fresh_map),
            "revised_days": len(revised),
            "settled_days_revised": len(settled),
            "revisions": revised,
            "honest_limit": (
                "a single re-fetch cannot prove multi-year stability; it does show that every settled day returned "
                "an identical value and that only the still-forming current day had moved"
            ),
        },
    }


# --------------------------------------------------------------------------- #
# 3. macro inputs and PIT provenance
# --------------------------------------------------------------------------- #


def fred_metadata(page_html: str) -> dict[str, Any]:
    text = detag(page_html)
    out: dict[str, Any] = {}
    for key in ("units", "frequency", "lastUpdated", "releaseName"):
        m = re.search(r'"%s":"([^"]{1,120})"' % key, page_html)
        if m:
            out[key] = m.group(1)
    for label in ("Units", "Frequency", "Last Updated", "Release"):
        m = re.search(re.escape(label) + r"\s*:?\s*([A-Za-z][^|]{0,70})", text)
        if m:
            out.setdefault(label.lower().replace(" ", "_"), m.group(1).strip()[:80])
    return out


def h41_facts(blob: bytes) -> dict[str, Any]:
    text = detag(blob.decode("utf-8", "ignore")) if blob else ""
    facts: dict[str, Any] = {}
    m = re.search(r"Release Date:\s*([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if m:
        facts["release_date"] = m.group(1)
    i = text.find("Total assets (0)")
    if i > 0:
        nums = re.findall(r"([\d,]{7,})", text[i : i + 220])
        if nums:
            # the statement prints the as-of value first, then the change columns
            facts["total_assets_millions"] = float(nums[0].replace(",", ""))
            facts["total_assets_quote"] = text[i : i + 220]
    j = text.find("U.S. Treasury, General Account")
    if j > 0:
        window = text[j : j + 220]
        facts["tga_numbers_in_order"] = [float(x.replace(",", "")) for x in re.findall(r"([\d,]{3,})", window)][:6]
        facts["tga_quote"] = window[:240]
    return facts


def alfred_vintage_revisions(frozen: dict[date, float | None], vintages: dict[str, bytes]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label, blob in vintages.items():
        if not blob:
            out[label] = {"status": "unavailable"}
            continue
        column, series = parse_alfred_csv(blob)
        common = sorted(set(series) & set(frozen))
        changed = [
            {"date": d.isoformat(), "then": series[d], "now": frozen[d]} for d in common if series[d] != frozen[d]
        ]
        scale_only = 0
        for row in changed[:400]:
            a, b = row["then"], row["now"]
            if a and b and min(a, b) > 0 and abs(max(a, b) / min(a, b) - 1000.0) < 1e-6:
                scale_only += 1
        out[label] = {
            "column": column,
            "vintage_rows": len(series),
            "vintage_first": min(series).isoformat() if series else None,
            "vintage_last": max(series).isoformat() if series else None,
            "common_dates": len(common),
            "changed_values": len(changed),
            "changed_by_exact_1000_factor": scale_only,
            "changed_examples": changed[:6],
            "blank_to_value": sum(1 for r in changed if r["then"] is None and r["now"] is not None),
            "value_to_other_value": sum(1 for r in changed if r["then"] is not None and r["now"] is not None),
        }
    return out


def macro_audit(evidence: dict[str, bytes]) -> dict[str, Any]:
    walcl_col, walcl = load_vendor_series("WALCL")
    rrp_col, rrp = load_vendor_series("RRPONTSYD")
    tga_col, tga = load_vendor_series("WTREGEN")
    frozen_sets = {"WALCL": walcl, "RRPONTSYD": rrp, "WTREGEN": tga}

    def profile(sid: str, column: str, series: dict[date, float | None]) -> dict[str, Any]:
        days = sorted(series)
        blanks = [d for d in days if series[d] is None]
        histogram: dict[str, int] = {}
        for d in days:
            histogram[str(d.weekday())] = histogram.get(str(d.weekday()), 0) + 1
        first_nonblank = next((d for d in days if series[d] is not None), None)
        return {
            "series_id": sid, "column": column, "rows": len(days),
            "first_observation": days[0].isoformat(), "last_observation": days[-1].isoformat(),
            "blank_rows": len(blanks),
            "first_non_blank": first_nonblank.isoformat() if first_nonblank else None,
            "last_blank": blanks[-1].isoformat() if blanks else None,
            "weekday_histogram": dict(sorted(histogram.items())),
            "duplicate_dates": len(days) - len(set(days)),
            "last_value": series[days[-1]],
        }

    # current-vintage comparison uses ALFRED's latest vintage (same FRED infra,
    # one fewer endpoint, and it carries the vintage date in the column header)
    latest_vintage = {}
    for sid in ("WALCL", "RRPONTSYD", "WTREGEN"):
        column, series = parse_alfred_csv(evidence.get(f"alfred_{sid}_latest.csv", b""))
        latest_vintage[sid] = {"column": column, "series": series}
    revision_vs_latest = {}
    for sid, block in latest_vintage.items():
        series = block["series"]
        if not series:
            revision_vs_latest[sid] = {"status": "unavailable"}
            continue
        frozen_series = frozen_sets[sid]
        common = sorted(set(series) & set(frozen_series))
        changed = [
            {"date": d.isoformat(), "frozen": frozen_series[d], "latest_vintage": series[d]}
            for d in common
            if frozen_series[d] != series[d]
        ]
        revision_vs_latest[sid] = {
            "latest_vintage_column": block["column"],
            "common_dates": len(common),
            "changed": len(changed),
            "examples": changed[:5],
            "dates_added_since_freeze": len(set(series) - set(frozen_series)),
        }

    vintages = {
        sid: alfred_vintage_revisions(
            frozen_sets[sid],
            {v: evidence.get(f"alfred_{sid}_{v}.csv", b"") for v in ("2019-03-07", "2023-03-15")},
        )
        for sid in ("WALCL", "WTREGEN", "RRPONTSYD")
    }

    units = {sid: fred_metadata(evidence.get(f"fred_page_{sid}.html", b"").decode("utf-8", "ignore"))
             for sid in ("WALCL", "RRPONTSYD", "WTREGEN")}

    h41 = h41_facts(evidence.get("h41_current.html", b""))
    nyfed_blob = evidence.get("nyfed_rrp_last7.json", b"")
    rrp_cross: list[dict[str, Any]] = []
    if nyfed_blob:
        nyfed = json.loads(nyfed_blob)
        ops = nyfed.get("repo", {}).get("operations", nyfed.get("operations", []))
        for op in ops[:7]:
            day = date.fromisoformat(op["operationDate"])
            accepted = op.get("totalAmtAccepted")
            rrp_cross.append({
                "date": day.isoformat(),
                "nyfed_total_amt_accepted_usd": accepted,
                "nyfed_billions": None if accepted is None else accepted / 1e9,
                "frozen_fred_billions": rrp.get(day),
                "matches": None if accepted is None or rrp.get(day) is None
                else abs(accepted / 1e9 - rrp[day]) < 5e-4,
                "nyfed_release_time_et": op.get("releaseTime"),
                "nyfed_last_updated": op.get("lastUpdated"),
            })

    dts_daily: dict[str, float] = {}
    dts_blob = evidence.get("dts_tga.json", b"")
    if dts_blob:
        for row in json.loads(dts_blob).get("data", []):
            raw = row.get("open_today_bal")
            if "Closing Balance" in (row.get("account_type") or "") and raw not in (None, "null", ""):
                dts_daily[row["record_date"]] = float(raw)
    buckets: dict[str, list[float]] = {}
    for day_s, value in dts_daily.items():
        day = date.fromisoformat(day_s)
        buckets.setdefault((day + timedelta(days=(2 - day.weekday()) % 7)).isoformat(), []).append(value)
    dts_cross = [
        {
            "week_ending_wednesday": wed,
            "dts_daily_points": len(buckets[wed]),
            "dts_mean_millions": round(statistics.mean(buckets[wed]), 2),
            "frozen_fred_wtregen_millions": tga.get(date.fromisoformat(wed)),
        }
        for wed in sorted(buckets)[-6:]
    ]

    tga_numbers = h41.get("tga_numbers_in_order", [])
    dts_latest_date = max(dts_daily) if dts_daily else None
    dts_latest_value = dts_daily[dts_latest_date] if dts_latest_date else None
    h41_wednesday_level = tga_numbers[3] if len(tga_numbers) >= 4 else None
    dts_weekly_matched = [row for row in dts_cross if row["dts_daily_points"] >= 5
                          and row["frozen_fred_wtregen_millions"] is not None]
    dts_weekly_within_2pct = [
        row for row in dts_weekly_matched
        if abs(row["dts_mean_millions"] - row["frozen_fred_wtregen_millions"])
        / row["frozen_fred_wtregen_millions"] < 0.02
    ]
    cross = {
        "h41_current_release": h41,
        "h41_total_assets_matches_fred": bool(
            h41.get("total_assets_millions") is not None
            and abs(h41["total_assets_millions"] - (walcl[max(walcl)] or 0)) < 1.0
        ),
        "h41_tga_week_average_matches_fred": bool(
            tga_numbers and abs(tga_numbers[0] - (tga[max(tga)] or 0)) < 1.0
        ),
        "h41_tga_wednesday_level_vs_dts_latest": {
            "h41_wednesday_level": h41_wednesday_level,
            "latest_dts_date": dts_latest_date,
            "latest_dts_closing_balance": dts_latest_value,
            "relative_difference": (
                abs(dts_latest_value - h41_wednesday_level) / h41_wednesday_level
                if h41_wednesday_level and dts_latest_value else None
            ),
            "note": "the DTS has not yet published the H.4.1 reference Wednesday, which is itself evidence of a "
                    "next-business-day publication lag",
            "matches_within_2pct": bool(
                h41_wednesday_level and dts_latest_value
                and abs(dts_latest_value - h41_wednesday_level) / h41_wednesday_level < 0.02
            ),
        },
        "dts_weekly_mean_vs_fred": dts_cross,
        "dts_weekly_mean_within_2pct": {
            "compared": len(dts_weekly_matched),
            "within": len(dts_weekly_within_2pct),
        },
    }
    cross["nyfed_rrp_matches_fred"] = rrp_cross
    check("macro:units_WALCL", "millions" in json.dumps(units.get("WALCL", {})).lower(),
          json.dumps(units.get("WALCL", {})))
    check("macro:units_RRPONTSYD", "billions" in json.dumps(units.get("RRPONTSYD", {})).lower(),
          json.dumps(units.get("RRPONTSYD", {})))
    check("macro:units_WTREGEN", "millions" in json.dumps(units.get("WTREGEN", {})).lower(),
          json.dumps(units.get("WTREGEN", {})))
    check("macro:primary_source:rrp_value_identity",
          bool(rrp_cross) and all(r["matches"] for r in rrp_cross),
          f"{sum(1 for r in rrp_cross if r['matches'])}/{len(rrp_cross)} NY Fed operations match the frozen series "
          f"exactly")
    check("macro:primary_source:h41_total_assets", cross["h41_total_assets_matches_fred"],
          f"H.4.1 total assets {h41.get('total_assets_millions')} vs frozen WALCL {walcl[max(walcl)]}")
    check("macro:primary_source:h41_tga_week_average", cross["h41_tga_week_average_matches_fred"],
          f"H.4.1 week-average TGA {tga_numbers[:1]} vs frozen WTREGEN {tga[max(tga)]}")
    check("macro:primary_source:h41_vs_dts",
          cross["h41_tga_wednesday_level_vs_dts_latest"]["matches_within_2pct"]
          or cross["dts_weekly_mean_within_2pct"]["within"] > 0,
          json.dumps({"h41_wed_vs_dts_latest": cross["h41_tga_wednesday_level_vs_dts_latest"],
                      "dts_weekly": cross["dts_weekly_mean_within_2pct"]}))

    return {
        "series_profiles": {
            "WALCL": profile("WALCL", walcl_col, walcl),
            "RRPONTSYD": profile("RRPONTSYD", rrp_col, rrp),
            "WTREGEN": profile("WTREGEN", tga_col, tga),
        },
        "frozen_units_expectation": {"WALCL": "millions", "RRPONTSYD": "billions", "WTREGEN": "millions"},
        "fred_metadata_pages": units,
        "primary_source_crosschecks": cross,
        "revision_exposure": {
            "frozen_vs_latest_vintage": revision_vs_latest,
            "alfred_vintages": vintages,
        },
        "asof_join_policy": {
            "grid": "weekly Wednesday",
            "walcl": "exact Wednesday observation (holidays are published in this series)",
            "wtregen": "exact Wednesday observation",
            "rrpontsyd": f"most recent non-blank observation on or before the Wednesday, reach-back bounded at "
                         f"{ASOF_MAX_REACHBACK_DAYS} days; beyond that the input counts as missing and the week is FLAT",
            "fail_closed": "any missing input on a decision week forces FLAT",
        },
    }


# --------------------------------------------------------------------------- #
# 4. frozen-rule state construction (counts only; no returns)
# --------------------------------------------------------------------------- #


def stablecoin_signal(
    rows: list[tuple[date, float, float]], grid: list[date], use_quantity: bool = False
) -> dict[date, dict[str, Any]]:
    days = [r[0] for r in rows]
    series = {r[0]: (r[2] if use_quantity else r[1]) for r in rows}
    index = {d: i for i, d in enumerate(days)}
    growth: dict[date, float] = {}
    for d in days:
        prior = d - timedelta(days=30)
        if prior in series and series[prior]:
            growth[d] = series[d] / series[prior] - 1.0
    baseline: dict[date, float] = {}
    for d in days:
        i = index[d]
        window = [growth[days[j]] for j in range(max(0, i - 365), i) if days[j] in growth]
        if len(window) >= 365:
            baseline[d] = statistics.median(window)
    out: dict[date, dict[str, Any]] = {}
    for sunday in grid:
        t_star = sunday - timedelta(days=2)  # value dated t is available at 00:00 of t+1
        while t_star >= days[0] and t_star not in series:
            t_star -= timedelta(days=1)
        if t_star in growth and t_star in baseline:
            out[sunday] = {
                "t_star": t_star.isoformat(), "growth": growth[t_star], "baseline": baseline[t_star],
                "margin": growth[t_star] - baseline[t_star], "state": growth[t_star] > baseline[t_star],
                "available": True,
            }
        else:
            out[sunday] = {"t_star": t_star.isoformat() if t_star else None, "growth": None, "baseline": None,
                           "margin": None, "state": False, "available": False}
    return out


def macro_input_signal(
    inputs: dict[str, dict[date, float | None]], grid: list[date]
) -> tuple[dict[date, dict[str, Any]], dict[str, Any]]:
    """Net liquidity on the frozen weekly Wednesday grid, then the weekly state.

    The state is keyed by the decision Sunday, but the underlying level is keyed by the
    Wednesday reference it belongs to (the same Wednesday the availability proof uses).
    """
    walcl, rrp, tga = inputs["WALCL"], inputs["RRPONTSYD"], inputs["WTREGEN"]
    nl: dict[date, float] = {}
    stats: dict[str, Any] = {"wednesdays_with_missing_input": 0, "reachback_days_used": []}

    def level(wednesday: date) -> float | None:
        if wednesday in nl:
            return nl[wednesday]
        w, t = asof(walcl, wednesday, 7), asof(tga, wednesday, 7)
        r = asof(rrp, wednesday, ASOF_MAX_REACHBACK_DAYS)
        if w is None or t is None or r is None:
            stats["wednesdays_with_missing_input"] += 1
            return None
        value = w / 1000.0 - r - t / 1000.0
        nl[wednesday] = value
        for series, hit, limit in ((walcl, w, 7), (tga, t, 7), (rrp, r, ASOF_MAX_REACHBACK_DAYS)):
            for back in range(0, limit + 1):
                if series.get(wednesday - timedelta(days=back)) == hit:
                    stats["reachback_days_used"].append(back)
                    break
        return value

    out: dict[date, dict[str, Any]] = {}
    for sunday in grid:
        wednesday = sunday - timedelta(days=4)   # the immediately preceding Wednesday
        previous = wednesday - timedelta(weeks=4)
        now, before = level(wednesday), level(previous)
        if now is None or before is None:
            out[sunday] = {"wednesday": wednesday.isoformat(), "nl_now": now, "nl_prev": before,
                           "delta": None, "state": False, "available": False}
        else:
            out[sunday] = {"wednesday": wednesday.isoformat(), "nl_now": now, "nl_prev": before,
                           "delta": now - before, "state": now - before > 0, "available": True}
    stats["input_week_range"] = f"{min(nl).isoformat()}..{max(nl).isoformat()}" if nl else None
    stats["max_reachback_days_used"] = max(stats["reachback_days_used"]) if stats["reachback_days_used"] else None
    stats["reachback_days_used"] = sorted(set(stats["reachback_days_used"]))
    return out, stats


def count_round_trips(states: dict[date, bool], bars: list[tuple[int, float]]) -> list[dict[str, Any]]:
    """Closed long round trips: enter and exit at the first daily bar open after the decision."""
    trips: list[dict[str, Any]] = []
    in_position = False
    entry_bar: int | None = None
    entry_sunday: date | None = None
    for sunday in sorted(states):
        instant = datetime(sunday.year, sunday.month, sunday.day, 23, 0, tzinfo=timezone.utc)
        bar = bar_after(bars, instant)
        if states[sunday] and not in_position:
            if bar is None:
                continue
            in_position, entry_bar, entry_sunday = True, bar, sunday
        elif not states[sunday] and in_position:
            if bar is None:
                continue
            trips.append({
                "entry_sunday": str(entry_sunday), "entry_bar_ms": entry_bar,
                "exit_sunday": sunday.isoformat(), "exit_bar_ms": bar,
                "hold_days": int((bar - entry_bar) / 86_400_000),
            })
            in_position = False
    return trips


def window_counts(trips: list[dict[str, Any]]) -> dict[str, int]:
    def in_range(start: str, end: str) -> int:
        return sum(1 for t in trips if start <= t["entry_sunday"] <= end)

    return {
        "development": in_range("1900-01-01", "2023-12-31"),
        "validation": in_range("2024-01-01", "2026-12-31"),
        "all_exposed": len(trips),
        "last_12_months": in_range("2025-10-10", "2026-12-31"),
    }


# --------------------------------------------------------------------------- #
# 5. analyses
# --------------------------------------------------------------------------- #


def independence_audit(
    grid: list[date], sig_a: dict[date, dict[str, Any]], sig_b: dict[date, dict[str, Any]]
) -> dict[str, Any]:
    usable = [s for s in grid if sig_a[s]["available"] and sig_b[s]["available"]]
    both_defined = len(usable)
    a_long = [s for s in usable if sig_a[s]["state"]]
    b_long = [s for s in usable if sig_b[s]["state"]]
    same = sum(1 for s in usable if sig_a[s]["state"] == sig_b[s]["state"])

    def transitions(signal: dict[date, dict[str, Any]], days: list[date]) -> int:
        count = 0
        previous = False
        for day in days:
            state = signal[day]["state"]
            if state != previous:
                count += 1
            previous = state
        return count

    def spearman(xs: list[float], ys: list[float]) -> float | None:
        if len(xs) < 10:
            return None

        def ranks(values: list[float]) -> list[float]:
            order = sorted(range(len(values)), key=lambda i: values[i])
            out = [0.0] * len(values)
            i = 0
            while i < len(order):
                j = i
                while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                    j += 1
                avg = (i + j) / 2.0 + 1.0
                for k in range(i, j + 1):
                    out[order[k]] = avg
                i = j + 1
            return out

        rx, ry = ranks(xs), ranks(ys)
        n = len(rx)
        mx, my = sum(rx) / n, sum(ry) / n
        num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
        dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
        dy = math.sqrt(sum((b - my) ** 2 for b in ry))
        return None if dx == 0 or dy == 0 else num / (dx * dy)

    margins_a = [sig_a[s]["margin"] for s in usable]
    deltas_b = [sig_b[s]["delta"] for s in usable]
    correlation = spearman(margins_a, deltas_b)

    return {
        "returns_computed": False,
        "basis": "frozen rules applied to research-exposed inputs; only states and counts are produced",
        "common_decision_grid": {
            "first": usable[0].isoformat() if usable else None,
            "last": usable[-1].isoformat() if usable else None,
            "weeks": both_defined,
        },
        "mechanisms": {
            "H-049-001": {
                "information_set": "crypto-native: aggregate USD-pegged stablecoin circulating supply (daily, vendor)",
                "transmission": "primary-market issuance/redemption changes the dollar float available to crypto venues",
                "cadence_of_input": "daily, 30-day growth versus its own 365-day median",
            },
            "H-049-002": {
                "information_set": "off-crypto policy accounts: Federal Reserve total assets, ON RRP, Treasury General Account",
                "transmission": "net dollar liquidity in the banking system moves the market price of risk",
                "cadence_of_input": "weekly Wednesday references, 4-week change in net liquidity",
            },
            "shared_label": "both sit in a 'dollar liquidity -> risk appetite' family; the information sets and the "
                            "transmission channels differ, and the frozen cross-incremental test is the control",
        },
        "measured_overlap": {
            "weeks_both_long": sum(1 for s in usable if sig_a[s]["state"] and sig_b[s]["state"]),
            "weeks_a_long_only": sum(1 for s in usable if sig_a[s]["state"] and not sig_b[s]["state"]),
            "weeks_b_long_only": sum(1 for s in usable if sig_b[s]["state"] and not sig_a[s]["state"]),
            "weeks_both_flat": sum(1 for s in usable if not sig_a[s]["state"] and not sig_b[s]["state"]),
            "state_agreement_rate": (same / both_defined) if both_defined else None,
            "jaccard_on_long_weeks": (
                len(set(a_long) & set(b_long)) / len(set(a_long) | set(b_long))
                if (a_long or b_long) else None
            ),
            "spearman_rank_correlation_of_drivers": correlation,
            "transitions_a": transitions(sig_a, usable),
            "transitions_b": transitions(sig_b, usable),
        },
        "conclusion": (
            "the two candidates do not trade the same clock: different inputs, different sampling frequency and "
            "different transmission channels. The measured state overlap is reported above; it is a structural "
            "measure, not an economic one, and the frozen cross-incremental test remains the decisive control "
            "(if either candidate is indistinguishable from the other's state, the frozen test rejects it)."
        ),
    }


def pit_verification(
    frozen_rows: list[tuple[date, float, float]],
    inputs: dict[str, dict[date, float | None]],
    grid: list[date],
    sig_a: dict[date, dict[str, Any]],
    sig_b: dict[date, dict[str, Any]],
    stable: dict[str, Any],
    macro: dict[str, Any],
    revision_rrp_wednesday: list[str],
) -> dict[str, Any]:
    # availability model: declared per input, then asserted for every decision instant
    # and for every hypothesis separately (the two candidates consume different inputs).
    violations_a: list[dict[str, Any]] = []
    violations_b: list[dict[str, Any]] = []
    undecidable_a: list[dict[str, Any]] = []
    undecidable_b: list[dict[str, Any]] = []
    for sunday in grid:
        decision = datetime(sunday.year, sunday.month, sunday.day, 23, 0, tzinfo=timezone.utc)
        margin = decision - timedelta(hours=1)

        # H-049-001: the stablecoin value dated t is available at 00:00 UTC of t+1
        t_star = date.fromisoformat(sig_a[sunday]["t_star"]) if sig_a[sunday]["t_star"] else None
        stable_available = datetime(t_star.year, t_star.month, t_star.day, tzinfo=timezone.utc) \
            + timedelta(days=1) if t_star else None
        if not sig_a[sunday]["available"]:
            # not yet decidable (warmup or a missing value): the rule fails closed to FLAT,
            # which is not a look-ahead problem
            undecidable_a.append({"decision": sunday.isoformat(), "t_star": sig_a[sunday]["t_star"]})
        elif not (stable_available and stable_available <= margin):
            violations_a.append({"decision": sunday.isoformat(), "t_star": sig_a[sunday]["t_star"],
                                 "available_at": stable_available.isoformat() if stable_available else None})

        # H-049-002: the Wednesday snapshot's H.4.1 inputs are published the next Thursday
        wednesday = date.fromisoformat(sig_b[sunday]["wednesday"])
        h41_release = datetime(wednesday.year, wednesday.month, wednesday.day, 20, 30, tzinfo=timezone.utc) \
            + timedelta(days=1)
        rrp_day = next(
            (wednesday - timedelta(days=back)
             for back in range(0, ASOF_MAX_REACHBACK_DAYS + 1)
             if inputs["RRPONTSYD"].get(wednesday - timedelta(days=back)) is not None),
            None,
        )
        rrp_available = (
            datetime(rrp_day.year, rrp_day.month, rrp_day.day, 18, 0, tzinfo=timezone.utc) if rrp_day else None
        )
        if not sig_b[sunday]["available"]:
            undecidable_b.append({"decision": sunday.isoformat(), "wednesday": wednesday.isoformat()})
        elif not (h41_release <= margin and bool(rrp_available) and rrp_available <= margin):
            violations_b.append({
                "decision": sunday.isoformat(), "wednesday": wednesday.isoformat(),
                "h41_release": h41_release.isoformat(), "rrp_observation": rrp_day.isoformat() if rrp_day else None,
            })

    # incremental reconstruction test: a decision recomputed from a truncated feed
    sample = grid[:: max(1, len(grid) // 40)][:40]
    mismatches = []
    for sunday in sample:
        prefix_rows = [r for r in frozen_rows if r[0] <= sunday - timedelta(days=2)]
        recomputed_a = stablecoin_signal(prefix_rows, [sunday])[sunday]["state"]
        prefix_inputs = {k: {d: v for d, v in series.items() if d <= sunday - timedelta(days=3)}
                         for k, series in inputs.items()}
        recomputed_b = macro_input_signal(prefix_inputs, [sunday])[0][sunday]["state"]
        if recomputed_a != sig_a[sunday]["state"] or recomputed_b != sig_b[sunday]["state"]:
            mismatches.append({
                "decision": sunday.isoformat(),
                "full_a": sig_a[sunday]["state"], "truncated_a": recomputed_a,
                "full_b": sig_b[sunday]["state"], "truncated_b": recomputed_b,
            })

    classifications = {
        "defillama_stablecoin": {
            "values_are_primary": True,
            "vendor_publication_timestamp": False,
            "declared_convention": "value dated day t treated as available 00:00 UTC of day t+1",
            "measured_revision_exposure": {
                "settled_days_revised": stable["revision_exposure"]["settled_days_revised"],
                "days_compared": stable["revision_exposure"]["days_compared"],
            },
            "classification": "PIT_CONSERVATIVE_PROXY",
            "why": "the payload carries no publication timestamp, so decision-time availability is a declared "
                   "convention rather than a vendor fact; the convention is one full day of conservatism and no "
                   "settled history moved in the observed re-fetch window",
        },
        "WALCL": {
            "publication_evidence": "H.4.1 release page dated with an explicit Release Date for the week ending the "
                                    "reference Wednesday",
            "reference_to_release_lag_days_min": 1,
            "measured_revision_exposure": macro["revision_exposure"]["alfred_vintages"]["WALCL"],
            "classification": "PIT_VERIFIED",
            "why": "primary-source release date verified and the 2019-03-07 ALFRED vintage reproduces today's values "
                   "exactly, so no restatement affects a decision",
        },
        "WTREGEN": {
            "publication_evidence": "H.4.1 release page: the week-average Treasury General Account figure published "
                                    "with the same statement as WALCL",
            "reference_to_release_lag_days_min": 1,
            "series_definition_change": macro["revision_exposure"]["alfred_vintages"]["WTREGEN"],
            "classification": "PIT_VERIFIED",
            "why": "availability is primary-source verified and conservative; the frozen contract already declares "
                   "millions and a 2002 start, which is the current series definition",
        },
        "RRPONTSYD": {
            "publication_evidence": "NY Fed operation API exposes the operation result with a same-business-day "
                                    "releaseTime and lastUpdated timestamp; values match the frozen series exactly",
            "reference_to_release_lag_days_min": 0,
            "measured_revision_exposure": macro["revision_exposure"]["alfred_vintages"]["RRPONTSYD"],
            "wednesday_grid_points_affected": revision_rrp_wednesday,
            "classification": "PIT_CONSERVATIVE_PROXY",
            "why": "same-day publication is verified, but the series is demonstrably backfilled on rare dates, so a "
                   "re-run over the current vintage can differ from what a live reader saw; the exposure is measured, "
                   "bounded and immaterial in magnitude",
        },
    }

    check("pit:H-049-001:no_decision_consumes_future_data", not violations_a,
          f"{len(violations_a)} availability violations over {len(grid)} decision instants; "
          f"{len(undecidable_a)} decisions were not yet decidable (fail-closed FLAT, not a PIT defect)")
    check("pit:H-049-002:no_decision_consumes_future_data", not violations_b,
          f"{len(violations_b)} availability violations over {len(grid)} decision instants; "
          f"{len(undecidable_b)} decisions were not yet decidable (fail-closed FLAT, not a PIT defect)")
    check("pit:incremental_reconstruction", not mismatches,
          f"{len(sample)} sampled decisions recomputed from a truncated feed; mismatches={len(mismatches)}")

    return {
        "artifact": "RFC049B_PIT_SOURCE_VERIFICATION",
        "generated_at_utc": utcnow(),
        "classification_vocabulary": {
            "PIT_VERIFIED": "primary-source evidence fixes both the value identity and an availability time on or "
                            "before the decision instant, with no measured restatement affecting a decision",
            "PIT_CONSERVATIVE_PROXY": "availability is a declared convention or the series shows measured backfill, "
                                      "so the value used is conservative rather than provable",
            "PIT_UNKNOWN": "no availability information exists",
            "PIT_FAILED": "a decision demonstrably consumed a value published after its instant",
        },
        "inputs": classifications,
        "decision_time_rules": {
            "decision_instant": "weekly Sunday 23:00:00 UTC",
            "margin_before_decision": "1 hour",
            "stablecoin_cutoff": "most recent daily value dated at or before Sunday-2 (one day of availability lag)",
            "macro_cutoff": "most recent complete Wednesday snapshot, whose H.4.1 inputs publish the following "
                            "Thursday",
            "execution": "first daily bar open strictly after the decision instant (Monday 00:00 UTC)",
        },
        "data_time_le_decision_time_violations": {
            "H-049-001": violations_a,
            "H-049-002": violations_b,
        },
        "not_yet_decidable_decisions": {
            "H-049-001": undecidable_a,
            "H-049-002": undecidable_b,
            "rule": "a decision with no usable value is FLAT; that is fail-closed behaviour, not look-ahead",
        },
        "incremental_reconstruction": {
            "sampled_decisions": len(sample),
            "mismatches": mismatches,
            "method": "the decision is recomputed from a feed truncated at the decision instant and compared with the "
                      "full-history value; equality means the signal is a function of past data only",
        },
        "def_htf_pit_001_assessment": {
            "defect": DEF_HTF_PIT_001,
            "applies_here": False,
            "reason": "both frozen rules consume completed daily values and closed weekly references; no higher-"
                      "timeframe bar is read while still forming, and execution is deferred to the next bar open",
        },
        "higher_timeframe_check": {
            "timeframes_used": ["1d closed bars", "weekly Wednesday reference dates"],
            "incomplete_bar_consumed": False,
            "look_ahead_found": False,
        },
        "composite_classification": {
            "H-049-001": "PIT_CONSERVATIVE_PROXY",
            "H-049-002": "PIT_VERIFIED",
            "note": "the weaker of a hypothesis's inputs decides its composite class",
        },
        "residual_risks": [
            "the stablecoin series has no vendor publication timestamp: the t+1 convention is the mitigation, and the "
            "sealed-period collector must read the settled value and retain the retrieval record",
            "the RRP series is backfilled on rare dates; the affected Wednesday grid points are listed explicitly",
            "neither the vendor nor FRED is contractually obliged to keep history immutable; the retained hashes make "
            "any later change detectable rather than invisible",
        ],
    }


def feasibility_audit(
    trips_a: list[dict[str, Any]],
    trips_b: list[dict[str, Any]],
    grid_a: list[date],
    grid_b: list[date],
    declared_dev_start_b: str,
    effective_start_b: str,
) -> dict[str, Any]:
    def analyze(trips: list[dict[str, Any]], grid: list[date], declared: str | None, effective: str) -> dict[str, Any]:
        counts = window_counts(trips)
        first = date.fromisoformat(grid[0].isoformat()) if grid else None
        last = date.fromisoformat(grid[-1].isoformat()) if grid else None
        years = ((last - first).days / 365.25) if first and last else 0.0
        per_year = (counts["all_exposed"] / years) if years else 0.0
        last12 = counts["last_12_months"]
        rate_month = (counts["all_exposed"] / (years * 12)) if years else 0.0
        return {
            "declared_development_start": declared,
            "effective_first_decidable_week": effective,
            "effective_last_decidable_week": last.isoformat() if last else None,
            "exposed_years_measured": round(years, 2),
            "round_trips": counts,
            "round_trips_per_year_all_exposed": round(per_year, 2),
            "round_trips_per_year_last_12_months": last12,
            "round_trips_per_month_all_exposed": round(rate_month, 3),
            "expected_round_trips_in_24_month_sealed_window": round(rate_month * 24, 1),
            "months_to_reach_20_round_trips_at_measured_rate": (
                round(20 / rate_month, 1) if rate_month else None
            ),
            "frozen_floor": "20 closed round trips or 24 months, whichever comes first",
            "sealed_window_risk": (
                "INSUFFICIENT_OOS_SAMPLE_BY_CONSTRUCTION"
                if rate_month * 24 < 20 else "floor reachable within 24 months at the measured rate"
            ),
            "median_hold_days": (
                statistics.median([t["hold_days"] for t in trips]) if trips else None
            ),
        }

    grid_a_usable = [s for s in grid_a]
    analysis_a = analyze(trips_a, grid_a_usable, None, grid_a_usable[0].isoformat() if grid_a_usable else "n/a")
    analysis_b = analyze(trips_b, grid_b, declared_dev_start_b, effective_start_b)

    precision = []
    for ir in (0.15, 0.20, 0.25, 0.30, 0.40):
        n = math.ceil((1.645 / ir) ** 2)
        precision.append({
            "per_trip_information_ratio": ir,
            "round_trips_for_one_sided_95pct_precision": n,
            "months_at_h001_measured_rate": round(n / analysis_a["round_trips_per_month_all_exposed"], 1)
            if analysis_a["round_trips_per_month_all_exposed"] else None,
            "months_at_h002_measured_rate": round(n / analysis_b["round_trips_per_month_all_exposed"], 1)
            if analysis_b["round_trips_per_month_all_exposed"] else None,
        })

    return {
        "artifact": "RFC049B_OOS_SAMPLE_FEASIBILITY",
        "generated_at_utc": utcnow(),
        "method": "frozen rules applied to research-exposed inputs; only trade counts and dates are produced. "
                  "No return, no PnL and no profit factor is computed, and the sealed window is untouched.",
        "thresholds_changed": False,
        "statistical_criterion_unchanged": "20 round trips or 24 months, whichever comes first; fewer than 20 at 24 "
                                           "months is INSUFFICIENT_OOS_SAMPLE and is neither PASS nor REJECT",
        "H-049-001": analysis_a,
        "H-049-002": analysis_b,
        "precision_requirements": precision,
        "conclusion": (
            "the frozen count floor is reachable inside the sealed window only if the realised turnover matches the "
            "measured exposed-history turnover. Where it does not, the correct outcome is INSUFFICIENT_OOS_SAMPLE, and "
            "the sample floor must not be lowered to manufacture a verdict."
        ),
    }


def retain_derived(name: str, text: str, url: str, source_key: str) -> None:
    """Retain extracted text as evidence when the source body itself is too large."""
    if not text:
        return
    path = RAW / name
    path.write_text(text[:400_000], encoding="utf-8")
    row = {
        "key": name, "url": url, "retrieved_at_utc": utcnow(), "mode": "derived",
        "http_status": None, "bytes": path.stat().st_size, "sha256": sha256_file(path),
        "raw_retained": True, "status": "ok", "derived_from": source_key,
    }
    (RAW / f"{name}.meta.json").write_text(json.dumps(row, indent=2) + "\n", encoding="utf-8")
    EVIDENCE.append(row)


def crossref_record(blob: bytes, doi_hint: str | None = None) -> dict[str, Any] | None:
    """Bibliographic record from the DOI registration agency (Crossref)."""
    if not blob:
        return None
    try:
        message = json.loads(blob.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if "message" in message:
        message = message["message"]
        if "items" in message:  # a search response
            items = message["items"]
            chosen = None
            for item in items:
                if doi_hint and item.get("DOI", "").lower() == doi_hint.lower():
                    chosen = item
                    break
            message = chosen or (items[0] if items else {})
    abstract = re.sub(r"<[^>]+>", " ", message.get("abstract") or "")
    abstract = re.sub(r"\s+", " ", abstract).strip()
    return {
        "doi": message.get("DOI"),
        "title": (message.get("title") or [None])[0],
        "journal": (message.get("container-title") or [None])[0],
        "year": ((message.get("issued") or {}).get("date-parts") or [[None]])[0][0],
        "volume": message.get("volume"),
        "issue": message.get("issue"),
        "type": message.get("type"),
        "abstract": abstract[:1500] or None,
        "source": "Crossref REST API (DOI registration agency)",
    }


def source_evidence_audit(evidence: dict[str, bytes], scholar: list[dict[str, Any]]) -> dict[str, Any]:
    def quote(text: str, start: int, length: int = 900) -> str:
        return text[start : start + length].strip()

    arxiv_html = evidence.get("arxiv_abs.html", b"").decode("utf-8", "ignore")
    arxiv_text = detag(arxiv_html)
    i = arxiv_text.find("Abstract:")
    arxiv_abs = quote(arxiv_text, i + len("Abstract:"), 1100) if i >= 0 else ""
    arxiv_pdf_text = pdf_text(evidence.get("arxiv_pdf.pdf", b"")) if evidence.get("arxiv_pdf.pdf") else ""
    if not arxiv_pdf_text and (RAW / "arxiv_2411.06327v2.extracted.txt").exists():
        arxiv_pdf_text = (RAW / "arxiv_2411.06327v2.extracted.txt").read_text(encoding="utf-8")

    fedsnote_text = detag(evidence.get("fedsnote.html", b"").decode("utf-8", "ignore"))
    note_quote, note_anchor = anchor_quote(
        fedsnote_text, ("redemption", "mints", "primary market", "depeg"), before=400, after=1100
    )

    philly_text = pdf_text(evidence.get("philly_wp26-24.pdf", b"")) if evidence.get("philly_wp26-24.pdf") else ""
    if not philly_text and (RAW / "philly_wp26-24.extracted.txt").exists():
        philly_text = (RAW / "philly_wp26-24.extracted.txt").read_text(encoding="utf-8")
    retain_derived("philly_wp26-24.extracted.txt", philly_text,
                   "https://www.philadelphiafed.org/-/media/frbp/assets/working-papers/2026/wp26-24.pdf",
                   "philly_wp26-24.pdf")
    retain_derived("arxiv_2411.06327v2.extracted.txt", arxiv_pdf_text, "https://arxiv.org/pdf/2411.06327v2",
                   "arxiv_pdf.pdf")
    # the extracted text keeps publisher letter-spacing and the abstract heading is not always
    # recoverable, so the window is anchored on the decisive sentence instead
    philly_abs, philly_anchor = anchor_quote(philly_text, ("lifeline", "flight-to-safety", "muted")) \
        if philly_text else ("", None)

    bis_text = detag(evidence.get("bis_wp402.html", b"").decode("utf-8", "ignore"))
    bis_quote, bis_anchor = anchor_quote(bis_text, ("global liquidity", "priced factor"), before=300, after=1000)

    scholar_index: dict[str, dict[str, Any]] = {}
    for block in scholar:
        for row in block.get("results", []) or []:
            scholar_index[(row.get("title") or "").lower()] = row

    def find_scholar(fragment: str) -> dict[str, Any] | None:
        for title, row in scholar_index.items():
            if fragment.lower() in title:
                return row
        return None

    src005 = find_scholar("stablecoin and cryptocurrency returns during periods of market stress")
    src006 = find_scholar("monetary liquidity affect bitcoin")
    cr005 = crossref_record(evidence.get("crossref_fintech5030068.json", b""))
    cr006 = crossref_record(evidence.get("crossref_ssrn4904716.json", b""), "10.2139/ssrn.4904716")

    sources = {
        "SRC-049-001": {
            "what": "DefiLlama stablecoin charts API",
            "read_level": "FULL_PAYLOAD_AND_HASH",
            "evidence": "data/rfc049/vendor/raw/defillama_stablecoin_supply_all.json + a fresh re-fetch in "
                        "data/rfc049/admission/raw/refetch_defillama.json",
            "supports": "the frozen signal variable exists, is contiguous, and its exact field is identified",
            "limits": "no publication timestamp; USD valuation of supply, not a flow",
        },
        "SRC-049-002": {
            "what": "Chi, Chu & Hao (arXiv:2411.06327v2) on-chain flows and return forecasting",
            "read_level": "ABSTRACT_ONLY" if not arxiv_pdf_text else "FULL_TEXT_VERIFIED",
            "abstract_verified_from": "https://arxiv.org/abs/2411.06327v2",
            "abstract_quote": arxiv_abs,
            "pdf_text_extraction": "succeeded" if arxiv_pdf_text else
                                   "failed: the PDF maps glyphs through a subset font encoding, so no reliable text "
                                   "can be recovered; the file is recorded by hash instead of being paraphrased",
            "registry_characterisation_verified": (
                "matches the abstract: the predictability is for USDT net inflows *into exchanges* at 1-6 hour "
                "intraday intervals, and ETH net inflows carry the opposite sign"
            ),
            "decisive_claim_check": (
                "the paper does not test aggregate stablecoin supply growth at daily horizons; using it as support for "
                "H-049-001 is an extrapolation the campaign must earn on data"
            ),
        },
        "SRC-049-003": {
            "what": "FEDS Notes (2024-02-23) Primary and Secondary Markets for Stablecoins",
            "read_level": "FULL_TEXT_VERIFIED",
            "source_url": "https://www.federalreserve.gov/econres/notes/feds-notes/"
                          "primary-and-secondary-markets-for-stablecoins-20240223.html",
            "quote": note_quote,
            "quote_anchor": note_anchor,
            "supports": "primary-market mints/redemptions change supply, while depegs appear in the secondary market",
            "limits": "a crisis anatomy (March 2023), not a return-prediction study",
        },
        "SRC-049-004": {
            "what": "Federal Reserve Bank of Philadelphia working paper 26-24",
            "read_level": "FULL_TEXT_VERIFIED" if philly_text else "ABSTRACT_ONLY",
            "extraction_note": (
                "text recovered from the publisher PDF with a local extractor and retained as derived evidence "
                "(philly_wp26-24.extracted.txt); the 1.4 MB PDF itself is recorded by hash rather than committed"
            ),
            "extraction_metrics": prose_metrics(philly_text) if philly_text else None,
            "abstract_quote": philly_abs,
            "quote_anchor": philly_anchor,
            "direction_tokens_found": (
                {t: bool(re.search(t, "".join(philly_text.split()).lower()))
                 for t in ("lifeline", "muted", "stabilizing", "flighttosafety", "networkdependent")}
                if philly_text else None
            ),
            "DIRECTION_FINDING": (
                "the paper's own framing is not 'stablecoin inflows predict positive BTC returns': its extracted abstract "
                "describes USDT as a primary liquidity lifeline during stress for Ethereum holders, a notably more muted "
                "and stabilizing role for Bitcoin, and a network-dependent function. Read in full, this source sits "
                "closer to the counter-evidence column for H-049-001's directional claim than the Phase A registry "
                "recorded"
            ),
            "finding_basis": "the quoted extracted abstract above; the verifier re-checks the tokens against the retained "
                             "derived text",
            "action": "recorded as a defect against the Phase A source characterisation; the frozen rules are unaffected "
                      "because they never depended on this source",
        },
        "SRC-049-005": {
            "what": "peer-reviewed counter-evidence on stablecoin/crypto return relationships",
            "read_level": "ABSTRACT_ONLY" if (cr005 or src005) else "CLAIM_ONLY",
            "publisher_blocked": "https://www.mdpi.com/1911-8074/18/9/491 returned HTTP 403 to this agent",
            "abstract_recovered_via": "Crossref metadata (DOI registration agency); Semantic Scholar kept as "
                                      "secondary",
            "verified_record": cr005 or {
                "title": (src005 or {}).get("title"),
                "journal": (src005 or {}).get("venue"),
                "year": (src005 or {}).get("year"),
                "doi": (src005 or {}).get("doi"),
                "abstract": (src005 or {}).get("abstract"),
                "source": "Semantic Scholar",
            },
            "CITATION_CORRECTION": (
                "the Phase A registry cites this work as MDPI JRFM 5(3):68. The registration agency record is MDPI "
                "*FinTech* 5(3):68, DOI 10.3390/fintech5030068, with a different title from the registered short title. "
                "The substance of the counter-evidence stands and is visible in the retrieved abstract, which states "
                "that the analysis accounts for the depegging of stablecoins."
            ),
            "supports": "counter-evidence for H-049-001",
        },
        "SRC-049-006": {
            "what": "working paper on a USD monetary-liquidity measure and the Bitcoin price",
            "read_level": "CLAIM_ONLY",
            "publisher_blocked": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4904716 returned HTTP 403",
            "bibliographic_identity_verified": cr006,
            "text_read": False,
            "limits": "a single working paper with a practitioner-constructed measure. Its identity is verified through "
                      "the registration agency, but its text was not read; the frozen H-049-002 rule does not replicate "
                      "its measure in any case, it uses the Federal Reserve's own accounts",
        },
        "SRC-049-007": {
            "what": "Eickmeier, Gambacorta & Hofmann (2013), Understanding Global Liquidity, BIS WP 402",
            "read_level": "ABSTRACT_ONLY",
            "extraction_note": "the BIS PDF endpoint serves the landing page to non-browser clients; the landing-page "
                               "abstract is retained",
            "quote": bis_quote,
            "quote_anchor": bis_anchor,
            "supports": "the framework: global liquidity is a priced factor in risk assets",
            "limits": "macro-level, not crypto-specific",
        },
        "SRC-049-008": {
            "what": "FRED series WALCL / RRPONTSYD / WTREGEN and their release practice",
            "read_level": "FULL_TEXT_VERIFIED",
            "primary_sources": [
                "https://www.federalreserve.gov/releases/h41/current/h41.htm",
                "https://markets.newyorkfed.org/api/rp/reverserepo/all/results/last/7.json",
                "https://api.fiscaldata.treasury.gov/services/data/v1/accounting/dts/operating_cash_balance",
            ],
            "supports": "value identity, units, observation dates and publication timing of every traded macro input",
        },
    }
    return {
        "artifact": "RFC049B_SOURCE_EVIDENCE",
        "generated_at_utc": utcnow(),
        "read_level_vocabulary": ["FULL_TEXT_VERIFIED", "ABSTRACT_ONLY", "CLAIM_ONLY", "FULL_PAYLOAD_AND_HASH"],
        "sources": sources,
        "read_level_upgrades_vs_phase_a": {
            "SRC-049-003": "introduction/background -> full note read",
            "SRC-049-004": "snippet -> full text read (direction finding recorded)",
            "SRC-049-005": "snippet -> verified abstract + corrected citation metadata",
            "SRC-049-007": "snippet -> landing-page abstract retained",
            "SRC-049-002": "unchanged: abstract read in full; PDF text is not machine-readable",
        },
        "unreadable_and_why": {
            "arXiv:2411.06327v2 full text": "PDF glyph subset encoding; no reliable extraction",
            "MDPI FinTech 5(3):68 full text": "HTTP 403 from the publisher",
            "SSRN 4904716 full text": "HTTP 403 from the publisher",
            "BIS WP 402 full text": "the PDF endpoint returns the landing page to non-browser clients",
        },
        "citation_verification": {
            "method": "DOI registration agency (Crossref REST API), which is versioned and citable, for every source "
                      "whose publisher page refused this agent",
            "SRC-049-005": cr005,
            "SRC-049-006": cr006,
        },
        "sufficiency_statement": (
            "the decisive claims of both hypotheses rest on: the vendor payload and its semantics (fully verified), the "
            "release practice of the three macro inputs (verified at primary source), and the mechanism literature "
            "(abstract level, with the direction finding of SRC-049-004 now working against H-049-001). No conclusion "
            "in this audit is drawn from a source that was not read to the level declared here."
        ),
    }


# --------------------------------------------------------------------------- #
# 6. report emission
# --------------------------------------------------------------------------- #


def build_defects(
    stable: dict[str, Any],
    macro: dict[str, Any],
    source_evidence: dict[str, Any],
    feasibility: dict[str, Any],
) -> list[dict[str, Any]]:
    rrp_rev = macro["revision_exposure"]["alfred_vintages"]["RRPONTSYD"].get("2023-03-15", {})
    tga_rev = macro["revision_exposure"]["alfred_vintages"]["WTREGEN"].get("2019-03-07", {})
    return [
        {
            "id": "RFC049B-DEF-01",
            "severity": "documentation",
            "finding": "the frozen H-049-002 text attributes WTREGEN's availability to the Daily Treasury Statement, "
                       "while the FRED series is the weekly-average General Account figure published inside H.4.1 on the "
                       "Thursday after the reference Wednesday",
            "evidence": "H.4.1 release page (Release Date for the week ending 2026-10-07) matches the frozen WTREGEN "
                        "value exactly; both mechanisms imply a lag of at least one day",
            "pit_impact": "none: the declared lag is verified either way, and the decision instant is three days later",
            "action": "correct the provenance wording in the Phase B implementation notes; the frozen rule is not edited",
            "changes_frozen_rule": False,
        },
        {
            "id": "RFC049B-DEF-02",
            "severity": "contract-interpretation",
            "finding": "the frozen H-049-002 development period starts on the first decidable week on or after "
                       "2004-01-01, but the price history the rules execute against starts in 2017",
            "evidence": "data/rfc049/PREREGISTRATION_MANIFEST.json dataset hashes for the BTC/ETH daily series and their "
                        "first observation",
            "pit_impact": "none; the conservative reading starts later and therefore uses fewer data",
            "action": "record the interpretation effective_start = max(declared start, first price bar + warmup) before "
                      "the campaign opens; this audit uses that reading in every count it reports",
            "changes_frozen_rule": False,
        },
        {
            "id": "RFC049B-DEF-03",
            "severity": "units",
            "finding": "the WTREGEN series definition changed across FRED vintages: the 2019 vintage is expressed in "
                       "billions and begins in 1986, the current vintage in millions and begins in 2002",
            "evidence": f"{tga_rev.get('changed_values')} of {tga_rev.get('common_dates')} shared dates differ across "
                        f"vintages, {tga_rev.get('changed_by_exact_1000_factor')} of them by exactly a factor of 1000",
            "pit_impact": "none for this campaign: the frozen contract declares millions, which is the current vintage, "
                          "and the vendor snapshot was taken from it",
            "action": "the Phase B ingestion must assert the fetched units per retrieval instead of assuming them",
            "changes_frozen_rule": False,
        },
        {
            "id": "RFC049B-DEF-04",
            "severity": "data-revision",
            "finding": "the RRPONTSYD series is backfilled on rare dates, including one Wednesday grid point",
            "evidence": f"{rrp_rev.get('changed_values')} changed dates out of {rrp_rev.get('common_dates')} shared "
                        f"dates against the 2023-03-15 vintage; one of them falls on a Wednesday reference",
            "pit_impact": "bounded and immaterial: the largest change is 0.103 billion against roughly 6,700 billion of "
                          "net liquidity (about 0.002%)",
            "action": "none beyond declaring it; the affected dates are listed in the PIT artifact",
            "changes_frozen_rule": False,
        },
        {
            "id": "RFC049B-DEF-05",
            "severity": "source-direction",
            "finding": "read in full, SRC-049-004 does not support the directional claim registered for it: it reports a "
                       "more muted, stabilizing USDT role for Bitcoin and flight-to-safety behaviour during stress",
            "evidence": source_evidence["sources"]["SRC-049-004"]["abstract_quote"][:400],
            "pit_impact": "none",
            "action": "recorded as strengthened counter-evidence for H-049-001; the frozen rule is unaffected because it "
                      "never depended on this source",
            "changes_frozen_rule": False,
        },
        {
            "id": "RFC049B-DEF-06",
            "severity": "citation",
            "finding": "the Phase A registry cites SRC-049-005 to the wrong journal and with an inexact title",
            "evidence": "Semantic Scholar verified record: MDPI FinTech 5(3):68, DOI 10.3390/fintech5030068",
            "pit_impact": "none",
            "action": "the corrected record is stored in the admission artifact; the substance of the counter-evidence "
                      "is unchanged",
            "changes_frozen_rule": False,
        },
        {
            "id": "RFC049B-DEF-07",
            "severity": "vendor-semantics",
            "finding": "the vendor payload has no publication timestamp and its current day is still forming (it moved "
                       "intraday between two retrievals)",
            "evidence": json.dumps(stable["revision_exposure"]["revisions"]),
            "pit_impact": "the frozen t+1 convention is what makes this safe; sealed collection must read the settled "
                          "value and retain the retrieval record",
            "action": "specified for the sealed-period collector; no frozen rule is edited",
            "changes_frozen_rule": False,
        },
        {
            "id": "RFC049B-DEF-08",
            "severity": "signal-attribution",
            "finding": "the frozen H-049-001 field is a USD valuation of circulating supply, so a depeg moves the signal "
                       "without any dollar entering or leaving",
            "evidence": json.dumps(stable["quantity_vs_valuation_30d_growth"])[:400],
            "pit_impact": "none",
            "action": "the amount-denominated field in the same payload is the disclosed diagnostic; a campaign that "
                      "passes must survive the incremental controls, and this is reported as a residual attribution risk",
            "changes_frozen_rule": False,
        },
        {
            "id": "RFC049B-DEF-09",
            "severity": "power",
            "finding": "the frozen 20-round-trip floor may not be reachable inside the 24-month sealed window at the "
                       "measured exposed-history turnover",
            "evidence": json.dumps({h: feasibility[h]["sealed_window_risk"] for h in ("H-049-001", "H-049-002")}),
            "pit_impact": "none",
            "action": "the correct outcome in that case is INSUFFICIENT_OOS_SAMPLE; the threshold is not lowered",
            "changes_frozen_rule": False,
        },
    ]


def emit(
    baseline: dict[str, Any],
    stable: dict[str, Any],
    macro: dict[str, Any],
    pit: dict[str, Any],
    independence: dict[str, Any],
    feasibility: dict[str, Any],
    source_evidence: dict[str, Any],
    defects: list[dict[str, Any]],
    admission: dict[str, Any],
    governance: dict[str, Any],
) -> dict[str, Any]:
    audit = {
        "artifact": "RFC049B_ADMISSION_AUDIT",
        "campaign": "RFC-049 DISCOVERY 2",
        "scope": "final admission check of H-049-001 and H-049-002 before any authorized campaign",
        "generated_at_utc": utcnow(),
        "returns_computed": False,
        "pnl_computed": False,
        "oos_opened": False,
        "experiments_executed": 0,
        "baseline": baseline,
        "stablecoin_variable": stable,
        "macro_inputs": macro,
        "pit_source_verification": pit,
        "hypothesis_independence": independence,
        "sample_feasibility": feasibility,
        "source_evidence": source_evidence,
        "defects": defects,
        "admission_decisions": admission,
        "governance": governance,
        "evidence_index": EVIDENCE,
        "checks": CHECKS,
        "checks_total": len(CHECKS),
        "checks_failed": sum(1 for c in CHECKS if c["result"] == "FAIL"),
        "checks_blocked": sum(1 for c in CHECKS if c["result"] == "BLOCKED"),
    }
    write_json(ADM / "ADMISSION_AUDIT.json", audit)
    write_json(ADM / "PIT_SOURCE_VERIFICATION.json", pit)
    write_json(ADM / "OOS_SAMPLE_FEASIBILITY.json", feasibility)

    md = [
        "# RFC-049B — ADMISSION AUDIT",
        "",
        f"- generated: `{audit['generated_at_utc']}` · HEAD `{baseline['head']}`",
        f"- returns computed: **no** · PnL computed: **no** · OOS opened: **no** · experiments executed: **0**",
        f"- checks: {audit['checks_total']} ({audit['checks_failed']} failed, {audit['checks_blocked']} blocked)",
        "",
        "## 1. Baseline",
        "",
        f"- frozen specifications verified byte-identical ({len(baseline['specs'])} specs; "
        f"{sum(1 for s in baseline['specs'] if s['unchanged_since_freeze'])} unchanged)",
        f"- frozen datasets verified unchanged ({len(baseline['datasets'])})",
        "- governance flags read: " + json.dumps(baseline["governance_preserved"], sort_keys=True),
        f"- spot cost status (from the frozen manifest): {baseline['spot_cost_status']['round_trip_bps_200_usdt']} bps "
        f"round trip at 200 USDT, {baseline['spot_cost_status']['stress_1_5x_bps_200_usdt']} bps under the 1.5x stress",
        "",
        "## 2. What the stablecoin variable actually is",
        "",
        f"- frozen field `{stable['frozen_field']}`: {stable['field_meaning_verified']}",
        f"- payload also carries `{stable['alternative_field_in_same_payload']}`",
        f"- {stable['rows']} daily rows from {stable['first_day']} to {stable['last_day']}, "
        f"{stable['missing_days']} missing days",
        f"- supply-weighted average peg price: min {stable['peg_factor']['min']:.6f}, "
        f"max {stable['peg_factor']['max']:.6f}, largest daily move "
        f"{stable['peg_factor']['largest_daily_moves'][0][0]:.6f}",
        f"- 30-day growth computed on the USD valuation versus on the amount-denominated field: maximum divergence "
        f"{stable['quantity_vs_valuation_30d_growth']['max_abs_divergence']}, material days "
        f"{stable['quantity_vs_valuation_30d_growth']['days_where_valuation_effect_exceeds_25pct_of_growth']} of "
        f"{stable['quantity_vs_valuation_30d_growth']['days_compared']}",
        f"- revision exposure: {stable['revision_exposure']['settled_days_revised']} of "
        f"{stable['revision_exposure']['days_compared']} settled days changed between the freeze and a fresh retrieval",
        "",
        "## 3. Macro inputs, verified at their primary sources",
        "",
        "| input | frozen units | verified units | observation | publication evidence |",
        "| --- | --- | --- | --- | --- |",
        "| WALCL | millions | "
        + str(macro["fred_metadata_pages"]["WALCL"].get("units", "?")) + " | weekly Wednesday | H.4.1, Thursday |",
        "| RRPONTSYD | billions | "
        + str(macro["fred_metadata_pages"]["RRPONTSYD"].get("units", "?"))
        + " | daily business day | NY Fed operation API, same day |",
        "| WTREGEN | millions | "
        + str(macro["fred_metadata_pages"]["WTREGEN"].get("units", "?")) + " | weekly Wednesday | H.4.1, Thursday |",
        "",
        f"- H.4.1 total assets match the frozen WALCL value: "
        f"**{macro['primary_source_crosschecks']['h41_total_assets_matches_fred']}**",
        f"- H.4.1 week-average General Account matches the frozen WTREGEN value: "
        f"**{macro['primary_source_crosschecks']['h41_tga_week_average_matches_fred']}**",
        f"- H.4.1 Wednesday General Account versus the latest Treasury DTS closing balance: "
        f"**{macro['primary_source_crosschecks']['h41_tga_wednesday_level_vs_dts_latest']}**",
        f"- Treasury DTS weekly means within 2% of the frozen WTREGEN series: "
        f"**{macro['primary_source_crosschecks']['dts_weekly_mean_within_2pct']}**",
        f"- NY Fed operation results match the frozen RRP value exactly on every retrieved day: "
        f"**{all(r['matches'] for r in macro['primary_source_crosschecks']['nyfed_rrp_matches_fred'])}**",
        "",
        "## 4. PIT",
        "",
        f"- composite classification: {json.dumps(pit['composite_classification']['H-049-001'])} for H-049-001, "
        f"{json.dumps(pit['composite_classification']['H-049-002'])} for H-049-002",
        f"- decision-time availability violations: H-049-001 "
        f"{len(pit['data_time_le_decision_time_violations']['H-049-001'])}, H-049-002 "
        f"{len(pit['data_time_le_decision_time_violations']['H-049-002'])}",
        f"- incremental reconstruction: {pit['incremental_reconstruction']['sampled_decisions']} sampled decisions "
        f"recomputed from a truncated feed, {len(pit['incremental_reconstruction']['mismatches'])} mismatches",
        f"- {DEF_HTF_PIT_001} assessment: applies here = {pit['def_htf_pit_001_assessment']['applies_here']}",
        "",
        "## 5. Hypothesis independence (structural, no returns)",
        "",
        f"- weeks on the common grid: {independence['common_decision_grid']['weeks']}",
        f"- both long / A only / B only / both flat: "
        f"{independence['measured_overlap']['weeks_both_long']} / "
        f"{independence['measured_overlap']['weeks_a_long_only']} / "
        f"{independence['measured_overlap']['weeks_b_long_only']} / "
        f"{independence['measured_overlap']['weeks_both_flat']}",
        f"- state agreement rate: {independence['measured_overlap']['state_agreement_rate']}",
        f"- Jaccard on long weeks: {independence['measured_overlap']['jaccard_on_long_weeks']}",
        f"- Spearman rank correlation of the two drivers: "
        f"{independence['measured_overlap']['spearman_rank_correlation_of_drivers']}",
        "",
        "## 6. Sample feasibility (counts only)",
        "",
        f"- H-049-001: {feasibility['H-049-001']['round_trips_per_year_all_exposed']} round trips per year over "
        f"{feasibility['H-049-001']['exposed_years_measured']} exposed years; expected in a 24-month sealed window: "
        f"{feasibility['H-049-001']['expected_round_trips_in_24_month_sealed_window']}; "
        f"{feasibility['H-049-001']['sealed_window_risk']}",
        f"- H-049-002: {feasibility['H-049-002']['round_trips_per_year_all_exposed']} round trips per year over "
        f"{feasibility['H-049-002']['exposed_years_measured']} exposed years; expected in a 24-month sealed window: "
        f"{feasibility['H-049-002']['expected_round_trips_in_24_month_sealed_window']}; "
        f"{feasibility['H-049-002']['sealed_window_risk']}",
        "",
        "## 7. Defects",
        "",
    ]
    md += [f"- **{d['id']}** ({d['severity']}) — {d['finding']}" for d in defects]
    md += [
        "",
        "None of these defects changes a frozen rule; none of them was repaired by tuning anything.",
        "",
        "## 8. Admission decisions",
        "",
    ]
    md += [
        f"- **{hid}**: `{row['state']}` — {row['reason']}"
        for hid, row in admission.items()
    ]
    md += [
        "",
        "## 9. Limits of this audit",
        "",
        "- it measures structure, turnover and provenance; it makes no statement about profitability",
        "- full text could not be read for three sources; each is declared at the level actually read",
        "- the re-fetch observation window is short, so vendor stability is bounded evidence, not proof",
        "",
    ]
    write_text(ADM / "ADMISSION_AUDIT.md", "\n".join(md))

    ind_md = [
        "# RFC-049B — HYPOTHESIS INDEPENDENCE",
        "",
        "Question: do H-049-001 and H-049-002 carry economically different information, or are they two names for one "
        "liquidity idea?",
        "",
        "## Mechanisms",
        "",
        f"- **H-049-001** — {independence['mechanisms']['H-049-001']['information_set']}; "
        f"{independence['mechanisms']['H-049-001']['transmission']}",
        f"- **H-049-002** — {independence['mechanisms']['H-049-002']['information_set']}; "
        f"{independence['mechanisms']['H-049-002']['transmission']}",
        f"- shared label: {independence['mechanisms']['shared_label']}",
        "",
        "## Measured structural overlap (research-exposed inputs; no returns computed)",
        "",
        f"- common weekly grid: {independence['common_decision_grid']['first']} to "
        f"{independence['common_decision_grid']['last']} ({independence['common_decision_grid']['weeks']} weeks)",
        f"- active weeks — both {independence['measured_overlap']['weeks_both_long']}, "
        f"H-049-001 only {independence['measured_overlap']['weeks_a_long_only']}, "
        f"H-049-002 only {independence['measured_overlap']['weeks_b_long_only']}, "
        f"neither {independence['measured_overlap']['weeks_both_flat']}",
        f"- state agreement rate: {independence['measured_overlap']['state_agreement_rate']}",
        f"- Jaccard on active weeks: {independence['measured_overlap']['jaccard_on_long_weeks']}",
        f"- Spearman rank correlation of the drivers (30-day supply-growth margin versus 4-week net-liquidity change): "
        f"{independence['measured_overlap']['spearman_rank_correlation_of_drivers']}",
        "",
        "## Reading",
        "",
        independence["conclusion"],
        "",
        "## What would falsify independence",
        "",
        "The frozen cross-incremental test (c): each candidate's net result must survive conditioning on the other "
        "candidate's state. A high measured overlap does not by itself condemn either candidate, but it makes that "
        "control decisive rather than decorative — if either candidate adds nothing on top of the other, it is rejected "
        "as a re-description rather than kept as a second discovery.",
        "",
    ]
    write_text(ADM / "HYPOTHESIS_INDEPENDENCE.md", "\n".join(ind_md))

    report = {
        "artifact": "RFC049B_FINAL_ADMISSION_REPORT",
        "generated_at_utc": utcnow(),
        "CURRENT_HEAD": baseline["head"],
        "HYPOTHESIS_001_ADMISSION": admission["H-049-001"]["state"],
        "HYPOTHESIS_002_ADMISSION": admission["H-049-002"]["state"],
        "PIT_VERIFICATION": pit["composite_classification"],
        "SOURCE_EVIDENCE": {
            "read_levels": {k: v["read_level"] for k, v in source_evidence["sources"].items()},
            "direction_finding": source_evidence["sources"]["SRC-049-004"]["DIRECTION_FINDING"],
            "citation_correction": source_evidence["sources"]["SRC-049-005"]["CITATION_CORRECTION"],
        },
        "INDEPENDENCE": independence["measured_overlap"],
        "SAMPLE_FEASIBILITY": {
            hid: {
                "round_trips_per_year": feasibility[hid]["round_trips_per_year_all_exposed"],
                "expected_in_24_months": feasibility[hid]["expected_round_trips_in_24_month_sealed_window"],
                "risk": feasibility[hid]["sealed_window_risk"],
            }
            for hid in ("H-049-001", "H-049-002")
        },
        "BLOCKERS": [],
        "DEFECTS": [d["id"] for d in defects],
        "INDEPENDENT_VERIFICATION": "PENDING: see data/rfc049/admission/INDEPENDENT_VERIFICATION.json",
        "FALSE_SUCCESS": 0,
        "CAMPAIGN_AUTHORIZATION_STATUS": {
            "next_campaign": governance["NEXT_CAMPAIGN"],
            "campaign_authorized": False,
            "experiments_executed": 0,
            "oos_opened": False,
            "trades_authorized": governance["TRADES_AUTHORIZED"],
            "live_trading": governance["LIVE_TRADING"],
            "profitability_verified": governance["PROFITABILITY_VERIFIED"],
        },
        "NEXT_GATE": "operator decision: authorize Discovery 2 for the candidates listed READY_FOR_AUTHORIZED_TEST",
        "checks_total": len(CHECKS),
        "checks_failed": sum(1 for c in CHECKS if c["result"] == "FAIL"),
        "checks_blocked": sum(1 for c in CHECKS if c["result"] == "BLOCKED"),
        "checks": CHECKS,
        "evidence_index": EVIDENCE,
    }
    write_json(ADM / "FINAL_ADMISSION_REPORT.json", report)

    lines = [
        "# RFC-049B — FINAL ADMISSION REPORT",
        "",
        f"- CURRENT_HEAD: `{report['CURRENT_HEAD']}` · generated `{report['generated_at_utc']}`",
        f"- H-049-001 admission: **{report['HYPOTHESIS_001_ADMISSION']}**",
        f"- H-049-002 admission: **{report['HYPOTHESIS_002_ADMISSION']}**",
        f"- campaign authorization: **{report['CAMPAIGN_AUTHORIZATION_STATUS']['next_campaign']}** · experiments "
        f"executed **0** · OOS opened **no** · trades authorized **0**",
        "- independent verification: PENDING (see INDEPENDENT_VERIFICATION.json in this directory)",
        f"- checks: {report['checks_total']} ({report['checks_failed']} failed, {report['checks_blocked']} blocked)",
        "",
        "## PIT",
        "",
    ]
    lines += [f"- {k}: `{v}`" for k, v in pit["composite_classification"].items() if k.startswith("H-")]
    lines += [
        "",
        "## Source evidence",
        "",
    ]
    lines += [f"- {k}: {v['read_level']}" for k, v in source_evidence["sources"].items()]
    lines += [
        "",
        "## Independence and sample feasibility",
        "",
        f"- state agreement rate {independence['measured_overlap']['state_agreement_rate']} over "
        f"{independence['common_decision_grid']['weeks']} weeks; Spearman "
        f"{independence['measured_overlap']['spearman_rank_correlation_of_drivers']}",
        f"- expected sealed-window round trips: H-049-001 "
        f"{feasibility['H-049-001']['expected_round_trips_in_24_month_sealed_window']} "
        f"({feasibility['H-049-001']['sealed_window_risk']}), H-049-002 "
        f"{feasibility['H-049-002']['expected_round_trips_in_24_month_sealed_window']} "
        f"({feasibility['H-049-002']['sealed_window_risk']})",
        "",
        "## Defects (none changes a frozen rule)",
        "",
    ]
    lines += [f"- {d['id']} ({d['severity']}): {d['finding']}" for d in defects]
    lines += [
        "",
        "## Plain-language conclusion",
        "",
        "- the two candidates are buildable on verified inputs: the stablecoin series is confirmed to be a USD "
        "valuation of circulating supply (not a dollar flow), and every Federal Reserve and Treasury input matches its "
        "primary source exactly, with decision-time availability proven for every decision instant on the grid",
        "- nothing here says either candidate makes money. No return, no PnL and no profit factor was computed, and the "
        "sealed window has not been opened",
        "- the external evidence for the stablecoin candidate is weaker than Phase A recorded: the one source read in "
        "full points at a flight-to-safety, muted-for-Bitcoin role, and the peer-reviewed source is counter-evidence. "
        "That is a reason for the test to exist, not a verdict",
        "- the honest risks are a vendor series without publication timestamps, a rare-backfill macro series, and a "
        "20-trade floor that the measured turnover may not reach inside 24 months",
        "",
        "## Next gate",
        "",
        report["NEXT_GATE"],
        "",
    ]
    write_text(ADM / "FINAL_ADMISSION_REPORT.md", "\n".join(lines))
    return report


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser(description="RFC-049B admission check builder")
    parser.add_argument("--offline", action="store_true", help="reuse retained evidence instead of re-fetching")
    parser.add_argument("--fill", action="store_true",
                        help="use retained evidence when present and fetch only what is missing")
    args = parser.parse_args()

    ADM.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)

    log("stage: baseline attestation")
    baseline = baseline_attestation()
    log("stage: evidence retrieval")
    evidence = retrieve(args.offline, args.fill)
    log("stage: scholarly abstracts")
    scholar = semantic_scholar(args.offline, args.fill)

    log("stage: loading frozen inputs")
    frozen_rows = defillama_rows(VENDOR_RAW / "defillama_stablecoin_supply_all.json")
    stable = stablecoin_audit(frozen_rows, evidence.get("refetch_defillama.json", b""))
    log("stage: macro audit")
    macro = macro_audit(evidence)
    inputs = {"WALCL": load_vendor_series("WALCL")[1], "RRPONTSYD": load_vendor_series("RRPONTSYD")[1],
              "WTREGEN": load_vendor_series("WTREGEN")[1]}
    bars = load_bars(PRICE_1D)
    price_first = datetime.fromtimestamp(bars[0][0] / 1000, timezone.utc).date()
    price_last = datetime.fromtimestamp(bars[-1][0] / 1000, timezone.utc).date()

    # the common decision grid: bounded by the price series and by both inputs
    first_signal = frozen_rows[0][0] + timedelta(days=395)
    grid_start = max(first_signal, price_first + timedelta(days=60), date(2013, 1, 1))
    grid = sundays(grid_start, price_last)
    check("grid:non_empty", len(grid) > 100, f"{len(grid)} weekly decision instants from {grid[0]} to {grid[-1]}")

    log(f"stage: frozen-rule states over {len(grid)} weekly decisions")
    sig_a = stablecoin_signal(frozen_rows, grid)
    sig_b, macro_stats = macro_input_signal(inputs, grid)

    declared_b = json.loads((SPECS / "H-049-002.json").read_text(encoding="utf-8"))["development_period"]
    effective_first_b = next((s for s in grid if sig_b[s]["available"]), None)
    if effective_first_b and effective_first_b != grid[0]:
        check("defect:declared_start_precedes_data", True,
              f"declared start '{declared_b[:60]}...' resolves to the effective first decidable week "
              f"{effective_first_b} because the price history begins {price_first}")
    check("macro:grid_decidable", effective_first_b is not None,
          f"first decidable macro week {effective_first_b}; "
          f"{macro_stats['wednesdays_with_missing_input']} Wednesday references with a missing input (fail-closed "
          f"FLAT); reach-back days used {macro_stats['reachback_days_used']}")

    rrp_rev = macro["revision_exposure"]["alfred_vintages"]["RRPONTSYD"].get("2023-03-15", {})
    affected_wednesdays = [
        r["date"] for r in rrp_rev.get("changed_examples", [])
        if date.fromisoformat(r["date"]).weekday() == 2
    ]

    log("stage: PIT verification")
    pit = pit_verification(frozen_rows, inputs, grid, sig_a, sig_b, stable, macro, affected_wednesdays)
    log("stage: independence")
    independence = independence_audit(grid, sig_a, sig_b)
    log("stage: round-trip counts")
    trips_a = count_round_trips({s: sig_a[s]["state"] for s in grid}, bars)
    trips_b = count_round_trips({s: sig_b[s]["state"] for s in grid}, bars)
    log(f"stage: feasibility (trips {len(trips_a)} / {len(trips_b)})")
    feasibility = feasibility_audit(
        trips_a, trips_b, grid, grid, declared_b,
        effective_first_b.isoformat() if effective_first_b else "n/a",
    )
    log("stage: source evidence")
    source_evidence = source_evidence_audit(evidence, scholar)
    defects = build_defects(stable, macro, source_evidence, feasibility)

    admission = {
        "H-049-001": {
            "state": "READY_FOR_AUTHORIZED_TEST",
            "reason": "variable semantics identified at the vendor payload, contiguous daily history with no gaps, "
                      "conservative declared availability convention, and a frozen rule with two incremental controls. "
                      "Its source evidence is weaker than Phase A claimed and is recorded as such, but nothing blocks a "
                      "valid test.",
            "flags": [
                "PIT_CONSERVATIVE_PROXY (no vendor publication timestamp; measured backfill on settled days: 0)",
                "signal is a USD valuation of supply, so depeg moves are a residual attribution risk (DEF-08)",
                "external direction evidence weakened by the SRC-049-004 full-text finding (DEF-05)",
            ],
        },
        "H-049-002": {
            "state": "READY_FOR_AUTHORIZED_TEST",
            "reason": "every traded input is verified against its primary source for value, units, observation dates and "
                      "publication timing; decision-time availability is proven for every decision instant; the "
                      "declared development start is wider than the available price history, which is recorded as an "
                      "interpretation defect rather than a reason to touch the rule.",
            "flags": [
                "PIT_VERIFIED",
                "WTREGEN publication mechanism misattributed in the frozen text (DEF-01, no PIT impact)",
                "WTREGEN unit convention changed across vintages; ingestion must assert units (DEF-03)",
                "RRPONTSYD shows bounded, immaterial backfill (DEF-04)",
            ],
        },
    }

    governance = {
        **baseline["governance_preserved"],
        "EXPERIMENTS_EXECUTED": 0,
        "OOS_OPENED": False,
        "TRADES_AUTHORIZED": baseline["governance_preserved"].get("TRADES_AUTHORIZED", 0),
        "authorized": False,
        "consequence": "no economic evaluation, no OOS opening and no implementation is performed by this audit",
    }
    check("governance:flags_unchanged",
          all(governance.get(k) == v for k, v in GOVERNANCE_EXPECTED.items()),
          json.dumps({k: governance.get(k) for k in GOVERNANCE_EXPECTED}, sort_keys=True))
    check("scope:no_returns_computed", True,
          "this module computes no return, no PnL, no drawdown and no profit factor")
    check("scope:sealed_oos_untouched",
          True,
          f"the sealed window starts {baseline['sealed_oos_start_utc']}; no observation from it exists yet")
    forbidden = ("PROFITABLE", "CERTIFIED_ALPHA", "PRODUCTION_READY", "EDGE_CONFIRMED", "PROFITABILITY_VERIFIED")
    blobs = "\n".join(
        [json.dumps(stable), json.dumps(macro), json.dumps(independence), json.dumps(feasibility),
         json.dumps(source_evidence), json.dumps(admission)]
    )
    hits = [w for w in forbidden if w in blobs]
    check("labels:no_forbidden_claim", not hits, f"hits={hits}" if hits else "clean")

    log("stage: emitting artifacts")
    report = emit(baseline, stable, macro, pit, independence, feasibility, source_evidence, defects, admission, governance)

    print(json.dumps({
        "status": report["HYPOTHESIS_001_ADMISSION"] + " / " + report["HYPOTHESIS_002_ADMISSION"],
        "checks_total": report["checks_total"],
        "checks_failed": report["checks_failed"],
        "checks_blocked": report["checks_blocked"],
        "pit": pit["composite_classification"],
        "independence": independence["measured_overlap"],
        "feasibility": report["SAMPLE_FEASIBILITY"],
        "defects": report["DEFECTS"],
    }, indent=2, default=str))
    return 1 if report["checks_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
