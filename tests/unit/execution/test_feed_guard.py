from __future__ import annotations

from trading_bot.execution import FeedDeadManGuard, FeedFreshness, FeedGuardAction


def _fresh(feed_id: str = "ohlcv-btc") -> FeedFreshness:
    return FeedFreshness(
        feed_id=feed_id, last_update_ts=1_000.0, observed_at_ts=1_010.0, max_staleness_seconds=30.0
    )


def _stale(feed_id: str = "ohlcv-btc", staleness: float = 60.0) -> FeedFreshness:
    return FeedFreshness(
        feed_id=feed_id,
        last_update_ts=1_000.0,
        observed_at_ts=1_000.0 + staleness,
        max_staleness_seconds=30.0,
    )


def test_all_fresh_allows_entries() -> None:
    guard = FeedDeadManGuard()
    verdict = guard.evaluate((_fresh(), _fresh("ohlcv-eth")))
    assert verdict.action is FeedGuardAction.ALLOW
    assert verdict.stale_feeds == ()
    assert guard.allow_new_entries(verdict)


def test_stale_feed_blocks_new_entries() -> None:
    guard = FeedDeadManGuard()
    verdict = guard.evaluate((_fresh(), _stale()))
    assert verdict.action is FeedGuardAction.BLOCK_NEW_ENTRIES
    assert verdict.stale_feeds == ("ohlcv-btc",)
    assert not guard.allow_new_entries(verdict)
    evidence_feed = verdict.evidence["feeds"]["ohlcv-btc"]
    assert evidence_feed["stale"] is True


def test_hard_stale_with_cancel_policy() -> None:
    guard = FeedDeadManGuard(cancel_resting_on_stale=True, cancel_after_multiplier=2.0)
    verdict = guard.evaluate((_stale(staleness=90.0),))  # 90s > 30s * 2
    assert verdict.action is FeedGuardAction.BLOCK_AND_CANCEL_RESTING


def test_stale_below_hard_threshold_never_cancels_resting() -> None:
    guard = FeedDeadManGuard(cancel_resting_on_stale=True, cancel_after_multiplier=3.0)
    verdict = guard.evaluate((_stale(staleness=60.0),))  # 60s < 30s * 3
    assert verdict.action is FeedGuardAction.BLOCK_NEW_ENTRIES


def test_verdicts_are_recorded_as_evidence() -> None:
    guard = FeedDeadManGuard()
    guard.evaluate((_fresh(),))
    guard.evaluate((_stale(),))
    assert len(guard.events) == 2
    assert guard.events[0].action is FeedGuardAction.ALLOW
    assert guard.events[1].action is FeedGuardAction.BLOCK_NEW_ENTRIES
