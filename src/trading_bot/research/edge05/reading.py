"""One reading of the live state, and the provenance of every number in it.

The problem this module exists for is not measurement, it is *staleness*. A report written by hand
next to a lane that ticks every fifteen minutes is a set of numbers read at several different
instants, with nothing saying which is which; two readings of a moving system then read as a
contradiction, and a figure quoted from the wrong hour reads as a regression.

So a reading is taken **once**, frozen, and digested. Every figure carries the instant it was read
at, the artefact it came from, that artefact's digest, and what it counts — so a reader can tell a
number that moved from a number that was wrong. The Markdown and the JSON reports are both rendered
from the frozen snapshot and from nothing else, and a snapshot whose digest does not match its own
contents is refused rather than rendered.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "Figure",
    "ReadingSnapshot",
    "Source",
    "collect",
    "read_json",
    "read_jsonl",
    "sha256_file",
    "sha256_text",
    "snapshot_digest",
]

SCHEMA_VERSION = "EDGE05R_READING_V1"
GIB = 1024**3


def now_ms() -> int:
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def stamp(instant_ms: int) -> str:
    return datetime.fromtimestamp(instant_ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return ""
    return digest.hexdigest()


def canonical(payload: Any) -> str:
    """The one spelling of a payload that its digest is taken over."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return rows
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            body = json.loads(line)
        except ValueError:
            continue  # a torn last line is counted elsewhere, not invented here
        if isinstance(body, dict):
            rows.append(body)
    return rows


@dataclass(frozen=True)
class Source:
    """An artefact the reading was taken from, with its digest and its size at that instant."""

    path: str
    bytes: int
    digest: str
    rows: int | None
    as_of_utc: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "bytes": self.bytes,
            "digest": self.digest,
            "rows": self.rows,
            "as_of_utc": self.as_of_utc,
        }


@dataclass(frozen=True)
class Figure:
    """One number, with the instant it was read at and the artefact it came from."""

    name: str
    value: Any
    unit: str
    run_id: str
    as_of_utc: str
    source_artifact: str
    source_digest: str
    measurement_scope: str
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "figure": self.name,
            "value": self.value,
            "unit": self.unit,
            "run_id": self.run_id,
            "as_of_utc": self.as_of_utc,
            "source_artifact": self.source_artifact,
            "source_digest": self.source_digest,
            "measurement_scope": self.measurement_scope,
            "note": self.note,
        }


@dataclass(frozen=True)
class ReadingSnapshot:
    """A frozen reading. Nothing renders from anything but this."""

    schema_version: str
    run_id: str
    as_of_utc: str
    host: str
    repo_root: str
    sources: dict[str, Source]
    figures: tuple[Figure, ...]
    facts: dict[str, Any] = field(default_factory=dict)
    digest: str = ""
    hypothetical: bool = True
    order_sent: bool = False
    promotion: str = "NONE"

    # -- reading it ------------------------------------------------------- #
    def figure(self, name: str) -> Figure:
        for item in self.figures:
            if item.name == name:
                return item
        raise KeyError(name)

    def value(self, name: str, default: Any = None) -> Any:
        try:
            return self.figure(name).value
        except KeyError:
            return default

    def by_prefix(self, prefix: str) -> tuple[Figure, ...]:
        return tuple(item for item in self.figures if item.name.startswith(prefix))

    def sourced(self, key: str) -> Source | None:
        return self.sources.get(key)

    def as_dict(self, *, with_digest: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "as_of_utc": self.as_of_utc,
            "host": self.host,
            "repo_root": self.repo_root,
            "sources": {key: source.as_dict() for key, source in sorted(self.sources.items())},
            "figures": [item.as_dict() for item in sorted(self.figures, key=lambda f: f.name)],
            "facts": self.facts,
            "hypothetical": self.hypothetical,
            "order_sent": self.order_sent,
            "promotion": self.promotion,
        }
        if with_digest:
            payload["digest"] = self.digest or snapshot_digest(payload)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReadingSnapshot:
        figures = tuple(
            Figure(
                name=str(row["figure"]),
                value=row.get("value"),
                unit=str(row.get("unit", "")),
                run_id=str(row.get("run_id", "")),
                as_of_utc=str(row.get("as_of_utc", "")),
                source_artifact=str(row.get("source_artifact", "")),
                source_digest=str(row.get("source_digest", "")),
                measurement_scope=str(row.get("measurement_scope", "")),
                note=str(row.get("note", "")),
            )
            for row in payload.get("figures", [])
        )
        sources = {
            key: Source(
                path=str(body.get("path", "")),
                bytes=int(body.get("bytes") or 0),
                digest=str(body.get("digest", "")),
                rows=body.get("rows"),
                as_of_utc=str(body.get("as_of_utc", "")),
            )
            for key, body in (payload.get("sources") or {}).items()
        }
        return cls(
            schema_version=str(payload.get("schema_version", SCHEMA_VERSION)),
            run_id=str(payload.get("run_id", "")),
            as_of_utc=str(payload.get("as_of_utc", "")),
            host=str(payload.get("host", "")),
            repo_root=str(payload.get("repo_root", "")),
            sources=sources,
            figures=figures,
            facts=payload.get("facts") or {},
            digest=str(payload.get("digest", "")),
            hypothetical=bool(payload.get("hypothetical", True)),
            order_sent=bool(payload.get("order_sent", False)),
            promotion=str(payload.get("promotion", "NONE")),
        )

    def verified(self) -> tuple[bool, str]:
        """Whether the digest matches the contents, checked the way a reader would."""
        recomputed = snapshot_digest(self.as_dict(with_digest=False))
        if not self.digest:
            return False, "the snapshot carries no digest of itself"
        if recomputed != self.digest:
            return False, (
                f"the snapshot's digest is {self.digest[:16]}… and its contents hash to "
                f"{recomputed[:16]}…: it was edited after it was taken"
            )
        return True, "the digest matches the contents"


def snapshot_digest(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "digest"}
    return sha256_text(canonical(body))


class _Collector:
    """Builds one snapshot: sources first, then figures that cite them by key."""

    def __init__(self, *, run_id: str, as_of_utc: str, host: str, repo_root: Path) -> None:
        self.run_id = run_id
        self.as_of_utc = as_of_utc
        self.host = host
        self.repo_root = repo_root
        self.sources: dict[str, Source] = {}
        self.figures: list[Figure] = []
        self.facts: dict[str, Any] = {}

    def source(self, key: str, path: Path, *, rows: int | None = None) -> Source:
        exists = path.is_file()
        entry = Source(
            path=str(path),
            bytes=path.stat().st_size if exists else 0,
            digest=sha256_file(path) if exists else "",
            rows=rows,
            as_of_utc=self.as_of_utc,
        )
        self.sources[key] = entry
        return entry

    def figure(
        self,
        name: str,
        value: Any,
        *,
        unit: str,
        source: str | Source,
        scope: str,
        note: str = "",
    ) -> None:
        body = self.sources[source] if isinstance(source, str) else source
        self.figures.append(
            Figure(
                name=name,
                value=value,
                unit=unit,
                run_id=self.run_id,
                as_of_utc=self.as_of_utc,
                source_artifact=body.path,
                source_digest=body.digest,
                measurement_scope=scope,
                note=note,
            )
        )

    def build(self) -> ReadingSnapshot:
        snapshot = ReadingSnapshot(
            schema_version=SCHEMA_VERSION,
            run_id=self.run_id,
            as_of_utc=self.as_of_utc,
            host=self.host,
            repo_root=str(self.repo_root),
            sources=dict(self.sources),
            figures=tuple(sorted(self.figures, key=lambda f: f.name)),
            facts=self.facts,
            digest="",
        )
        # The digest is taken over exactly what a reader gets back, so `verified()` is a real
        # check and not a ritual: any later edit to any figure changes it.
        return replace(
            snapshot, digest=snapshot_digest(snapshot.as_dict(with_digest=False))
        )


def _git(repo_root: Path, *args: str) -> str:
    import subprocess

    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), *args], capture_output=True, check=False
        )
    except OSError:
        return ""
    return result.stdout.decode("utf-8", "replace").strip()


def _count(rows: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get(key))
        counts[label] = counts.get(label, 0) + 1
    return counts


def collect(
    *,
    repo_root: Path,
    lane_state_root: Path,
    watch_state_root: Path,
    store_root: Path,
    inventory: Path | None = None,
    reclaim: Path | None = None,
    verification: Path | None = None,
    evidence_dir: Path | None = None,
    authority_map: Path | None = None,
    github: Path | None = None,
    tests: Path | None = None,
) -> ReadingSnapshot:
    """Read everything once, and tag every figure with where it came from."""
    instant = now_ms()
    as_of = stamp(instant)
    run_id = f"EDGE05R-READ-{as_of.replace('-', '').replace(':', '')}"
    collector = _Collector(
        run_id=run_id, as_of_utc=as_of, host=os.environ.get("COMPUTERNAME", "unknown"),
        repo_root=repo_root,
    )

    # ---- the volume ------------------------------------------------------ #
    volume = shutil.disk_usage(repo_root)
    disk_source = collector.source("volume", repo_root / "pyproject.toml")
    collector.figure(
        "volume_free_bytes",
        volume.free,
        unit="bytes",
        source=disk_source,
        scope=f"volume {repo_root.drive} as seen from the repository root",
        note="measured by the operating system at this instant, not read from a record",
    )
    collector.figure(
        "volume_free_gib",
        round(volume.free / GIB, 3),
        unit="GiB",
        source=disk_source,
        scope=f"volume {repo_root.drive}",
    )
    collector.figure(
        "volume_verdict",
        ("HEALTHY" if volume.free >= 5 * GIB else "ABOVE_CRITICAL_BELOW_HEALTHY"
         if volume.free >= 2 * GIB else "BELOW_CRITICAL"),
        unit="label",
        source=disk_source,
        scope="the two floors the lane's own guard declares (2 GiB and 5 GiB)",
    )

    # ---- the lane -------------------------------------------------------- #
    runs_path = lane_state_root / "runs.jsonl"
    runs = read_jsonl(runs_path)
    runs_source = collector.source("lane_runs", runs_path, rows=len(runs))
    outcomes = _count(runs, "outcome")
    collector.figure("lane_ticks_total", len(runs), unit="ticks", source=runs_source,
                     scope="every row of the lane's run log")
    for outcome in sorted(outcomes):
        collector.figure(
            f"lane_ticks_{outcome.lower()}",
            outcomes[outcome],
            unit="ticks",
            source=runs_source,
            scope=f"rows of the lane's run log whose outcome is {outcome}",
        )
    last = runs[-1] if runs else {}
    for name, value, unit in (
        ("lane_last_tick_utc", last.get("finished_at_utc") or last.get("started_at_utc"), "instant"),
        ("lane_last_outcome", last.get("outcome"), "label"),
        ("lane_last_new_bars", last.get("new_bars"), "bars"),
        ("lane_last_exit_code", last.get("exit_code"), "exit code"),
        ("lane_last_market_requests", last.get("market_requests"), "requests"),
        ("lane_last_parity_verdict", last.get("parity_verdict"), "label"),
        ("lane_last_ruleset_params_hash", (last.get("ruleset") or {}).get("params_hash"), "digest"),
        ("lane_last_health_status", last.get("health_status"), "label"),
    ):
        collector.figure(name, value, unit=unit, source=runs_source,
                         scope="the newest row of the lane's run log")
    refused = [row for row in runs if str(row.get("outcome")) == "DISK_BUDGET_EXCEEDED"]
    collector.figure(
        "lane_first_disk_refusal_utc",
        (refused[0].get("finished_at_utc") or refused[0].get("started_at_utc")) if refused else None,
        unit="instant",
        source=runs_source,
        scope="the first row of the lane's run log that refused on disk, if any",
    )
    # The one invariant that can be checked by reading: nothing here claims an order or a promotion.
    collector.figure(
        "lane_rows_claiming_an_order",
        sum(
            1
            for row in runs
            if row.get("order_sent") is True or str(row.get("promotion")) not in ("NONE", "None", "")
        ),
        unit="rows",
        source=runs_source,
        scope="every lane run row, checked for a sent order or a promotion",
    )

    slots = read_jsonl(lane_state_root / "slots.jsonl")
    slots_source = collector.source("lane_slots", lane_state_root / "slots.jsonl", rows=len(slots))
    collector.figure("lane_slot_seals", len(slots), unit="seals", source=slots_source,
                     scope="sealed slots in the lane's slot ledger")

    ledger = read_jsonl(lane_state_root / "ledger" / "INGEST_LEDGER.jsonl")
    ledger_source = collector.source(
        "ingest_ledger", lane_state_root / "ledger" / "INGEST_LEDGER.jsonl", rows=len(ledger)
    )
    collector.figure("ingest_ledger_rows", len(ledger), unit="attempts", source=ledger_source,
                     scope="every ingest attempt the lane recorded, one row per series and tick")
    collector.figure(
        "ingest_appended_bars",
        sum(int(row.get("appended") or 0) for row in ledger),
        unit="bars",
        source=ledger_source,
        scope="the `appended` field summed over every ingest attempt",
    )

    health = read_json(lane_state_root / "health.json")
    health_source = collector.source("lane_health", lane_state_root / "health.json")
    collector.figure("lane_health_status", health.get("status"), unit="label", source=health_source,
                     scope="the lane's own health file at this instant")
    collector.figure("lane_health_last_observation_utc", health.get("last_observation_utc"),
                     unit="instant", source=health_source, scope="the lane's own health file")

    # ---- the watchdog ---------------------------------------------------- #
    watch_path = watch_state_root / "watchdog.jsonl"
    readings = read_jsonl(watch_path)
    watch_source = collector.source("watchdog_readings", watch_path, rows=len(readings))
    verdicts = _count(readings, "verdict")
    categories = _count(readings, "category")
    collector.figure("watchdog_readings", len(readings), unit="readings", source=watch_source,
                     scope="every reading the watchdog has on file")
    for verdict in sorted(verdicts):
        collector.figure(
            f"watchdog_verdict_{verdict.lower()}", verdicts[verdict], unit="readings",
            source=watch_source, scope=f"readings whose verdict is {verdict}",
        )
    newest = readings[-1] if readings else {}
    for name, value, unit in (
        ("watchdog_newest_at_utc", newest.get("at_utc"), "instant"),
        ("watchdog_newest_verdict", newest.get("verdict"), "label"),
        ("watchdog_newest_category", newest.get("category"), "label"),
        ("watchdog_newest_schema", newest.get("schema_version"), "label"),
        ("watchdog_newest_cause", newest.get("cause"), "label"),
        ("watchdog_newest_operational_failure", newest.get("operational_failure"), "boolean"),
    ):
        collector.figure(name, value, unit=unit, source=watch_source,
                        scope="the newest reading on file")
    collector.figure(
        "watchdog_categories_seen",
        {key: categories[key] for key in sorted(categories)},
        unit="map",
        source=watch_source,
        scope="how many readings were filed under each category, over the whole log",
    )

    # The newest reading's own scheduler section, so a report can show how the same instant is
    # labelled rather than describe it: the UTC form and the platform's spelling are two fields of
    # one row, and the probe's answer lag is measured between two instants that row publishes.
    newest_task = (newest.get("checks") or {}).get("scheduler_task") or {}
    newest_cadence = (newest.get("checks") or {}).get("scheduler_cadence") or {}
    for name, value, unit in (
        ("watchdog_newest_scheduler_next_run_utc", newest_task.get("next_run_utc"), "instant"),
        (
            "watchdog_newest_scheduler_platform_spelling",
            newest_task.get("next_run_platform_spelling"),
            "label",
        ),
        (
            "watchdog_newest_probe_answer_lag_seconds",
            newest_cadence.get("probe_answer_lag_seconds"),
            "seconds",
        ),
        (
            "watchdog_newest_local_utc_offset_minutes",
            newest_cadence.get("local_utc_offset_minutes"),
            "minutes",
        ),
    ):
        collector.figure(
            name,
            value,
            unit=unit,
            source=watch_source,
            scope="the newest reading's own scheduler section",
        )

    # The volume's own drain, read from the watchdog's existing readings rather than from a new
    # probe: the watchdog already writes free bytes every fifteen minutes, so the trend costs
    # nothing to know and cannot be a different number from the one it recorded.
    disk_series = [
        (row.get("at_ms"), ((row.get("checks") or {}).get("resource_disk") or {}).get("free_bytes"))
        for row in readings
        if isinstance(row.get("at_ms"), int)
    ]
    disk_series = [(t, b) for t, b in disk_series if isinstance(b, int)]
    if len(disk_series) >= 2:
        (first_t, first_b), (last_t, last_b) = disk_series[0], disk_series[-1]
        hours = (last_t - first_t) / 3_600_000
        if hours > 0:
            collector.figure(
                "volume_free_bytes_first_watchdog_reading",
                first_b,
                unit="bytes",
                source=watch_source,
                scope="the oldest watchdog reading on file that recorded free space",
            )
            collector.figure(
                "volume_free_bytes_newest_watchdog_reading",
                last_b,
                unit="bytes",
                source=watch_source,
                scope="the newest watchdog reading that recorded free space",
            )
            collector.figure(
                "volume_change_bytes_per_hour",
                round((last_b - first_b) / hours, 1),
                unit="bytes per hour",
                source=watch_source,
                scope=(
                    f"the change in free space between the first and the newest footprint of "
                    f"{hours:.2f} h: negative means the volume is being consumed faster than it is "
                    "being returned, and this window contains the reclaim"
                ),
            )
        recent = disk_series[-3:]
        recent_hours = (recent[-1][0] - recent[0][0]) / 3_600_000
        if len(recent) == 3 and recent_hours > 0:
            collector.figure(
                "volume_change_bytes_per_hour_recent",
                round((recent[-1][1] - recent[0][1]) / recent_hours, 1),
                unit="bytes per hour",
                source=watch_source,
                scope="the same quantity over the newest three readings, after the reclaim",
            )

    alerts_path = watch_state_root / "watch_alerts.jsonl"
    alerts = read_jsonl(alerts_path)
    alerts_source = collector.source("watchdog_alerts", alerts_path, rows=len(alerts))
    kinds = _count(alerts, "kind")
    collector.figure("watchdog_alerts", len(alerts), unit="alerts", source=alerts_source,
                     scope="every alert row the watchdog appended, one per transition")
    collector.figure(
        "watchdog_rows_claiming_an_order",
        sum(
            1
            for row in readings
            if row.get("order_sent") is True or str(row.get("promotion")) not in ("NONE", "None", "")
        ),
        unit="rows",
        source=watch_source,
        scope="every watchdog reading, checked for a sent order or a promotion",
    )
    collector.figure("watchdog_alert_kinds", {key: kinds[key] for key in sorted(kinds)},
                     unit="map", source=alerts_source,
                     scope="alert rows grouped by kind")

    reconciliation = read_json(watch_state_root / "reconciliation" / "RECONCILIATION.json")
    recon_source = collector.source(
        "reconciliation", watch_state_root / "reconciliation" / "RECONCILIATION.json"
    )
    for name, value, unit in (
        ("reconciliation_verdict", reconciliation.get("verdict"), "label"),
        ("reconciliation_generated_at_utc", reconciliation.get("generated_at_utc"), "instant"),
        ("reconciliation_open_defects", len(reconciliation.get("open_defects") or []), "defects"),
        ("reconciliation_historical_defects", len(reconciliation.get("historical_defects") or []),
         "defects"),
        ("reconciliation_market_requests", reconciliation.get("market_requests"), "requests"),
        ("reconciliation_status", reconciliation.get("status"), "label"),
    ):
        collector.figure(name, value, unit=unit, source=recon_source,
                         scope="the newest reconciliation on file")
    seals = reconciliation.get("seals") or {}
    collector.figure("reconciliation_seals", seals.get("total"), unit="seals", source=recon_source,
                     scope="sealed slots the reconciliation accounted for")
    for name, value in (
        ("reconciliation_seals_missing_for_a_consuming_run",
         len(seals.get("missing_for_a_consuming_run") or [])),
        ("reconciliation_seals_of_an_unrecorded_run",
         len(seals.get("of_an_unrecorded_run") or [])),
        ("reconciliation_seals_orphaned", len(seals.get("orphaned") or [])),
    ):
        collector.figure(name, value, unit="seals", source=recon_source,
                         scope="the reconciliation's own seal accounting")
    restart = reconciliation.get("restart_proof") or {}
    collector.figure("restart_proof_broken", len(restart.get("broken") or []), unit="instances",
                     source=recon_source,
                     scope="instants where the second ingest pass appended a bar it should not have")
    collector.figure("restart_proof_instants_with_two_passes",
                     restart.get("instants_with_two_passes"), unit="instants", source=recon_source,
                     scope="market instants the lane ingested twice, as its own design does")
    chains = reconciliation.get("chains") or {}
    collector.figure(
        "reconciliation_chains_holding",
        sum(1 for body in chains.values() if body.get("chain_holds")),
        unit="series",
        source=recon_source,
        scope=f"of {len(chains)} series, how many chains the recomputation holds for",
    )
    collector.figure(
        "reconciliation_stored_bars",
        sum(int(body.get("stored_bars") or 0) for body in chains.values()),
        unit="bars",
        source=recon_source,
        scope="stored bars summed over the per-series chains",
    )
    collector.figure(
        "reconciliation_unattributed_bars",
        sum(int(body.get("unattributed_bars") or 0) for body in chains.values()),
        unit="bars",
        source=recon_source,
        scope="stored bars no recorded attempt claims, named rather than deleted",
    )
    for name, body in sorted((reconciliation.get("defect_counts") or {}).items()):
        collector.figure(f"defect_{str(name).lower()}", body, unit="count", source=recon_source,
                         scope="closed defect counts from the reconciliation")

    # ---- the store and the forward window -------------------------------- #
    store_files = sorted(store_root.glob("*/*.jsonl")) if store_root.is_dir() else []
    store_manifest = []
    bars = 0
    for path in store_files:
        rows = read_jsonl(path)
        bars += len(rows)
        store_manifest.append(
            {
                "series": f"{path.parent.name}:{path.stem}",
                "bytes": path.stat().st_size,
                "rows": len(rows),
                "digest": sha256_file(path),
            }
        )
    store_source = collector.source("store", store_root / "INGEST_LEDGER.jsonl")
    store_source = Source(
        path=str(store_root),
        bytes=sum(int(item["bytes"]) for item in store_manifest),
        digest=sha256_text(canonical(store_manifest)),
        rows=bars,
        as_of_utc=as_of,
    )
    collector.sources["store"] = store_source
    collector.figure("store_series", len(store_manifest), unit="series", source=store_source,
                     scope="every series file in the forward store")
    collector.figure("store_bars", bars, unit="bars", source=store_source,
                     scope="every stored closed bar, summed over the series")
    collector.facts["store_manifest"] = store_manifest

    coverage = read_json(lane_state_root / "coverage.json")
    coverage_source = collector.source("coverage", lane_state_root / "coverage.json")
    for name, value, unit in (
        ("forward_days_with_data", coverage.get("days_with_any_data"), "days"),
        ("forward_days_prospectively_observed", coverage.get("prospectively_observed"), "days"),
        ("forward_days_densely_covered_but_backfilled",
         coverage.get("densely_covered_but_backfilled"), "days"),
        ("forward_days_required", coverage.get("required_days"), "days"),
        ("forward_days_observed_window", coverage.get("window_observation_days"), "days"),
        ("forward_days_remaining", coverage.get("remaining_days"), "days"),
        ("forward_coverage_required", coverage.get("coverage_required"), "ratio"),
        ("forward_epoch_utc", coverage.get("epoch_utc"), "instant"),
        ("forward_freeze", coverage.get("freeze"), "label"),
    ):
        collector.figure(name, value, unit=unit, source=coverage_source,
                         scope="the lane's own coverage file: what it counts and what it refuses")

    if inventory is not None:
        entry = collector.source("storage_inventory", inventory)
        body = read_json(inventory)
        collector.figure("storage_safe_reclaimable_bytes",
                         (body.get("reclaim_plan") or {}).get("safe_reclaimable_bytes"),
                         unit="bytes", source=entry,
                         scope="tool caches proven untracked and gitignored at that reading")
        collector.figure("storage_repo_bytes", (body.get("totals") or {}).get("repo_bytes"),
                         unit="bytes", source=entry, scope="every file under the repository root")
    if reclaim is not None:
        entry = collector.source("storage_reclaim", reclaim)
        body = read_json(reclaim)
        volume_body = body.get("volume") or {}
        collector.figure("storage_reclaimed_bytes", body.get("reclaimed_bytes"), unit="bytes",
                         source=entry, scope="bytes removed by the reclaim, measured by the OS")
        collector.figure("storage_free_bytes_after", volume_body.get("free_bytes_after"),
                         unit="bytes", source=entry,
                         scope="free space after the reclaim, from the OS")
        collector.figure("storage_verdict_after", volume_body.get("verdict_after"), unit="label",
                         source=entry, scope="the floor the volume stood at after the reclaim")
    if verification is not None:
        entry = collector.source("verification", verification)
        body = read_json(verification)
        collector.figure("verification_verdict", body.get("verdict"), unit="label", source=entry,
                         scope="the independent verifier's own verdict on the latest state")
        collector.figure("verification_self_test",
                         (body.get("self_test") or {}).get("verdict"), unit="label",
                         source=entry, scope="how many sabotages the matrix caught")
        collector.figure("verification_generated_at_utc", body.get("generated_at_utc"),
                         unit="instant", source=entry, scope="when the verifier read the state")

    if tests is not None:
        entry = collector.source("regression", tests)
        body = read_json(tests)
        chain = body.get("chain") or {}
        full = body.get("full") or {}
        chain_counts = chain.get("counts") or {}
        full_counts = full.get("counts") or {}
        collector.figure(
            "tests_chain_passed", chain_counts.get("passed"), unit="tests", source=entry,
            scope="the forward chain's three suites: the lane's, the watchdog's, the reconciliation's",
        )
        collector.figure(
            "tests_chain_failed", chain_counts.get("failed"), unit="tests", source=entry,
            scope="failures in the forward chain's suites",
        )
        collector.figure(
            "tests_chain_exit_code", chain.get("exit_code"), unit="exit code", source=entry,
            scope="the test command's own exit status, not a summary of it",
        )
        collector.figure(
            "tests_full_passed", full_counts.get("passed"), unit="tests", source=entry,
            scope="every test under tests/unit/research, run in one invocation",
        )
        collector.figure(
            "tests_full_failed", full_counts.get("failed"), unit="tests", source=entry,
            scope="failures anywhere in the research suite, this work package's or not",
        )
        collector.figure(
            "tests_full_exit_code", full.get("exit_code"), unit="exit code", source=entry,
            scope="the whole-suite command's own exit status",
        )
        collector.figure(
            "tests_unexplained_failures",
            len(body.get("unexplained") or []),
            unit="tests",
            source=entry,
            scope="failures for which no cause was demonstrated",
        )
        collector.facts["regression"] = body
    if authority_map is not None:
        entry = collector.source("runtime_authority_map", authority_map)
        collector.figure("runtime_authority_map_bytes", entry.bytes, unit="bytes", source=entry,
                         scope="this work package's own runtime authority map, as written")
    if github is not None:
        entry = collector.source("github_state", github)
        body = read_json(github)
        collector.figure("github_push_state", body.get("push_state"), unit="label", source=entry,
                         scope="the recorded result of the publication probe, not re-probed here")
        collector.figure("github_probe_exit_code", body.get("probe_exit_code"), unit="exit code",
                         source=entry, scope="the probe's own exit status")
    if evidence_dir is not None and (evidence_dir / "OUTAGE_DETECT_1.txt").is_file():
        entry = collector.source("outage_detect", evidence_dir / "OUTAGE_DETECT_1.txt")
        collector.figure(
            "watchdog_detection_latency_seconds",
            6.0,
            unit="seconds",
            source=entry,
            scope=(
                "the induced-outage rehearsal of 2026-10-13 18:48Z: the watchdog's own two "
                "readings around the stop, quoted from that evidence file"
            ),
            note="a historical measurement, cited with its file and digest rather than re-derived",
        )

    # ---- the repository --------------------------------------------------- #
    git_source = collector.source("git", repo_root / ".git" / "HEAD")
    head = _git(repo_root, "rev-parse", "HEAD")
    branch = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD")
    status = _git(repo_root, "status", "--porcelain")
    base = _git(repo_root, "rev-list", "--max-parents=0", "HEAD")
    count = _git(repo_root, "rev-list", "--count", f"{base}..HEAD") if base else ""
    for name, value, unit, scope in (
        ("git_head", head, "commit", "the commit the reading was taken at"),
        ("git_branch", branch, "label", "the branch the reading was taken on"),
        ("git_commits_since_root", int(count) if str(count).strip().isdigit() else None,
         "commits", "commits reachable from HEAD since the root commit"),
        ("git_dirty_entries", len(status.splitlines()) if status else 0, "paths",
         "lines of `git status --porcelain`: every change, whoever made it"),
    ):
        collector.figure(name, value, unit=unit, source=git_source, scope=scope)

    # ---- the timeline, every row tagged with this reading ----------------- #
    collector.facts["timeline"] = sorted(
        [
            {
                "as_of_utc": as_of,
                "run_id": run_id,
                "instant_utc": str(row.get("finished_at_utc") or row.get("started_at_utc") or ""),
                "actor": "lane",
                "what": (
                    f"{row.get('outcome')} · {row.get('new_bars')} new bar(s) · "
                    f"{row.get('market_requests')} request(s) · slot {row.get('slot_key')}"
                ),
            }
            for row in runs
        ]
        + [
            {
                "as_of_utc": as_of,
                "run_id": run_id,
                "instant_utc": str(row.get("at_utc") or ""),
                "actor": "watchdog",
                "what": (
                    f"{row.get('verdict')} ({row.get('category')}) · cause {row.get('cause')}"
                ),
            }
            for row in readings
        ]
        + [
            {
                "as_of_utc": as_of,
                "run_id": run_id,
                "instant_utc": str(row.get("at_utc") or ""),
                "actor": "alert",
                "what": f"{row.get('kind')} {row.get('state')} ({row.get('severity')})",
            }
            for row in alerts
        ],
        key=lambda row: (str(row["instant_utc"]), str(row["actor"])),
    )
    collector.facts["newest_checks"] = (newest.get("checks") or {})
    collector.facts["newest_findings"] = newest.get("findings") or []
    collector.facts["newest_warnings"] = newest.get("warnings") or []
    collector.facts["lane_disk_record"] = (last.get("disk") or {})
    return collector.build()
