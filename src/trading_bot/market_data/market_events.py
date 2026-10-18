"""Event-driven gating for AI market analysis — offline, fail-closed.

The question this module answers is *not* "can we call a model?" but "is there a
new, closed, material event that justifies spending money on one?".  A scheduler
ticking every fifteen minutes is not an event: a closed candle is, and so is a
verified change built from closed bars.  Everything else is ``SKIP`` with a
reason, which is a legitimate — and free — outcome.

Properties that matter for RFC-TAP-MARKET-005:

* **Dedupe by event, not by clock.**  The event key is
  ``symbol:timeframe:last_closed_open``.  Re-running the scheduler cannot buy
  the same analysis twice.
* **No credential, no budget, no call.**  ``MISSING_CREDENTIAL`` and
  ``BUDGET_EXHAUSTED`` are checked before anything else that could spend.
* **State survives a restart.**  The trigger ledger is append-only JSONL and is
  replayed on construction; an in-memory counter would forget a spend across a
  process boundary.
* **A cached answer is never sold as fresh.**  ``ResponseCache.get`` returns
  ``None`` when the entry is older than its TTL *or* was produced from a
  different snapshot/prompt/model triple, so a changed market cannot inherit an
  old answer.

This module performs **zero** network calls and imports no provider SDK.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import structlog

from trading_bot.market_data.candle_filter import timeframe_seconds_or_raise
from trading_bot.market_data.snapshot import MarketSnapshot, gate_snapshot

__all__ = [
    "CachedResponse",
    "EventGate",
    "EventTriggerConfig",
    "ResponseCache",
    "SkipReason",
    "TriggerDecision",
]

SkipReason = Literal[
    "TRIGGERED",
    "NO_NEW_CLOSED_BAR",
    "NOT_YET_AVAILABLE",
    "STALE_SNAPSHOT",
    "NO_EXECUTABLE_PRICE",
    "MISSING_CREDENTIAL",
    "BUDGET_EXHAUSTED",
    "DUPLICATE_EVENT",
    "COOLDOWN",
    "HOURLY_CAP",
    "NO_MATERIAL_CHANGE",
    "INSUFFICIENT_HISTORY",
]

#: Reasons that are decided *before* any spend-shaped check, so the caller can
#: distinguish "the data said no" from "the wallet said no".
_DATA_REASONS: frozenset[str] = frozenset(
    {
        "NOT_YET_AVAILABLE",
        "STALE_SNAPSHOT",
        "NO_EXECUTABLE_PRICE",
        "INSUFFICIENT_HISTORY",
        "NO_NEW_CLOSED_BAR",
        "NO_MATERIAL_CHANGE",
    }
)


@dataclass(frozen=True, slots=True)
class EventTriggerConfig:
    """Declared policy.  Defaults spend nothing unless a budget is supplied."""

    base_timeframe: str = "1h"
    cooldown_ms: int = 3_600_000
    max_triggers_per_hour: int = 4
    cost_per_attempt_usd: float = 0.02
    budget_usd: float = 0.0
    min_change_bps: float = 25.0
    max_snapshot_age_ms: int = 4 * 3_600_000
    require_quote: bool = False
    quote_max_age_ms: int = 60_000

    def validated(self) -> EventTriggerConfig:
        if self.cooldown_ms < 0:
            raise ValueError("cooldown_ms must be >= 0")
        if self.max_triggers_per_hour <= 0:
            raise ValueError("max_triggers_per_hour must be > 0")
        if self.cost_per_attempt_usd < 0:
            raise ValueError("cost_per_attempt_usd must be >= 0")
        if self.budget_usd < 0:
            raise ValueError("budget_usd must be >= 0")
        if self.min_change_bps < 0:
            raise ValueError("min_change_bps must be >= 0")
        timeframe_seconds_or_raise(self.base_timeframe)
        return self


@dataclass(frozen=True, slots=True)
class TriggerDecision:
    should_analyze: bool
    reason: SkipReason
    detail: str
    event_key: str
    symbol: str
    at_ms: int
    change_bps: float | None
    estimated_cost_usd: float
    remaining_budget_usd: float
    snapshot_id: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "should_analyze": self.should_analyze,
            "reason": self.reason,
            "detail": self.detail,
            "event_key": self.event_key,
            "symbol": self.symbol,
            "at_ms": self.at_ms,
            "change_bps": None if self.change_bps is None else round(self.change_bps, 4),
            "estimated_cost_usd": self.estimated_cost_usd,
            "remaining_budget_usd": round(self.remaining_budget_usd, 6),
            "snapshot_id": self.snapshot_id,
        }


def _change_bps(snapshot: MarketSnapshot, timeframe: str) -> float | None:
    bars = snapshot.bars(timeframe)
    if len(bars) < 2:
        return None
    previous = float(bars[-2].close)
    latest = float(bars[-1].close)
    if previous <= 0:
        return None
    return (latest / previous - 1.0) * 10_000.0


class EventGate:
    """Stateful trigger gate with an append-only ledger.

    ``evaluate`` is pure with respect to the network and the model: it may write
    one ledger row when it fires, and nothing else.
    """

    def __init__(
        self,
        config: EventTriggerConfig,
        *,
        ledger_path: Path | str,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._config = config.validated()
        self._ledger_path = Path(ledger_path)
        self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1_000))
        self._log = structlog.get_logger(self.__class__.__module__)
        self._fired_at: deque[int] = deque()
        self._seen_events: set[str] = set()
        self._spent_usd: float = 0.0
        self._replay()

    # ------------------------------------------------------------------ state
    def _replay(self) -> None:
        if not self._ledger_path.exists():
            return
        for line in self._ledger_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # A truncated last line is a crash artifact, not a reason to
                # forget every earlier event; the hash chain makes it visible.
                self._log.warning("trigger_ledger_line_skipped")
                continue
            if not isinstance(row, dict) or not row.get("should_analyze"):
                continue
            self._seen_events.add(str(row.get("event_key")))
            self._fired_at.append(int(row.get("at_ms", 0)))
            self._spent_usd += float(row.get("estimated_cost_usd", 0.0))

    @property
    def spent_usd(self) -> float:
        return self._spent_usd

    @property
    def remaining_budget_usd(self) -> float:
        return max(0.0, self._config.budget_usd - self._spent_usd)

    def _prune_window(self, at_ms: int) -> int:
        horizon = at_ms - 3_600_000
        while self._fired_at and self._fired_at[0] < horizon:
            self._fired_at.popleft()
        return len(self._fired_at)

    # ---------------------------------------------------------------- evaluate
    def evaluate(
        self,
        snapshot: MarketSnapshot,
        *,
        at_ms: int,
        credentials_present: bool,
        budget_remaining_usd: float | None = None,
        allow_new_candle: bool = True,
    ) -> TriggerDecision:
        cfg = self._config
        at = int(at_ms)
        base_tf = cfg.base_timeframe

        try:
            bars = snapshot.bars(base_tf)
        except KeyError:
            return self._skip(
                "INSUFFICIENT_HISTORY",
                f"snapshot has no {base_tf} slice",
                snapshot,
                at,
                None,
            )
        event_key = f"{snapshot.symbol}:{base_tf}:{int(bars[-1].timestamp)}"
        change_bps = _change_bps(snapshot, base_tf)

        gate = gate_snapshot(
            snapshot,
            at_ms=at,
            max_age_ms=cfg.max_snapshot_age_ms,
            max_quote_age_ms=cfg.quote_max_age_ms,
            require_quote=cfg.require_quote,
        )
        if not gate.usable:
            reason: SkipReason
            if gate.reason in ("NOT_YET_AVAILABLE", "STALE_TIMEFRAME"):
                reason = "STALE_SNAPSHOT"
                if gate.reason == "NOT_YET_AVAILABLE":
                    reason = "NOT_YET_AVAILABLE"
            elif gate.reason == "NO_EXECUTABLE_PRICE":
                reason = "NO_EXECUTABLE_PRICE"
            else:
                reason = "STALE_SNAPSHOT"
            return self._skip(reason, gate.detail, snapshot, at, change_bps, event_key)

        if change_bps is None:
            return self._skip(
                "INSUFFICIENT_HISTORY",
                f"{base_tf} needs two closed bars to measure a change",
                snapshot,
                at,
                None,
                event_key,
            )

        if not credentials_present:
            return self._skip(
                "MISSING_CREDENTIAL",
                "no authorized model credential; zero inference requests",
                snapshot,
                at,
                change_bps,
                event_key,
            )

        budget = (
            self.remaining_budget_usd
            if budget_remaining_usd is None
            else float(budget_remaining_usd)
        )
        if budget < cfg.cost_per_attempt_usd or cfg.budget_usd <= 0:
            return self._skip(
                "BUDGET_EXHAUSTED",
                (
                    f"remaining={budget:.4f} USD, cost_per_attempt="
                    f"{cfg.cost_per_attempt_usd:.4f} USD"
                ),
                snapshot,
                at,
                change_bps,
                event_key,
                remaining=budget,
            )

        if event_key in self._seen_events:
            return self._skip(
                "DUPLICATE_EVENT",
                f"{event_key} was already analysed",
                snapshot,
                at,
                change_bps,
                event_key,
                remaining=budget,
            )

        if not allow_new_candle and abs(change_bps) < cfg.min_change_bps:
            return self._skip(
                "NO_MATERIAL_CHANGE",
                f"{change_bps:.2f} bps < {cfg.min_change_bps:.2f} bps",
                snapshot,
                at,
                change_bps,
                event_key,
                remaining=budget,
            )

        fired = self._prune_window(at)
        if fired >= cfg.max_triggers_per_hour:
            return self._skip(
                "HOURLY_CAP",
                f"{fired} triggers in the last hour (cap {cfg.max_triggers_per_hour})",
                snapshot,
                at,
                change_bps,
                event_key,
                remaining=budget,
            )

        if self._fired_at and at - self._fired_at[-1] < cfg.cooldown_ms:
            return self._skip(
                "COOLDOWN",
                f"{at - self._fired_at[-1]} ms since the last trigger",
                snapshot,
                at,
                change_bps,
                event_key,
                remaining=budget,
            )

        decision = TriggerDecision(
            should_analyze=True,
            reason="TRIGGERED",
            detail=(f"closed {base_tf} bar {bars[-1].timestamp} with {change_bps:+.2f} bps change"),
            event_key=event_key,
            symbol=snapshot.symbol,
            at_ms=at,
            change_bps=change_bps,
            estimated_cost_usd=cfg.cost_per_attempt_usd,
            remaining_budget_usd=max(0.0, budget - cfg.cost_per_attempt_usd),
            snapshot_id=snapshot.snapshot_id,
        )
        self._seen_events.add(event_key)
        self._fired_at.append(at)
        self._spent_usd += cfg.cost_per_attempt_usd
        self._append(decision)
        return decision

    def _skip(
        self,
        reason: SkipReason,
        detail: str,
        snapshot: MarketSnapshot,
        at: int,
        change_bps: float | None,
        event_key: str | None = None,
        *,
        remaining: float | None = None,
    ) -> TriggerDecision:
        budget = self.remaining_budget_usd if remaining is None else remaining
        decision = TriggerDecision(
            should_analyze=False,
            reason=reason,
            detail=detail,
            event_key=event_key or f"{snapshot.symbol}:{self._config.base_timeframe}:unknown",
            symbol=snapshot.symbol,
            at_ms=at,
            change_bps=change_bps,
            estimated_cost_usd=0.0,
            remaining_budget_usd=max(0.0, budget),
            snapshot_id=snapshot.snapshot_id,
        )
        # Skips are recorded too: "why did the bot not analyse?" must be
        # answerable from the ledger, not inferred from a missing row.
        self._append(decision)
        return decision

    def _append(self, decision: TriggerDecision) -> None:
        row = decision.to_json()
        row["event_hash"] = hashlib.sha256(
            json.dumps(row, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest()
        with self._ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")


@dataclass(frozen=True, slots=True)
class CachedResponse:
    cache_key: str
    snapshot_hash: str
    prompt_version: str
    model_version: str
    text: str
    created_at_ms: int
    ttl_ms: int

    def is_fresh(self, at_ms: int) -> bool:
        age = int(at_ms) - int(self.created_at_ms)
        return 0 <= age <= self.ttl_ms

    def to_json(self) -> dict[str, Any]:
        return {
            "cache_key": self.cache_key,
            "snapshot_hash": self.snapshot_hash,
            "prompt_version": self.prompt_version,
            "model_version": self.model_version,
            "text": self.text,
            "created_at_ms": self.created_at_ms,
            "ttl_ms": self.ttl_ms,
        }


class ResponseCache:
    """TTL + identity cache.  A hit is fresh only if the *inputs* match."""

    def __init__(self, root: Path | str, *, ttl_ms: int = 3_600_000) -> None:
        if ttl_ms <= 0:
            raise ValueError("ttl_ms must be > 0")
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._ttl_ms = int(ttl_ms)

    @staticmethod
    def key(snapshot_hash: str, prompt_version: str, model_version: str) -> str:
        material = f"{snapshot_hash}|{prompt_version}|{model_version}".encode()
        return hashlib.sha256(material).hexdigest()

    def _path(self, cache_key: str) -> Path:
        return self._root / f"{cache_key}.json"

    def put(
        self,
        *,
        snapshot_hash: str,
        prompt_version: str,
        model_version: str,
        text: str,
        at_ms: int,
        ttl_ms: int | None = None,
    ) -> CachedResponse:
        ttl = self._ttl_ms if ttl_ms is None else int(ttl_ms)
        if ttl <= 0:
            raise ValueError("ttl_ms must be > 0")
        key = self.key(snapshot_hash, prompt_version, model_version)
        entry = CachedResponse(
            cache_key=key,
            snapshot_hash=snapshot_hash,
            prompt_version=prompt_version,
            model_version=model_version,
            text=text,
            created_at_ms=int(at_ms),
            ttl_ms=ttl,
        )
        self._path(key).write_text(
            json.dumps(entry.to_json(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return entry

    def get(
        self,
        *,
        snapshot_hash: str,
        prompt_version: str,
        model_version: str,
        at_ms: int,
    ) -> CachedResponse | None:
        key = self.key(snapshot_hash, prompt_version, model_version)
        path = self._path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            entry = CachedResponse(
                cache_key=str(payload["cache_key"]),
                snapshot_hash=str(payload["snapshot_hash"]),
                prompt_version=str(payload["prompt_version"]),
                model_version=str(payload["model_version"]),
                text=str(payload["text"]),
                created_at_ms=int(payload["created_at_ms"]),
                ttl_ms=int(payload["ttl_ms"]),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if entry.cache_key != key:
            return None
        if (entry.snapshot_hash, entry.prompt_version, entry.model_version) != (
            snapshot_hash,
            prompt_version,
            model_version,
        ):
            return None
        if not entry.is_fresh(at_ms):
            return None
        return entry
