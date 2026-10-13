"""Independent verification of WP-EDGE-03 (forward observation and risk parity).

    python scripts/edge03_verify.py [--dir reports/edge-recovery/WP-EDGE-03]
                                    [--self-test] [--json-out FILE]

This process imports NOTHING from ``trading_bot``. It reads the published artefacts, the
raw forward store, the frozen corpora and the source files, restates every constant and
rule from the declarations written here, and recomputes what the payload claims:

1.  ``ARTIFACTS_PRESENT``              every required artefact exists and is not empty
2.  ``FROZEN_CORPUS_UNCHANGED``        the frozen shards' digests and last instants are the
                                       ones the payload recorded (so the past did not move)
3.  ``FROZEN_PARAMS_PINNED``           the ruleset digest re-derived from the source text
                                       equals the payload's pin and the campaign's
                                       published ``params_hash``
4.  ``STORE_DIGESTS_MATCH_MANIFEST``   every store file answers to its published sha256
5.  ``FORWARD_BARS_AFTER_FREEZE``      every stored bar is on the grid, strictly after the
                                       frozen end, and was CLOSED when it was fetched
6.  ``QUALITY_RECOMPUTED``             gaps, duplicates and order recomputed from the store
7.  ``OBSERVATION_DAYS_RECOMPUTED``    the coverage rule applied to the raw bars
8.  ``LATENCY_RECOMPUTED``             bar close to store, from the stored provenance
9.  ``SHADOW_WINDOW_RESPECTED``        no signal, fill or refusal sits at or before a freeze
10. ``SHADOW_WINDOW_START_CONSISTENT`` each arm's window start is the first bucket after
                                       the frozen end of its own source timeframe
11. ``HYPOTHETICAL_ONLY``              every shadow row is hypothetical and order-free
12. ``SHADOW_ACCOUNTING``              net == sum(fills) and the curve closes on the book
13. ``EXPOSURE_RECOMPUTED``            each arm's exposure recomputed from its own fills
14. ``PARITY_CLASSES_RECOMPUTED``      every case's class, the counts and the verdict are
                                       re-derived from the published decision columns
15. ``PARITY_CASES_COMPLETE``          both decisions present, class in the vocabulary
16. ``RESTART_PROOF_CONSISTENT``       the second ingest appended nothing and moved nothing
17. ``VERDICT_RECOMPUTED``             the observation verdict follows from the floor
18. ``TEST_TARGET_EQUALS_RUNTIME``     the tests and the runner drive the same callable
19. ``NO_ORDER_PATH``                  no order endpoint or exchange client is referenced

``--self-test`` sabotages a copy of the evidence once per check and requires the matching
check to break: a check nobody can break is reported as a failure, not as a pass.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- #
# What the run is allowed to be, restated here rather than read from it
# --------------------------------------------------------------------------- #

#: The frozen ends, by source timeframe (ms UTC).
FROZEN_END = {"1h": 1_772_319_600_000, "15m": 1_791_372_600_000}
#: The frozen shard digests, by (timeframe, asset), first 16 hex characters.
FROZEN_SHARD = {
    "1h:BTC": "f4d16c3664c142d1",
    "1h:ETH": "365046d4738aa7b1",
    "1h:SOL": "847d8eb45eafebd8",
    "15m:BTC": "cd1d2ea256a97f7c",
    "15m:ETH": "b8fd5744cc66f635",
    "15m:SOL": "72a268137cbe944b",
}
FROZEN_LAST = {"1h": 1_772_319_600_000, "15m": 1_791_372_600_000}
SPAN_MS = {"1h": 3_600_000, "15m": 900_000, "4h": 14_400_000, "1d": 86_400_000}
BARS_PER_DAY = {"1h": 24, "15m": 96}
COVERAGE = 0.90
MIN_OBSERVATION_DAYS = 60
ASSETS = ("BTC", "ETH", "SOL")

CORPUS_1H = "reports/alpha-expansion-v1/data"
CORPUS_15M = "data/raw/alpha003/price"

#: Where the campaign published the ruleset digest, and the source that holds the ruleset.
#: The verifier reads the ruleset out of the SOURCE TEXT (it imports no ``trading_bot``
#: code), so a module-level constant could not hide a change made after publication.
FROZEN_PARAMS_PATH = "reports/edge-recovery/WP-EDGE-01/oos-trend-4h/OOS_TREND.json"
CANDIDATES_SOURCE = "src/trading_bot/research/edge01/candidates.py"

REQUIRED = (
    "forward-observation/OBSERVATION.json",
    "forward-observation/INGEST_LEDGER.jsonl",
    "forward-observation/CUMULATIVE.md",
    "forward-observation/CUMULATIVE.json",
    "risk-parity/PARITY.json",
    "risk-parity/PARITY_CASES.csv",
    "risk-parity/PARITY.md",
)

#: Restated from ``parity.PARITY_DECISION``: the mapping and the class vocabulary.
REASON_TO_RUNTIME_RULE = {
    "risk_max_trades_per_day": "daily_trade_limit",
    "risk_max_open_positions": "max_positions",
    "risk_loss_cooldown": "consecutive_loss_cooldown",
    "risk_drawdown_halt": "max_drawdown",
    "risk_exposure_cap": "position_sizing",
    "risk_notional_below_minimum": "position_sizing",
    "position_already_open": "max_positions",
    "stop_above_fill": "position_sizing",
    "fill_price_invalid": "position_sizing",
    "parity_approved": "APPROVED",
}
NOT_MODELLED_BY_RESEARCH = ("kill_switch", "daily_loss_limit", "weekly_loss_limit", "daily_drawdown")
CLASSES = (
    "AGREE_APPROVED",
    "AGREE_REFUSED_SAME_RULE",
    "RULE_ORDER_DIFFERS",
    "RULE_NOT_MODELLED_BY_RESEARCH",
    "RESEARCH_ONLY_REFUSAL",
    "SIZING_ROUNDING_ONLY",
    "SIZING_DIFFERS",
    "PARITY_DEFECT",
)
NOTIONAL_TOLERANCE = 1e-6
#: The runtime publishes PositionSize.notional_usdt rounded to cents; a gap inside half a
#: cent is a presentation difference, and the verifier restates that boundary here.
RUNTIME_PUBLISHED_ROUNDING = 0.005
EQUITY_TOLERANCE = 0.05

#: Files a forward lane must never reference: a private endpoint or an order call.
FORBIDDEN_TOKENS = (
    "api/v3/order",
    "create_order",
    "place_order",
    "cancel_order",
    "ccxt",
    "apiKey",
    "api_secret",
    "BITUNIX_API",
)
SCANNED_SOURCES = (
    "src/trading_bot/research/edge03/forward_plan.py",
    "src/trading_bot/research/edge03/ingest.py",
    "src/trading_bot/research/edge03/shadow.py",
    "src/trading_bot/research/edge03/parity.py",
    "src/trading_bot/research/edge03/reporting.py",
    "src/trading_bot/research/edge03/run.py",
    "scripts/edge03_run.py",
)


@dataclass(frozen=True, slots=True)
class Bundle:
    """Where the evidence is. Everything a check needs comes through here.

    ``repo`` is the tree that holds the forward store (a rehearsal points it at a
    temporary checkout), ``corpus`` is where the frozen shards live (always the real ones:
    the point of the check is that the past did not move), and ``sources`` is the code the
    lane's own checks read.
    """

    artifacts: Path
    repo: Path
    sources: Path
    corpus: Path | None = None

    @property
    def corpus_root(self) -> Path:
        return self.corpus or self.repo

    def path(self, relative: str) -> Path:
        return self.artifacts / relative

    def load(self, relative: str) -> Any:
        return json.loads(self.path(relative).read_text(encoding="utf-8"))

    def observation(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.load("forward-observation/OBSERVATION.json"))

    def parity(self) -> dict[str, Any]:
        return cast(dict[str, Any], self.load("risk-parity/PARITY.json"))

    def store_root(self) -> Path:
        return self.repo / "data" / "forward" / "edge03"

    def store_rows(self, timeframe: str, asset: str) -> list[dict[str, Any]]:
        path = self.store_root() / timeframe / f"{asset}.jsonl"
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def ledger(self) -> list[dict[str, Any]]:
        path = self.path("forward-observation/INGEST_LEDGER.jsonl")
        return [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]

    def csv(self, relative: str) -> list[dict[str, str]]:
        path = self.path(relative)
        if not path.exists():
            return []
        with path.open(encoding="utf-8", newline="") as handle:
            return list(csv.DictReader(handle))

    def source(self, relative: str) -> str:
        path = self.sources / relative
        return path.read_text(encoding="utf-8") if path.exists() else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _shard_paths(repo: Path, timeframe: str, asset: str) -> list[Path]:
    if timeframe == "15m":
        return [repo / CORPUS_15M / f"{asset}USDT_15m.json"]
    return sorted(
        path
        for path in (repo / CORPUS_1H).glob(f"{asset}USDT_*.json")
        if not path.name.startswith("_")
    )


def _combined_digest(paths: list[Path]) -> str:
    combined = hashlib.sha256()
    for path in sorted(paths):
        combined.update(path.name.encode("utf-8"))
        combined.update(_sha256(path).encode("utf-8"))
    return combined.hexdigest()


def _last_bar_ts(paths: list[Path]) -> int:
    newest = 0
    for path in paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        rows = raw if isinstance(raw, list) else (raw.get("bars") or raw.get("data") or [])
        for row in rows:
            ts = int(row["ts"]) if isinstance(row, dict) else int(row[0])
            newest = max(newest, ts)
    return newest


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truth(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #
def check_artifacts_present(bundle: Bundle) -> list[tuple[str, bool, str]]:
    missing = [name for name in REQUIRED if not bundle.path(name).exists()]
    empty = [name for name in REQUIRED if bundle.path(name).exists() and not bundle.path(name).stat().st_size]
    return [
        (
            "ARTIFACTS_PRESENT",
            not missing and not empty,
            f"{len(REQUIRED)} artefact(s) required; missing {missing or 'none'}, empty {empty or 'none'}",
        )
    ]


def check_frozen_corpus(bundle: Bundle) -> list[tuple[str, bool, str]]:
    payload = bundle.observation()
    recorded = payload.get("frozen_corpus") or {}
    failures: list[str] = []
    for timeframe in ("1h", "15m"):
        for asset in ASSETS:
            key = f"{timeframe}:{asset}"
            paths = _shard_paths(bundle.corpus_root, timeframe, asset)
            if not paths:
                failures.append(f"{key}: no shard found")
                continue
            digest = _combined_digest(paths)[:16]
            last = _last_bar_ts(paths)
            if digest != FROZEN_SHARD[key]:
                failures.append(f"{key}: digest {digest} != frozen {FROZEN_SHARD[key]}")
            if last != FROZEN_LAST[timeframe]:
                failures.append(f"{key}: last bar {last} != frozen {FROZEN_LAST[timeframe]}")
            seen = recorded.get(key) or {}
            if seen.get("sha256_prefix16") != digest or seen.get("last_ts") != last:
                failures.append(f"{key}: the payload recorded a different corpus than the disk")
    return [
        (
            "FROZEN_CORPUS_UNCHANGED",
            not failures,
            "; ".join(failures) if failures else "all 6 frozen series match their pinned digests",
        )
    ]


def _params_digest(source: str) -> str | None:
    """Hash the ``FROZEN_PARAMS`` literal exactly as it stands in the source text.

    ``ast`` is the point: the verifier must be able to hash a ruleset the lane could have
    edited between the publication and this run, and importing the module would hand back
    whatever the current code happens to say.
    """
    for node in ast.parse(source).body:
        value_node: ast.expr | None = None
        if isinstance(node, ast.AnnAssign):
            name = getattr(node.target, "id", None)
            value_node = node.value
        elif isinstance(node, ast.Assign):
            name = next(
                (getattr(target, "id", None) for target in node.targets if getattr(target, "id", None)),
                None,
            )
            value_node = node.value
        else:
            continue
        if name == "FROZEN_PARAMS" and value_node is not None:
            literal: Any = ast.literal_eval(value_node)
            canonical: str = json.dumps(literal, sort_keys=True, separators=(",", ":"))
            return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return None


def check_frozen_params(bundle: Bundle) -> list[tuple[str, bool, str]]:
    """The ruleset this run read forward is the ruleset the campaign published.

    Three independent statements must agree: the digest re-derived from the source text,
    the digest the payload pinned, and the digest WP-EDGE-01 published. A forward reading
    of a tuned ruleset is not a forward reading of the frozen one, so a disagreement here
    is a failure rather than a note.
    """
    payload = bundle.observation()
    recorded = payload.get("frozen_params") or {}
    planned = ((payload.get("plan") or {}).get("frozen") or {}).get("params_hash")
    source = bundle.source(CANDIDATES_SOURCE)
    failures: list[str] = []
    rederived = _params_digest(source) if source else None
    if not source:
        failures.append(f"{CANDIDATES_SOURCE} is not readable")
    elif rederived is None:
        failures.append(f"no FROZEN_PARAMS literal found in {CANDIDATES_SOURCE}")
    published_path = ROOT / FROZEN_PARAMS_PATH
    published = None
    if published_path.is_file():
        published = json.loads(published_path.read_text(encoding="utf-8")).get("params_hash")
    else:
        failures.append(f"no publication at {FROZEN_PARAMS_PATH}")
    if rederived is not None:
        for label, value in (
            ("the payload's ruleset pin", recorded.get("params_hash")),
            ("the plan's frozen digest", planned),
            ("the published params_hash", published),
        ):
            if value != rederived:
                failures.append(f"{label} is {value}, the source re-derives {rederived}")
    if recorded.get("agrees_with_publication") is not True:
        failures.append("the payload does not assert agreement with the publication")
    return [
        (
            "FROZEN_PARAMS_PINNED",
            not failures,
            "; ".join(failures)
            if failures
            else (
                f"ruleset digest {str(rederived)[:16]} re-derived from the source, pinned "
                f"by the payload and equal to the published value"
            ),
        )
    ]


def check_store_digests(bundle: Bundle) -> list[tuple[str, bool, str]]:
    payload = bundle.observation()
    manifest = (payload.get("manifest") or {}).get("files") or {}
    ledger = bundle.ledger()
    failures: list[str] = []
    for key, entry in sorted(manifest.items()):
        timeframe, asset = key.split(":", 1)
        path = bundle.store_root() / timeframe / f"{asset}.jsonl"
        if not path.exists():
            if entry.get("bars"):
                failures.append(f"{key}: store file missing but the manifest claims bars")
            continue
        digest = _sha256(path)
        if digest != entry.get("sha256"):
            failures.append(f"{key}: digest {digest[:12]} != manifest {str(entry.get('sha256'))[:12]}")
        rows = bundle.store_rows(timeframe, asset)
        if len(rows) != int(entry.get("bars") or 0):
            failures.append(f"{key}: {len(rows)} row(s) on disk vs {entry.get('bars')} declared")
        tail = [row for row in ledger if row.get("timeframe") == timeframe and row.get("symbol") == asset]
        if tail and tail[-1].get("store_sha256") not in (None, digest):
            failures.append(f"{key}: the ledger's last digest disagrees with the store")
    return [
        (
            "STORE_DIGESTS_MATCH_MANIFEST",
            not failures,
            "; ".join(failures) if failures else f"{len(manifest)} store file(s) verified",
        )
    ]


def check_forward_bars(bundle: Bundle) -> list[tuple[str, bool, str]]:
    failures: list[str] = []
    bars = 0
    for timeframe in ("1h", "15m"):
        span = SPAN_MS[timeframe]
        for asset in ASSETS:
            for row in bundle.store_rows(timeframe, asset):
                bars += 1
                ts = int(row["ts"])
                if ts <= FROZEN_END[timeframe]:
                    failures.append(f"{timeframe}:{asset} bar {ts} is not after the freeze")
                if ts % span:
                    failures.append(f"{timeframe}:{asset} bar {ts} is off the {timeframe} grid")
                fetched = int(row.get("fetched_at_ms") or 0)
                if ts + span > fetched:
                    failures.append(f"{timeframe}:{asset} bar {ts} was stored before it closed")
                o, h, low, c = (float(row[k]) for k in ("open", "high", "low", "close"))
                if h < low or h < max(o, c) or low > min(o, c) or min(o, h, low, c) <= 0:
                    failures.append(f"{timeframe}:{asset} bar {ts} is not a valid OHLC block")
    return [
        (
            "FORWARD_BARS_AFTER_FREEZE",
            not failures,
            "; ".join(failures[:6]) if failures else f"{bars} forward bar(s) admissible",
        )
    ]


def _audit(rows: list[dict[str, Any]], *, timeframe: str) -> dict[str, Any]:
    span = SPAN_MS[timeframe]
    stamps = [int(row["ts"]) for row in rows]
    gaps: list[dict[str, Any]] = []
    missing = 0
    for a, b in pairwise(stamps):
        if b - a <= span:
            continue
        slots = (b - a) // span - 1
        missing += int(slots)
        gaps.append({"after_ts": a, "before_ts": b, "missing_bars": int(slots)})
    if stamps:
        expected_first = FROZEN_END[timeframe] + span
        if stamps[0] > expected_first:
            slots = (stamps[0] - expected_first) // span
            missing += int(slots)
            gaps.insert(0, {"after_ts": FROZEN_END[timeframe], "before_ts": stamps[0], "missing_bars": int(slots)})
    return {
        "bars": len(stamps),
        "first_ts": stamps[0] if stamps else None,
        "last_ts": stamps[-1] if stamps else None,
        "duplicates": len(stamps) - len(set(stamps)),
        "out_of_order": sum(1 for a, b in pairwise(stamps) if b <= a),
        "gap_count": len(gaps),
        "missing_bars": missing,
    }


def check_quality(bundle: Bundle) -> list[tuple[str, bool, str]]:
    quality = bundle.observation().get("quality") or {}
    failures: list[str] = []
    for timeframe in ("1h", "15m"):
        for asset in ASSETS:
            key = f"{timeframe}:{asset}"
            recomputed = _audit(bundle.store_rows(timeframe, asset), timeframe=timeframe)
            claimed = quality.get(key) or {}
            for field in ("bars", "first_ts", "last_ts", "duplicates", "out_of_order", "gap_count", "missing_bars"):
                if claimed.get(field) != recomputed[field]:
                    failures.append(f"{key}.{field}: claimed {claimed.get(field)} vs {recomputed[field]}")
            claimed_contiguous = bool(claimed.get("contiguous"))
            expected = (
                recomputed["missing_bars"] == 0
                and recomputed["duplicates"] == 0
                and recomputed["out_of_order"] == 0
            )
            if claimed_contiguous != expected:
                failures.append(f"{key}.contiguous: claimed {claimed_contiguous} vs {expected}")
    return [
        (
            "QUALITY_RECOMPUTED",
            not failures,
            "; ".join(failures[:6]) if failures else "gaps, duplicates and order match the store",
        )
    ]


def check_observation_days(bundle: Bundle) -> list[tuple[str, bool, str]]:
    payload = bundle.observation()
    claimed = payload.get("observation") or {}
    failures: list[str] = []
    common: set[str] | None = None
    for timeframe in ("1h", "15m"):
        expected = BARS_PER_DAY[timeframe]
        for asset in ASSETS:
            key = f"{timeframe}:{asset}"
            per_day: dict[str, int] = {}
            for row in bundle.store_rows(timeframe, asset):
                day = datetime.fromtimestamp(int(row["ts"]) / 1000, tz=UTC).strftime("%Y-%m-%d")
                per_day[day] = per_day.get(day, 0) + 1
            days = sorted(day for day, count in per_day.items() if count >= COVERAGE * expected)
            seen = claimed.get(key) or {}
            if int(seen.get("observation_days") or 0) != len(days):
                failures.append(
                    f"{key}: claimed {seen.get('observation_days')} day(s) vs {len(days)} recomputed"
                )
            if timeframe == "1h":
                common = set(days) if common is None else common & set(days)
    health = payload.get("health") or {}
    recomputed_common = len(common or set())
    if int(health.get("observation_days") or 0) != recomputed_common:
        failures.append(
            f"health.observation_days: claimed {health.get('observation_days')} vs {recomputed_common}"
        )
    detail = (health.get("observation_days_detail") or {}).get("common_days")
    if detail is not None and int(detail) != recomputed_common:
        failures.append(f"health.observation_days_detail.common_days: {detail} vs {recomputed_common}")
    return [
        (
            "OBSERVATION_DAYS_RECOMPUTED",
            not failures,
            "; ".join(failures[:6]) if failures else f"{recomputed_common} common observation day(s)",
        )
    ]


def check_latency(bundle: Bundle) -> list[tuple[str, bool, str]]:
    """Both latency readings, each recomputed from the store's own provenance.

    The window figures must match every stored bar; the fresh figures must match the bars
    stamped with the run's own fetch instant. The split matters: a run that mixed the two
    could publish the first run's backfill as if it were the feed's current latency.
    """
    payload = bundle.observation()
    claimed = payload.get("latency") or {}
    run_instant = payload.get("observed_at_ms")
    failures: list[str] = []
    for timeframe in ("1h", "15m"):
        span = SPAN_MS[timeframe]
        for asset in ASSETS:
            key = f"{timeframe}:{asset}"
            rows = bundle.store_rows(timeframe, asset)
            lag = [
                (int(row["fetched_at_ms"]) - (int(row["ts"]) + span)) / 1000.0
                for row in rows
                if row.get("fetched_at_ms") is not None
            ]
            fresh = [
                (int(row["fetched_at_ms"]) - (int(row["ts"]) + span)) / 1000.0
                for row in rows
                if row.get("fetched_at_ms") is not None
                and run_instant is not None
                and int(row["fetched_at_ms"]) == int(run_instant)
            ]
            seen = claimed.get(key) or {}
            if int(seen.get("samples") or 0) != len(lag):
                failures.append(f"{key}.samples: {seen.get('samples')} vs {len(lag)}")
                continue
            if int(seen.get("fresh_bars") or 0) != len(fresh):
                failures.append(f"{key}.fresh_bars: {seen.get('fresh_bars')} vs {len(fresh)}")
            for field, value in (
                ("min_seconds", min(lag) if lag else None),
                ("median_seconds", _median(lag) if lag else None),
                ("max_seconds", max(lag) if lag else None),
                ("fresh_min_seconds", min(fresh) if fresh else None),
                ("fresh_median_seconds", _median(fresh) if fresh else None),
                ("fresh_max_seconds", max(fresh) if fresh else None),
            ):
                claimed_value = seen.get(field)
                if value is None:
                    # This run pulled no bar for this series, so there is no lag to report:
                    # a number here is a figure the store cannot support.
                    if claimed_value is not None:
                        failures.append(
                            f"{key}.{field}: claims {claimed_value} for a run that pulled no bar"
                        )
                    continue
                if abs(float(claimed_value or 0.0) - value) > 1e-3:
                    failures.append(f"{key}.{field}: {claimed_value} vs {round(value, 3)}")
            instants = {row.get("fetched_at_ms") for row in rows if row.get("fetched_at_ms")}
            if int(seen.get("fetch_instants") or 0) != len(instants):
                failures.append(f"{key}.fetch_instants: {seen.get('fetch_instants')} vs {len(instants)}")
    return [
        (
            "LATENCY_RECOMPUTED",
            not failures,
            "; ".join(failures[:6])
            if failures
            else "window and last-run ingestion lag both match the stored provenance",
        )
    ]


def check_shadow_window(bundle: Bundle) -> list[tuple[str, bool, str]]:
    failures: list[str] = []
    rows = 0
    for name in ("SHADOW_SIGNALS.csv", "SHADOW_TRADES.csv", "SHADOW_REFUSALS.csv"):
        for row in bundle.csv(f"forward-observation/{name}"):
            rows += 1
            arm = row.get("arm") or row.get("candidate") or ""
            if name == "SHADOW_REFUSALS.csv":
                # a candidate-level refusal carries the arm in the candidate column
                arm = row.get("candidate") or ""
            timeframe = "15m" if str(arm).startswith("edge_intra") else "1h"
            ts = _num(row.get("decision_ts"))
            if ts is None:
                failures.append(f"{name}: a row without a decision instant")
                continue
            if ts <= FROZEN_END[timeframe]:
                failures.append(f"{name}: {arm} decision at {int(ts)} is not after the freeze")
    if not rows:
        failures.append("no shadow row was published at all")
    return [
        (
            "SHADOW_WINDOW_RESPECTED",
            not failures,
            "; ".join(failures[:6]) if failures else f"{rows} shadow row(s) inside the forward window",
        )
    ]


def check_shadow_window_start(bundle: Bundle) -> list[tuple[str, bool, str]]:
    arms = (bundle.observation().get("shadow") or {}).get("arm_summaries") or {}
    failures: list[str] = []
    checked = 0
    for arm, body in sorted(arms.items()):
        if body.get("status") != "observed":
            continue
        checked += 1
        timeframe = str(body.get("timeframe"))
        source = "15m" if timeframe == "15m" else "1h"
        span = SPAN_MS[timeframe]
        start = int(body.get("window_start_ts") or 0)
        # The window must start on the arm's own grid, strictly after the frozen end, and
        # no later than one bucket past it: the first bucket that could have opened.
        if start % span:
            failures.append(f"{arm}: window start {start} is off the {timeframe} grid")
        if not (FROZEN_END[source] < start <= FROZEN_END[source] + span):
            failures.append(
                f"{arm}: window starts at {start}, which is not the first {timeframe} bucket "
                f"after the frozen end {FROZEN_END[source]}"
            )
        signals = bundle.csv("forward-observation/SHADOW_SIGNALS.csv")
        mine = [row for row in signals if row.get("arm") == arm]
        for row in mine:
            if int(float(row["decision_ts"])) < int(body.get("window_start_ts") or 0):
                failures.append(f"{arm}: a signal precedes the declared window start")
                break
    return [
        (
            "SHADOW_WINDOW_START_CONSISTENT",
            not failures,
            "; ".join(failures[:6]) if failures else f"{checked} observed arm(s) start exactly after their freeze",
        )
    ]


def check_hypothetical(bundle: Bundle) -> list[tuple[str, bool, str]]:
    payload = bundle.observation()
    failures: list[str] = []
    rows = 0
    for name in ("SHADOW_SIGNALS.csv", "SHADOW_TRADES.csv"):
        for row in bundle.csv(f"forward-observation/{name}"):
            rows += 1
            if not _truth(row.get("hypothetical")):
                failures.append(f"{name}: a row is not marked hypothetical")
            if _truth(row.get("order_sent")):
                failures.append(f"{name}: a row claims an order was sent")
    shadow = payload.get("shadow") or {}
    if shadow.get("order_sent") is not False:
        failures.append("the payload does not declare order_sent false")
    if shadow.get("hypothetical") is not True:
        failures.append("the payload does not declare the shadow hypothetical")
    return [
        (
            "HYPOTHETICAL_ONLY",
            not failures,
            "; ".join(failures[:6]) if failures else f"{rows} shadow row(s) hypothetical, zero orders",
        )
    ]


def check_shadow_accounting(bundle: Bundle) -> list[tuple[str, bool, str]]:
    payload = bundle.observation()
    arms = (payload.get("shadow") or {}).get("arm_summaries") or {}
    trades = bundle.csv("forward-observation/SHADOW_TRADES.csv")
    curve = bundle.csv("forward-observation/SHADOW_EQUITY.csv")
    failures: list[str] = []
    by_arm: dict[str, float] = {}
    count: dict[str, int] = {}
    for row in trades:
        net = _num(row.get("net"))
        if net is None:
            failures.append("a trade row has no net")
            continue
        arm = str(row.get("arm"))
        by_arm[arm] = by_arm.get(arm, 0.0) + net
        count[arm] = count.get(arm, 0) + 1
    for arm, body in sorted(arms.items()):
        if body.get("status") != "observed":
            continue
        metrics = body.get("metrics") or {}
        claimed_net = float(metrics.get("net_usdt") or 0.0)
        recomputed = by_arm.get(arm, 0.0)
        if abs(claimed_net - recomputed) > EQUITY_TOLERANCE:
            failures.append(f"{arm}: net {claimed_net} vs sum(fills) {round(recomputed, 6)}")
        if int(metrics.get("trades") or 0) != count.get(arm, 0):
            failures.append(f"{arm}: {metrics.get('trades')} fills claimed vs {count.get(arm, 0)} rows")
    primary_key = str((payload.get("shadow") or {}).get("primary_arm"))
    primary = arms.get(primary_key) or {}
    if primary.get("status") == "observed" and curve:
        last = _num(curve[-1].get("equity")) or 0.0
        expected = 10_000.0 + by_arm.get(primary_key, 0.0)
        if abs(last - expected) > 1.0:
            failures.append(
                f"the primary curve closes at {last} USDT but 10,000 + net is {round(expected, 6)}"
            f" for {primary_key}"
            )
    return [
        (
            "SHADOW_ACCOUNTING",
            not failures,
            "; ".join(failures[:6]) if failures else "every arm's net equals the sum of its fills",
        )
    ]


def check_exposure(bundle: Bundle) -> list[tuple[str, bool, str]]:
    """The published exposure must be the one the fills imply, not a number of its own."""
    arms = (bundle.observation().get("shadow") or {}).get("arm_summaries") or {}
    by_arm: dict[str, list[dict[str, str]]] = {}
    for row in bundle.csv("forward-observation/SHADOW_TRADES.csv"):
        by_arm.setdefault(str(row.get("arm")), []).append(row)
    failures: list[str] = []
    checked = 0
    for arm, body in sorted(arms.items()):
        if body.get("status") != "observed":
            continue
        checked += 1
        span = SPAN_MS[str(body.get("timeframe"))]
        bars = int(body.get("window_bars") or 0)
        rows = by_arm.get(arm, [])
        expected = (
            sum((float(r["exit_ts"]) - float(r["entry_ts"])) / span for r in rows) / bars * 100.0
            if bars
            else None
        )
        claimed = (body.get("metrics") or {}).get("exposure_pct_of_time")
        if claimed is None or expected is None:
            if claimed != expected:
                failures.append(f"{arm}: exposure {claimed} vs {expected}")
            continue
        if abs(float(claimed) - expected) > 1e-6:
            failures.append(f"{arm}: exposure {claimed} vs the fills' {round(expected, 6)}")
    return [
        (
            "EXPOSURE_RECOMPUTED",
            not failures,
            "; ".join(failures[:6])
            if failures
            else f"{checked} observed arm(s) exposure recomputed from their fills",
        )
    ]


def _classify(research_approved: bool, research_reason: str, runtime_approved: bool, blocked_by: str,
              research_notional: float | None, runtime_notional: float | None) -> str:
    if research_approved and runtime_approved:
        if research_notional is None or runtime_notional is None:
            return "PARITY_DEFECT"
        gap = abs(research_notional - runtime_notional)
        if gap <= NOTIONAL_TOLERANCE:
            return "AGREE_APPROVED"
        return "SIZING_ROUNDING_ONLY" if gap <= RUNTIME_PUBLISHED_ROUNDING else "SIZING_DIFFERS"
    if not research_approved and not runtime_approved:
        mapped = REASON_TO_RUNTIME_RULE.get(research_reason, "UNMAPPED")
        return "AGREE_REFUSED_SAME_RULE" if mapped == blocked_by else "RULE_ORDER_DIFFERS"
    if research_approved and not runtime_approved:
        return (
            "RULE_NOT_MODELLED_BY_RESEARCH"
            if blocked_by in NOT_MODELLED_BY_RESEARCH
            else "PARITY_DEFECT"
        )
    return "RESEARCH_ONLY_REFUSAL"


def check_parity_classes(bundle: Bundle) -> list[tuple[str, bool, str]]:
    payload = bundle.parity()
    rows = bundle.csv("risk-parity/PARITY_CASES.csv")
    failures: list[str] = []
    counts: dict[str, int] = {}
    defects = 0
    for row in rows:
        research_approved = row.get("research_decision") == "APPROVED"
        runtime_approved = row.get("runtime_decision") == "APPROVED"
        expected = _classify(
            research_approved,
            str(row.get("research_reason") or ""),
            runtime_approved,
            str(row.get("runtime_blocked_by") or ""),
            _num(row.get("research_notional")),
            _num(row.get("runtime_notional")),
        )
        if expected != row.get("class"):
            failures.append(
                f"{row.get('case_id')}: published {row.get('class')} vs recomputed {expected}"
            )
        counts[expected] = counts.get(expected, 0) + 1
        if expected == "PARITY_DEFECT":
            defects += 1
    published = payload.get("counts") or {}
    for klass, value in sorted(counts.items()):
        if int(published.get(klass) or 0) != value:
            failures.append(f"counts[{klass}]: published {published.get(klass)} vs {value}")
    for klass in published:
        if klass not in counts:
            failures.append(f"counts[{klass}] is published but no case carries it")
    expected_verdict = "PARITY_PASS" if defects == 0 and not (payload.get("captured_reproduction") or {}).get("mismatches") else "PARITY_FINDINGS"
    if payload.get("verdict") != expected_verdict:
        failures.append(f"verdict {payload.get('verdict')} vs {expected_verdict} from {defects} defect(s)")
    return [
        (
            "PARITY_CLASSES_RECOMPUTED",
            not failures,
            "; ".join(failures[:6])
            if failures
            else f"{len(rows)} case(s) re-classified, {defects} defect(s)",
        )
    ]


def check_parity_complete(bundle: Bundle) -> list[tuple[str, bool, str]]:
    payload = bundle.parity()
    rows = bundle.csv("risk-parity/PARITY_CASES.csv")
    failures: list[str] = []
    seen: set[str] = set()
    for row in rows:
        case_id = str(row.get("case_id"))
        if case_id in seen:
            failures.append(f"{case_id}: duplicate case id")
        seen.add(case_id)
        if row.get("class") not in CLASSES:
            failures.append(f"{case_id}: class {row.get('class')!r} is not in the vocabulary")
        if row.get("research_decision") not in {"APPROVED", "REFUSED"}:
            failures.append(f"{case_id}: no research decision")
        if row.get("runtime_decision") not in {"APPROVED", "REFUSED"}:
            failures.append(f"{case_id}: no runtime decision")
        if row.get("runtime_decision") == "REFUSED" and not row.get("runtime_blocked_by"):
            failures.append(f"{case_id}: refused by the runtime with no rule named")
    declared = len(payload.get("cases") or [])
    if declared != len(rows):
        failures.append(f"PARITY.json carries {declared} case(s) but the CSV has {len(rows)}")

    # Every instant the shadow captured must be checked; a run that captured none must say
    # so instead of publishing an empty grid as if it had covered the window.
    captured = int(((bundle.observation().get("shadow") or {}).get("captured_decisions")) or 0)
    shadow_rows = [row for row in rows if row.get("origin") == "shadow"]
    reproduction = payload.get("captured_reproduction") or {}
    if captured == 0 and shadow_rows:
        failures.append(f"{len(shadow_rows)} shadow case(s) exist but the run captured none")
    if captured and not shadow_rows:
        failures.append(f"{captured} instant(s) were captured but none reached the parity grid")
    if captured and int(reproduction.get("checked") or 0) != len(shadow_rows):
        failures.append(
            f"captured_reproduction.checked is {reproduction.get('checked')} but {len(shadow_rows)} "
            "shadow case(s) were published"
        )
    if int(reproduction.get("reproduced") or 0) != int(reproduction.get("checked") or 0):
        failures.append(
            f"{reproduction.get('checked')} captured decision(s) checked but only "
            f"{reproduction.get('reproduced')} reproduced"
        )
    return [
        (
            "PARITY_CASES_COMPLETE",
            not failures,
            "; ".join(failures[:6]) if failures else f"{len(rows)} case(s) complete and unique",
        )
    ]


def check_restart(bundle: Bundle) -> list[tuple[str, bool, str]]:
    proof = bundle.observation().get("restart_proof") or {}
    ledger = bundle.ledger()
    failures: list[str] = []
    if proof.get("second_run_appended") not in (0, None):
        failures.append(f"the second ingest appended {proof.get('second_run_appended')} bar(s)")
    if proof.get("digests_unchanged") is not True:
        failures.append("the store digests moved between the two runs")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in ledger:
        grouped.setdefault((str(row.get("timeframe")), str(row.get("symbol"))), []).append(row)
    for key, rows in grouped.items():
        last_two = rows[-2:]
        if (
            len(rows) >= 2
            and int(last_two[0].get("run_at_ms") or 0) == int(last_two[1].get("run_at_ms") or 0)
            and int(last_two[1].get("appended") or 0) != 0
        ):
            failures.append(f"{key}: the second run at the same instant appended bars")
    if int(proof.get("duplicate_timestamps") or 0) != 0:
        failures.append("the store reports duplicate timestamps")
    if int(proof.get("duplicate_refusals") or 0) != 0:
        failures.append("the primary arm reports duplicate refusals")
    for timeframe in ("1h", "15m"):
        for asset in ASSETS:
            stamps = [int(row["ts"]) for row in bundle.store_rows(timeframe, asset)]
            if len(stamps) != len(set(stamps)):
                failures.append(f"{timeframe}:{asset}: duplicate timestamps in the store")
    return [
        (
            "RESTART_PROOF_CONSISTENT",
            not failures,
            "; ".join(failures[:6]) if failures else "the second ingest added nothing and moved nothing",
        )
    ]


def check_verdict(bundle: Bundle) -> list[tuple[str, bool, str]]:
    payload = bundle.observation()
    verdict = payload.get("verdict") or {}
    health = payload.get("health") or {}
    stored = int(health.get("stored_bars") or 0)
    days = int(health.get("observation_days") or 0)
    if stored == 0:
        expected = "OBSERVATION_STALLED"
    elif days < MIN_OBSERVATION_DAYS:
        expected = "OBSERVATION_RUNNING"
    else:
        expected = "OBSERVATION_AVAILABLE"
    failures: list[str] = []
    if verdict.get("state") != expected:
        failures.append(f"state {verdict.get('state')} vs {expected}")
    if verdict.get("promotion") != "NONE":
        failures.append(f"promotion {verdict.get('promotion')!r} is not NONE")
    parity_verdict = (payload.get("parity") or {}).get("verdict")
    if verdict.get("parity") != parity_verdict:
        failures.append(f"the verdict quotes parity {verdict.get('parity')} but the payload says {parity_verdict}")
    floor = int(verdict.get("observation_floor") or 0)
    if floor != MIN_OBSERVATION_DAYS:
        failures.append(f"the observation floor is {floor}, not {MIN_OBSERVATION_DAYS}")
    if int(verdict.get("stored_bars") or 0) != stored:
        failures.append(f"the verdict quotes {verdict.get('stored_bars')} stored bar(s) vs {stored}")
    return [
        (
            "VERDICT_RECOMPUTED",
            not failures,
            "; ".join(failures[:6]) if failures else f"{expected} with promotion NONE",
        )
    ]


def check_target(bundle: Bundle) -> list[tuple[str, bool, str]]:
    payload = bundle.observation()
    target = str(payload.get("test_target") or "")
    entrypoint = str(payload.get("entrypoint") or "")
    tests = bundle.source("tests/unit/research/test_edge03_forward.py")
    runner = bundle.source("scripts/edge03_run.py")
    failures: list[str] = []
    if not target:
        failures.append("the payload does not name the target the tests drive")
    if target and f"{target}(" not in runner:
        failures.append("the runner does not call the declared target")
    if target and f"{target}(" not in tests:
        failures.append("the tests do not call the declared target")
    if target and f":{target}" not in entrypoint:
        failures.append(f"the entrypoint {entrypoint!r} does not name the target")
    return [
        (
            "TEST_TARGET_EQUALS_RUNTIME",
            not failures,
            "; ".join(failures[:6]) if failures else f"both targets are {target}",
        )
    ]


def check_no_order_path(bundle: Bundle) -> list[tuple[str, bool, str]]:
    hits: list[str] = []
    for relative in SCANNED_SOURCES:
        text = bundle.source(relative)
        if not text:
            hits.append(f"{relative}: not found")
            continue
        for token in FORBIDDEN_TOKENS:
            if token in text:
                hits.append(f"{relative}: contains {token!r}")
    return [
        (
            "NO_ORDER_PATH",
            not hits,
            "; ".join(hits[:6]) if hits else f"{len(SCANNED_SOURCES)} source(s) free of order paths",
        )
    ]


CHECKS: tuple[tuple[str, Callable[[Bundle], list[tuple[str, bool, str]]]], ...] = (
    ("ARTIFACTS_PRESENT", check_artifacts_present),
    ("FROZEN_CORPUS_UNCHANGED", check_frozen_corpus),
    ("FROZEN_PARAMS_PINNED", check_frozen_params),
    ("STORE_DIGESTS_MATCH_MANIFEST", check_store_digests),
    ("FORWARD_BARS_AFTER_FREEZE", check_forward_bars),
    ("QUALITY_RECOMPUTED", check_quality),
    ("OBSERVATION_DAYS_RECOMPUTED", check_observation_days),
    ("LATENCY_RECOMPUTED", check_latency),
    ("SHADOW_WINDOW_RESPECTED", check_shadow_window),
    ("SHADOW_WINDOW_START_CONSISTENT", check_shadow_window_start),
    ("HYPOTHETICAL_ONLY", check_hypothetical),
    ("SHADOW_ACCOUNTING", check_shadow_accounting),
    ("EXPOSURE_RECOMPUTED", check_exposure),
    ("PARITY_CLASSES_RECOMPUTED", check_parity_classes),
    ("PARITY_CASES_COMPLETE", check_parity_complete),
    ("RESTART_PROOF_CONSISTENT", check_restart),
    ("VERDICT_RECOMPUTED", check_verdict),
    ("TEST_TARGET_EQUALS_RUNTIME", check_target),
    ("NO_ORDER_PATH", check_no_order_path),
)


def run_checks(bundle: Bundle) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for name, function in CHECKS:
        produced = function(bundle)
        for check_name, passed, detail in produced:
            results.append({"check": check_name, "passed": bool(passed), "detail": detail})
        if not any(entry["check"] == name for entry in results):
            results.append(
                {"check": name, "passed": False, "detail": "the check produced no result"}
            )
    failed = [entry for entry in results if not entry["passed"]]
    return {
        "checks": results,
        "passed": len(results) - len(failed),
        "failed": len(failed),
        "verdict": "VERIFY_PASS" if not failed else "VERIFY_FAIL",
    }


# --------------------------------------------------------------------------- #
# Sabotage self-test
# --------------------------------------------------------------------------- #
def _copy_evidence(bundle: Bundle, tmp: Path) -> Bundle:
    """A private copy of the artefacts, the sources AND the store.

    The store has to be copied per sabotage case: a sabotage that appends a bar would
    otherwise leak into every later case and make a check look like it broke for the wrong
    reason. With an isolated store, a broken check is evidence about its own sabotage.
    """
    artifacts = tmp / "artifacts"
    shutil.copytree(bundle.artifacts, artifacts)
    sources = tmp / "sources"
    for relative in (*SCANNED_SOURCES, "tests/unit/research/test_edge03_forward.py", CANDIDATES_SOURCE):
        target = sources / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        source = bundle.sources / relative
        if source.exists():
            shutil.copy2(source, target)
    repo = tmp / "repo"
    store = bundle.store_root()
    if store.exists():
        shutil.copytree(store, repo / "data" / "forward" / "edge03")
    return replace(bundle, artifacts=artifacts, sources=sources, repo=repo)


def _rewrite_json(path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _rewrite_csv(path: Path, mutate: Callable[[list[dict[str, str]]], list[dict[str, str]]]) -> None:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = reader.fieldnames or []
    rows = mutate(rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _sabotages() -> list[tuple[str, Callable[[Bundle], Bundle]]]:
    def delete_artifact(bundle: Bundle) -> Bundle:
        bundle.path("risk-parity/PARITY.md").unlink()
        return bundle

    def move_frozen(bundle: Bundle) -> Bundle:
        _rewrite_json(
            bundle.path("forward-observation/OBSERVATION.json"),
            lambda payload: payload["frozen_corpus"]["1h:BTC"].__setitem__("sha256_prefix16", "deadbeefdeadbeef"),
        )
        return bundle

    def break_manifest(bundle: Bundle) -> Bundle:
        _rewrite_json(
            bundle.path("forward-observation/OBSERVATION.json"),
            lambda payload: payload["manifest"]["files"]["1h:BTC"].__setitem__("sha256", "0" * 64),
        )
        return bundle

    def bar_before_freeze(bundle: Bundle) -> Bundle:
        path = bundle.store_root() / "1h" / "BTC.jsonl"
        row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        row["ts"] = FROZEN_END["1h"]
        path.write_text(json.dumps(row, sort_keys=True) + "\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
        return bundle

    def ruleset_tuned(bundle: Bundle) -> Bundle:
        path = bundle.sources / CANDIDATES_SOURCE
        text = path.read_text(encoding="utf-8")
        tuned = text.replace('"resistance_lookback": 20', '"resistance_lookback": 21', 1)
        if tuned == text:
            raise AssertionError(
                "the frozen-parameter sabotage no longer matches the source it targets; "
                "a sabotage that changes nothing would prove nothing"
            )
        path.write_text(tuned, encoding="utf-8")
        return bundle

    def fake_quality(bundle: Bundle) -> Bundle:
        _rewrite_json(
            bundle.path("forward-observation/OBSERVATION.json"),
            lambda payload: payload["quality"]["1h:BTC"].__setitem__("duplicates", 3),
        )
        return bundle

    def fake_days(bundle: Bundle) -> Bundle:
        _rewrite_json(
            bundle.path("forward-observation/OBSERVATION.json"),
            lambda payload: payload["health"].__setitem__("observation_days", 999),
        )
        return bundle

    def fake_latency(bundle: Bundle) -> Bundle:
        _rewrite_json(
            bundle.path("forward-observation/OBSERVATION.json"),
            lambda payload: payload["latency"]["1h:BTC"].__setitem__("max_seconds", -1.0),
        )
        return bundle

    def fake_fresh_latency(bundle: Bundle) -> Bundle:
        """Claim a last-run lag the store cannot support, in whichever state the run is.

        A negative lag is impossible, so the claim is wrong either way; and when the run
        pulled no bar at all the payload has to publish NO fresh figure, which is the
        other half of the rule this sabotage probes.
        """

        def mutate(payload: dict[str, Any]) -> None:
            latency = payload.get("latency") or {}
            fresh_keys = sorted(key for key, seen in latency.items() if seen.get("fresh_samples"))
            for key in (fresh_keys or sorted(latency))[:1]:
                latency[key]["fresh_min_seconds"] = -1.0
                latency[key]["fresh_max_seconds"] = -1.0

        _rewrite_json(bundle.path("forward-observation/OBSERVATION.json"), mutate)
        return bundle

    def signal_before_freeze(bundle: Bundle) -> Bundle:
        path = bundle.path("forward-observation/SHADOW_SIGNALS.csv")
        _rewrite_csv(
            path,
            lambda rows: [
                {**row, "decision_ts": str(FROZEN_END["1h"])}
                if str(row.get("arm")).startswith("edge_trend_01")
                else row
                for row in rows
            ],
        )
        return bundle

    def window_start_moved(bundle: Bundle) -> Bundle:
        _rewrite_json(
            bundle.path("forward-observation/OBSERVATION.json"),
            lambda payload: payload["shadow"]["arm_summaries"][
                str(payload["shadow"]["primary_arm"])
            ].__setitem__("window_start_ts", FROZEN_END["1h"]),
        )
        return bundle

    def order_sent(bundle: Bundle) -> Bundle:
        path = bundle.path("forward-observation/SHADOW_SIGNALS.csv")
        _rewrite_csv(path, lambda rows: [{**rows[0], "order_sent": "true"}, *rows[1:]] if rows else rows)
        return bundle

    def net_moved(bundle: Bundle) -> Bundle:
        path = bundle.path("forward-observation/SHADOW_TRADES.csv")
        _rewrite_csv(
            path,
            lambda rows: [
                {**rows[0], "net": str((_num(rows[0].get("net")) or 0.0) + 1000.0)},
                *rows[1:],
            ]
            if rows
            else rows,
        )
        return bundle

    def class_flipped(bundle: Bundle) -> Bundle:
        path = bundle.path("risk-parity/PARITY_CASES.csv")

        def mutate(rows: list[dict[str, str]]) -> list[dict[str, str]]:
            if not rows:
                return rows
            current = rows[0].get("class")
            # Pick a class that is definitely NOT the one the columns justify.
            replacement = next(name for name in CLASSES if name != current)
            return [{**rows[0], "class": replacement}, *rows[1:]]

        _rewrite_csv(path, mutate)
        return bundle

    def counts_moved(bundle: Bundle) -> Bundle:
        _rewrite_json(
            bundle.path("risk-parity/PARITY.json"),
            lambda payload: payload["counts"].__setitem__("AGREE_APPROVED", 12345),
        )
        return bundle

    def restart_broken(bundle: Bundle) -> Bundle:
        _rewrite_json(
            bundle.path("forward-observation/OBSERVATION.json"),
            lambda payload: payload["restart_proof"].__setitem__("second_run_appended", 5),
        )
        return bundle

    def verdict_broken(bundle: Bundle) -> Bundle:
        states = ("OBSERVATION_STALLED", "OBSERVATION_RUNNING", "OBSERVATION_AVAILABLE")

        def mutate(payload: dict[str, Any]) -> None:
            # Pick a state that is definitely NOT the one the numbers justify, whatever
            # that state happens to be in this run.
            current = payload["verdict"].get("state")
            payload["verdict"]["state"] = next(name for name in states if name != current)

        _rewrite_json(bundle.path("forward-observation/OBSERVATION.json"), mutate)
        return bundle

    def target_broken(bundle: Bundle) -> Bundle:
        path = bundle.sources / "tests/unit/research/test_edge03_forward.py"
        path.write_text("def test_nothing():\n    assert True\n", encoding="utf-8")
        return bundle

    def exposure_broken(bundle: Bundle) -> Bundle:
        payload = bundle.observation()
        primary = str((payload.get("shadow") or {}).get("primary_arm"))

        def mutate(payload: dict[str, Any]) -> None:
            body = payload["shadow"]["arm_summaries"][primary]
            body["metrics"]["exposure_pct_of_time"] = (
                float(body["metrics"].get("exposure_pct_of_time") or 0.0) + 5.0
            )

        _rewrite_json(bundle.path("forward-observation/OBSERVATION.json"), mutate)
        return bundle

    def order_path(bundle: Bundle) -> Bundle:
        path = bundle.sources / "scripts/edge03_run.py"
        path.write_text(
            path.read_text(encoding="utf-8") + "\n# forbidden: create_order('BTCUSDT')\n",
            encoding="utf-8",
        )
        return bundle

    return [
        ("delete an artefact", delete_artifact),
        ("move the frozen corpus digest", move_frozen),
        ("tune a frozen ruleset parameter", ruleset_tuned),
        ("break a store digest in the manifest", break_manifest),
        ("write a bar at the frozen end", bar_before_freeze),
        ("inflate the duplicate count", fake_quality),
        ("inflate the observation days", fake_days),
        ("falsify the ingestion latency", fake_latency),
        ("publish the backfill as the last-run latency", fake_fresh_latency),
        ("move a signal before the freeze", signal_before_freeze),
        ("move the shadow window start", window_start_moved),
        ("claim an order was sent", order_sent),
        ("move a trade's net", net_moved),
        ("flip a parity class", class_flipped),
        ("inflate a parity count", counts_moved),
        ("break the restart proof", restart_broken),
        ("overstate the verdict", verdict_broken),
        ("stop the tests driving the target", target_broken),
        ("inflate the primary arm's exposure", exposure_broken),
        ("introduce an order call", order_path),
    ]


def self_test(bundle: Bundle) -> dict[str, Any]:
    """Sabotage the evidence once per check and require the matching check to break."""
    results: list[dict[str, Any]] = []
    expected_failures = {
        "delete an artefact": "ARTIFACTS_PRESENT",
        "move the frozen corpus digest": "FROZEN_CORPUS_UNCHANGED",
        "tune a frozen ruleset parameter": "FROZEN_PARAMS_PINNED",
        "break a store digest in the manifest": "STORE_DIGESTS_MATCH_MANIFEST",
        "write a bar at the frozen end": "FORWARD_BARS_AFTER_FREEZE",
        "inflate the duplicate count": "QUALITY_RECOMPUTED",
        "inflate the observation days": "OBSERVATION_DAYS_RECOMPUTED",
        "falsify the ingestion latency": "LATENCY_RECOMPUTED",
        "publish the backfill as the last-run latency": "LATENCY_RECOMPUTED",
        "move a signal before the freeze": "SHADOW_WINDOW_RESPECTED",
        "move the shadow window start": "SHADOW_WINDOW_START_CONSISTENT",
        "claim an order was sent": "HYPOTHETICAL_ONLY",
        "move a trade's net": "SHADOW_ACCOUNTING",
        "flip a parity class": "PARITY_CLASSES_RECOMPUTED",
        "inflate a parity count": "PARITY_CLASSES_RECOMPUTED",
        "break the restart proof": "RESTART_PROOF_CONSISTENT",
        "overstate the verdict": "VERDICT_RECOMPUTED",
        "stop the tests driving the target": "TEST_TARGET_EQUALS_RUNTIME",
        "inflate the primary arm's exposure": "EXPOSURE_RECOMPUTED",
        "introduce an order call": "NO_ORDER_PATH",
    }
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = _copy_evidence(bundle, root / "base")
        clean = run_checks(base)
        for index, (label, sabotage) in enumerate(_sabotages()):
            case_dir = root / f"case{index:02d}"
            case_dir.mkdir(parents=True, exist_ok=True)
            case_bundle = _copy_evidence(bundle, case_dir)
            try:
                case_bundle = sabotage(case_bundle)
            except FileNotFoundError as missing:
                # The artefact this sabotage targets does not exist in this run (a window
                # with no fills publishes no trade ledger). Reported as skipped, never as
                # a detected break: a sabotage nobody applied proves nothing.
                results.append(
                    {
                        "sabotage": label,
                        "expected_check": expected_failures[label],
                        "detected": None,
                        "skipped": str(missing),
                    }
                )
                continue
            outcome = run_checks(case_bundle)
            broken = {
                entry["check"] for entry in outcome["checks"] if not entry["passed"]
            }
            expected = expected_failures[label]
            results.append(
                {
                    "sabotage": label,
                    "expected_check": expected,
                    "detected": expected in broken,
                    "broken_checks": sorted(broken),
                    "collateral": sorted(broken - {expected}),
                    "baseline_passed": clean["verdict"] == "VERIFY_PASS",
                }
            )
    undetected = [row for row in results if row.get("detected") is False]
    skipped = [row for row in results if row.get("detected") is None]
    applied = len(results) - len(skipped)
    collateral = sum(len(row.get("collateral") or []) for row in results)
    return {
        "sabotages": results,
        "collateral_breaks": collateral,
        "applied": applied,
        "detected": applied - len(undetected),
        "undetected": len(undetected),
        "skipped": len(skipped),
        "skipped_labels": [row["sabotage"] for row in skipped],
        "verdict": "SELF_TEST_PASS" if not undetected else "SELF_TEST_FAIL",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default="reports/edge-recovery/WP-EDGE-03")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    bundle = Bundle(
        artifacts=(ROOT / args.dir).resolve(),
        repo=ROOT,
        sources=ROOT,
        corpus=ROOT,
    )
    report = run_checks(bundle)
    for entry in report["checks"]:
        mark = "PASS" if entry["passed"] else "FAIL"
        print(f"[{mark}] {entry['check']:<32} {entry['detail']}")
    print(f"verdict: {report['verdict']} ({report['passed']} passed, {report['failed']} failed)")

    payload: dict[str, Any] = {"checks": report}
    if args.self_test:
        payload["self_test"] = self_test(bundle)
        print(
            f"self-test: {payload['self_test']['verdict']} "
            f"({payload['self_test']['detected']} detected, {payload['self_test']['undetected']} "
            f"undetected, {payload['self_test']['skipped']} skipped)"
        )
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    failed = report["failed"] or (args.self_test and payload.get("self_test", {}).get("undetected", 0))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
