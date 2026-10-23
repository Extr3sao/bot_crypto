"""Continuous PAPER operation: heartbeat, daily report, safe stop (§13-§15, §47, §51).

The runtime already knows how to run *a* cycle. This module is what lets it run
*for days*: it publishes a heartbeat an operator can read without parsing traces,
folds the run into a daily report, and provides a stop that flushes the state
rather than a stop that kills the process.

Three deliberate choices:

* a heartbeat is written **after** the cycle it describes, so it can never claim
  progress that did not happen;
* the heartbeat exists both as an append-only log (what happened, in order) and
  as a single atomically-replaced file (what is true right now), because those
  are different questions and one file cannot answer both;
* the stop signal is a file *and* a signal handler, because a portable supervisor
  should not have to guess which one its platform delivers.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

__all__ = [
    "PAPER_DAILY_REPORT_SCHEMA_VERSION",
    "PAPER_HEARTBEAT_SCHEMA_VERSION",
    "STOP_FILE_NAME",
    "ArtifactWriteFailures",
    "HeartbeatWriter",
    "PaperHeartbeat",
    "StopController",
    "build_daily_report",
    "durable_write",
    "render_daily_report_markdown",
    "wait_for_stop_file",
    "write_daily_report",
]

PAPER_HEARTBEAT_SCHEMA_VERSION: Final[str] = "paper-heartbeat-v1"
PAPER_DAILY_REPORT_SCHEMA_VERSION: Final[str] = "paper-daily-report-v1"
STOP_FILE_NAME: Final[str] = "STOP"


@dataclass(slots=True)
class ArtifactWriteFailures:
    """Storage failures the PAPER loop survived, in the order they happened (§22).

    PAPER is a decision process; its reports, traces and heartbeats are evidence,
    not its purpose. On a host where a research capture and PAPER share a volume,
    the capture filling it must degrade PAPER's evidence — never stop PAPER, and
    never leave an operator without a reason.
    """

    failures: list[str] = field(default_factory=list)

    def record(self, what: str, exc: BaseException) -> str:
        message = f"{what}: {type(exc).__name__}: {exc}"
        self.failures.append(message)
        return message

    @property
    def count(self) -> int:
        return len(self.failures)

    def recent(self, limit: int = 5) -> tuple[str, ...]:
        return tuple(self.failures[-limit:])


def durable_write(write: Any, *, what: str, failures: ArtifactWriteFailures) -> Any:
    """Run an artifact write; a storage failure is recorded, never fatal.

    Returns whatever the write returned, or ``None`` when it could not complete.
    Only ``OSError`` is treated this way, because a full disk is an operational
    condition (``ENOSPC``), while a bug in our own serialisation is not: those must
    still surface.
    """
    try:
        return write()
    except OSError as exc:
        message = failures.record(what, exc)
        print(f"[paper] {message}", file=sys.stderr)
        return None


def wait_for_stop_file(
    stop_file: Path | None,
    seconds: float,
    *,
    chunk_seconds: float = 1.0,
) -> bool:
    """Sleep ``seconds`` in short slices, waking early when the stop file appears.

    A long-lived worker has to notice a supervisor's stop request without
    finishing a five-minute nap first, and it has to notice it *portably*: on
    Windows the supervisor cannot send a signal, so the file is the only channel.
    ``True`` means stop now; ``False`` means the sleep ran out.
    """
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        if stop_file is not None and stop_file.exists():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(chunk_seconds, remaining))


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


@dataclass(frozen=True, slots=True)
class PaperHeartbeat:
    """§14 — one cycle, in the words an operator needs."""

    run_id: str
    cycle: int
    timestamp_ms: int
    assets: tuple[str, ...]
    timeframe: str
    strategies_evaluated: int
    decisions: int
    no_trade: int
    no_trade_kinds: dict[str, int]
    shadow_trades: int
    paper_trades: int
    risk_vetoes: int
    runtime_failures: int
    errors: tuple[str, ...]
    cycles_completed: int
    uptime_seconds: float
    state_age_seconds: float | None
    paper_candidates: tuple[str, ...] = ()
    #: §22 — artifact writes that failed. PAPER keeps deciding when the disk is
    #: full: it is not a storage service, and a research volume filling up must
    #: never take the PAPER loop down with it.
    storage_failures: int = 0
    storage_errors: tuple[str, ...] = ()
    mode: str = "PAPER"
    timestamp_iso: str = ""
    schema_version: str = PAPER_HEARTBEAT_SCHEMA_VERSION

    @classmethod
    def from_cycle(
        cls,
        *,
        run_id: str,
        cycle: int,
        report: Any,
        started_at_ms: int,
        timeframe: str,
        paper_candidates: tuple[str, ...] | list[str] = (),
        state_age_seconds: float | None = None,
        now_ms: int | None = None,
    ) -> PaperHeartbeat:
        """Project one ``CycleReport`` into a heartbeat.

        Everything is counted from the report itself: nothing here can add a
        trade or a strategy that the cycle did not produce.
        """
        now = int(time.time() * 1000) if now_ms is None else now_ms
        rows = list(getattr(report, "assets", ()) or ())
        vetoes = sum(1 for row in rows if str(getattr(row, "risk_state", "")) == "VETOED")
        return cls(
            run_id=run_id,
            cycle=cycle,
            timestamp_ms=now,
            timestamp_iso=_iso(now),
            assets=tuple(sorted({str(getattr(row, "asset", "")) for row in rows})),
            timeframe=timeframe,
            strategies_evaluated=sum(
                len(getattr(row, "strategies_considered", ()) or ()) for row in rows
            ),
            decisions=len(rows),
            no_trade=int(getattr(report, "no_trades", 0)),
            no_trade_kinds=dict(getattr(report, "no_trade_kinds", {}) or {}),
            shadow_trades=int(getattr(report, "shadow_trades", 0)),
            paper_trades=int(getattr(report, "paper_trades", 0)),
            risk_vetoes=vetoes,
            runtime_failures=int(getattr(report, "runtime_failures", 0)),
            errors=tuple(getattr(report, "errors", ()) or ()),
            cycles_completed=cycle,
            uptime_seconds=round(max(0.0, (now - started_at_ms) / 1000.0), 3),
            state_age_seconds=state_age_seconds,
            paper_candidates=tuple(paper_candidates),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "mode": self.mode,
            "cycle": self.cycle,
            "timestamp_ms": self.timestamp_ms,
            "timestamp_iso": self.timestamp_iso or _iso(self.timestamp_ms),
            "assets": list(self.assets),
            "timeframe": self.timeframe,
            "strategies_evaluated": self.strategies_evaluated,
            "decisions": self.decisions,
            "no_trade": self.no_trade,
            "no_trade_kinds": dict(sorted(self.no_trade_kinds.items())),
            "shadow_trades": self.shadow_trades,
            "paper_trades": self.paper_trades,
            "risk_vetoes": self.risk_vetoes,
            "runtime_failures": self.runtime_failures,
            "errors": list(self.errors),
            "cycles_completed": self.cycles_completed,
            "uptime_seconds": self.uptime_seconds,
            "state_age_seconds": self.state_age_seconds,
            "paper_candidates": list(self.paper_candidates),
            "storage_failures": self.storage_failures,
            "storage_errors": list(self.storage_errors[-5:]),
        }


@dataclass(slots=True)
class HeartbeatWriter:
    """Append-only heartbeat log plus an atomically replaced "current" file."""

    run_dir: Path
    log_name: str = "heartbeat.jsonl"
    current_name: str = "heartbeat.json"
    written: int = 0
    last: PaperHeartbeat | None = None

    @property
    def log_path(self) -> Path:
        return self.run_dir / self.log_name

    @property
    def current_path(self) -> Path:
        return self.run_dir / self.current_name

    def write(self, heartbeat: PaperHeartbeat) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        payload = heartbeat.to_dict()
        if heartbeat.storage_failures:
            payload["storage_failures"] = heartbeat.storage_failures
        line = json.dumps(payload, ensure_ascii=False, sort_keys=False)
        with self.log_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line + "\n")
        tmp = self.current_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, self.current_path)
        self.written += 1
        self.last = heartbeat

    def read_log(self) -> list[dict[str, Any]]:
        if not self.log_path.exists():
            return []
        records: list[dict[str, Any]] = []
        with self.log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records


@dataclass(slots=True)
class StopController:
    """§51 — ask the loop to stop after the cycle it is in, and no sooner."""

    run_dir: Path
    reason: str | None = None
    installed: tuple[str, ...] = ()
    stop_file_name: str = STOP_FILE_NAME

    @property
    def stop_path(self) -> Path:
        return self.run_dir / self.stop_file_name

    @property
    def stopped(self) -> bool:
        return self.reason is not None or self.stop_path.exists()

    def request(self, reason: str) -> None:
        """Record why the loop should stop (first reason wins)."""
        if self.reason is None:
            self.reason = reason

    def install(self) -> tuple[str, ...]:
        """Install SIGINT/SIGTERM handlers on the main thread when possible."""
        if os.name == "nt":  # pragma: no cover - platform dependent
            installed: list[str] = []
            for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
                sig = getattr(signal, name, None)
                if sig is None:
                    continue
                try:
                    signal.signal(sig, lambda signum, frame: self.request(f"signal {signum}"))
                    installed.append(name)
                except (ValueError, OSError):
                    continue
            self.installed = tuple(installed)
            return self.installed
        installed = []
        for name in ("SIGINT", "SIGTERM"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, lambda signum, frame: self.request(f"signal {signum}"))
                installed.append(name)
            except (ValueError, OSError):  # pragma: no cover - non-main thread
                continue
        self.installed = tuple(installed)
        return self.installed

    def clear_stop_file(self) -> None:
        self.stop_path.unlink(missing_ok=True)


def build_daily_report(
    *,
    run_id: str,
    timeframe: str,
    assets: tuple[str, ...] | list[str],
    started_at_ms: int,
    cycles: list[Any],
    totals: dict[str, int],
    paper_candidates: tuple[str, ...] | list[str] = (),
    performance: list[dict[str, Any]] | None = None,
    outcomes: list[dict[str, Any]] | None = None,
    errors: list[str] | None = None,
    restarts: list[dict[str, Any]] | None = None,
    now_ms: int | None = None,
    report_date: str | None = None,
) -> dict[str, Any]:
    """§15/§47 — the day's PAPER activity, including the boring parts.

    ``strategy_attribution`` is per strategy, not per family, because the point
    of attribution is to know *which* admitted strategy produced a result —
    including the honest answer "none of them produced anything yet".
    """
    now = int(time.time() * 1000) if now_ms is None else now_ms
    report_date = report_date or datetime.fromtimestamp(now / 1000, tz=UTC).strftime("%Y-%m-%d")
    attribution: dict[str, dict[str, Any]] = {}
    for cycle in cycles:
        for row in getattr(cycle, "assets", ()) or ():
            strategy_id = getattr(row, "strategy_selected", None)
            if not strategy_id:
                continue
            cell = attribution.setdefault(
                str(strategy_id),
                {
                    "decisions": 0,
                    "paper_trades": 0,
                    "shadow_trades": 0,
                    "no_trade": 0,
                    "risk_vetoes": 0,
                    "outcomes_resolved": 0,
                    "limitations": "per-strategy PnL is not attributed yet (no admitted strategy has traded)",
                },
            )
            cell["decisions"] += 1
            mode = str(getattr(row, "mode", ""))
            if mode == "TRADE_PAPER":
                cell["paper_trades"] += 1
            elif mode == "SHADOW_TRADE":
                cell["shadow_trades"] += 1
            elif mode == "NO_TRADE":
                cell["no_trade"] += 1
            if str(getattr(row, "risk_state", "")) == "VETOED":
                cell["risk_vetoes"] += 1
            if bool(getattr(row, "order_created", False)):
                cell["outcomes_resolved"] += 0

    resolved_outcomes = [o for o in (outcomes or []) if o.get("status") == "RESOLVED"]
    pnl_values = [
        float(o["pnl"]) for o in resolved_outcomes if isinstance(o.get("pnl"), int | float)
    ]
    gross = sum(pnl_values) if pnl_values else 0.0
    peak = 0.0
    trough = 0.0
    equity = 0.0
    for value in pnl_values:
        equity += value
        peak = max(peak, equity)
        trough = min(trough, equity - peak)
    return {
        "schema_version": PAPER_DAILY_REPORT_SCHEMA_VERSION,
        "report_date": report_date,
        "generated_at_ms": now,
        "generated_at_iso": _iso(now),
        "run_id": run_id,
        "mode": "PAPER",
        "timeframe": timeframe,
        "assets": list(assets),
        "runtime_hours": round(max(0.0, (now - started_at_ms) / 3_600_000), 6),
        "cycles": len(cycles),
        "decisions": int(totals.get("asset_cycle_evaluations", 0)),
        "no_trade": int(totals.get("no_trades", 0)),
        "no_trade_kinds": {
            key: value
            for key, value in sorted(totals.items())
            if key.startswith("no_trade_") and value
        },
        "shadow_trades": int(totals.get("shadow_trades", 0)),
        "paper_trades": int(totals.get("paper_trades", 0)),
        "orders_created": int(totals.get("orders_created", 0)),
        "pnl": {
            "gross_bps_total": round(gross, 6),
            "resolved_outcomes": len(resolved_outcomes),
            "pending_outcomes": int(totals.get("outcomes_pending", 0)),
            "note": "PAPER only; no capital, no live orders. 0 trades is a PASS.",
        },
        "drawdown": {
            "max_drawdown_bps": round(trough, 6),
            "note": "computed from resolved PAPER outcomes only",
        },
        "strategy_attribution": attribution,
        "risk_events": {
            key: value for key, value in sorted(totals.items()) if key.startswith("risk_") and value
        },
        "runtime_failures": int(totals.get("runtime_failures", 0)),
        "errors": list(errors or []),
        "restarts": list(restarts or []),
        "outcomes": {
            "resolved": len(resolved_outcomes),
            "pending": int(totals.get("outcomes_pending", 0)),
            "performance_cells": len(performance or []),
        },
        "paper_candidates": list(paper_candidates),
        "no_trade_is_expected": (
            "No strategy is admitted for PAPER, so the correct behaviour is "
            "NO_TRADE with zero trades."
            if not paper_candidates
            else "At least one strategy is admitted; PAPER trades are expected when it emits."
        ),
    }


def render_daily_report_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# PAPER DAILY REPORT — {payload['report_date']}",
        "",
        "```text",
        f"run_id:        {payload['run_id']}",
        f"mode:          {payload['mode']} (no live path)",
        f"timeframe:     {payload['timeframe']}",
        f"assets:        {', '.join(payload['assets'])}",
        f"runtime_hours: {payload['runtime_hours']}",
        f"cycles:        {payload['cycles']}",
        f"decisions:     {payload['decisions']}",
        f"NO_TRADE:      {payload['no_trade']}",
        f"SHADOW:        {payload['shadow_trades']}",
        f"PAPER trades:  {payload['paper_trades']}",
        f"orders:        {payload['orders_created']}",
        f"failures:      {payload['runtime_failures']}",
        f"candidates:    {', '.join(payload['paper_candidates']) or 'NONE'}",
        "```",
        "",
        f"_{payload['no_trade_is_expected']}_",
        "",
    ]
    if payload.get("no_trade_kinds"):
        lines.append("## Why NO_TRADE")
        lines.append("")
        for kind, count in payload["no_trade_kinds"].items():
            lines.append(f"- `{kind}`: {count}")
        lines.append("")
    if payload.get("strategy_attribution"):
        lines.append("## Strategy attribution")
        lines.append("")
        for strategy_id, cell in sorted(payload["strategy_attribution"].items()):
            lines.append(
                f"- `{strategy_id}`: decisions={cell['decisions']} paper={cell['paper_trades']} "
                f"shadow={cell['shadow_trades']} no_trade={cell['no_trade']} "
                f"vetoes={cell['risk_vetoes']}"
            )
        lines.append("")
    if payload.get("errors"):
        lines.append("## Errors")
        lines.append("")
        for error in payload["errors"][:50]:
            lines.append(f"- {error}")
        lines.append("")
    return "\n".join(lines)


def write_daily_report(
    run_dir: Path | str, payload: dict[str, Any], *, stem: str = "PAPER_DAILY_REPORT"
) -> tuple[Path, Path]:
    directory = Path(run_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / f"{stem}.json"
    md_path = directory / f"{stem}.md"
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(render_daily_report_markdown(payload), encoding="utf-8")
    return md_path, json_path
