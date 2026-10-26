"""FORWARD DATA — point-in-time microstructure capture (DISCOVERY PLANE).

MICROSTRUCTURE-FORWARD-COLLECTION-V1. This package exists because the two
hypotheses that survived the historical audit (M-03 order-book imbalance and
M-07 open-interest x price) cannot be tested on data that does not exist:
order book history has no provider, open interest retains ~31 days and the
liquidation feed is dead.

So instead of fabricating history, we capture guaranteed-quality forward data.

    contract     the stable raw event schema (three clocks, explicit market)
    orderbook    snapshot+diff reconstruction with hard sequence integrity
    storage      deterministic rotation, fingerprints, manifest, resume
    collector    the WebSocket-first, restartable, self-auditing capture process
    replay       offline, internet-free deterministic reconstruction
    aggregation  raw -> complete 1m buckets -> 5m/15m/30m with PIT availability
    reporting    quality / book / resource / daily reports
    resources    portable CPU, RAM, disk and network accounting

Nothing in this package is on the trading decision path. It cannot place an
order, and it holds no credentials.
"""

from __future__ import annotations

from .aggregation import (
    AGGREGATION_VERSION,
    BucketAggregate,
    OrderBookBucketAggregate,
    aggregate_dataset,
    aggregate_events,
)
from .collector import CollectorConfig, ForwardCollector
from .contract import (
    COLLECTOR_VERSION,
    CONTRACT_VERSION,
    SCHEMA_VERSION,
    ClockViolation,
    ContractError,
    EventType,
    Market,
    RawEvent,
    SequenceRange,
    Transport,
)
from .orderbook import (
    BookHealth,
    BookSyncer,
    DepthUpdate,
    DiffDisposition,
    OrderBook,
    SequencePolicy,
)
from .replay import ForwardReplay, ReplayVerification, replay_microstructure_dataset
from .reporting import (
    build_daily_report,
    build_quality_report,
    build_resource_report,
    load_run,
)
from .storage import (
    DEFAULT_ROOT,
    GapRecord,
    RunManifest,
    SegmentFingerprint,
    SegmentWriter,
)

__all__ = [
    "AGGREGATION_VERSION",
    "COLLECTOR_VERSION",
    "CONTRACT_VERSION",
    "DEFAULT_ROOT",
    "SCHEMA_VERSION",
    "BookHealth",
    "BookSyncer",
    "BucketAggregate",
    "ClockViolation",
    "CollectorConfig",
    "ContractError",
    "DepthUpdate",
    "DiffDisposition",
    "EventType",
    "ForwardCollector",
    "ForwardReplay",
    "GapRecord",
    "Market",
    "OrderBook",
    "OrderBookBucketAggregate",
    "RawEvent",
    "ReplayVerification",
    "RunManifest",
    "SegmentFingerprint",
    "SegmentWriter",
    "SequencePolicy",
    "SequenceRange",
    "Transport",
    "aggregate_dataset",
    "aggregate_events",
    "build_daily_report",
    "build_quality_report",
    "build_resource_report",
    "load_run",
    "replay_microstructure_dataset",
]
