"""Champion/challenger tests: no single-window promotion (§11)."""

from __future__ import annotations

from trading_bot.strategy_lifecycle.champion import (
    ChallengerEvaluation,
    ChampionChallenger,
    ComparisonOutcome,
)
from trading_bot.strategy_lifecycle.contracts import ContextKey

KEY = ContextKey("champ", "BTC", "5m", "TREND_UP")


def _eval(sid, *, samples=200, exp=10.0, pf=1.5, dd=50.0, windows=()):
    return ChallengerEvaluation(
        strategy_id=sid,
        sample_count=samples,
        net_expectancy_bps=exp,
        profit_factor=pf,
        max_drawdown_bps=dd,
        window_net_bps=windows,
    )


def test_no_champion_is_insufficient_evidence() -> None:
    cc = ChampionChallenger()
    result = cc.compare(context=KEY, champion=None, challengers=[_eval("c1")])
    assert result.outcome is ComparisonOutcome.INSUFFICIENT_EVIDENCE


def test_challenger_winning_one_window_does_not_promote() -> None:
    cc = ChampionChallenger(required_window_wins=3)
    champion = _eval("champ", windows=(10.0, 10.0, 10.0, 10.0))
    challenger = _eval("chal", exp=20.0, pf=2.0, windows=(30.0, 5.0, 5.0, 5.0))
    result = cc.compare(context=KEY, champion=champion, challengers=[challenger])
    assert result.outcome is ComparisonOutcome.CHAMPION_RETAINED


def test_challenger_winning_enough_windows_becomes_promotion_candidate() -> None:
    cc = ChampionChallenger(required_window_wins=3)
    champion = _eval("champ", windows=(5.0, 5.0, 5.0, 5.0))
    challenger = _eval("chal", exp=25.0, pf=2.0, windows=(30.0, 30.0, 30.0, 6.0))
    result = cc.compare(context=KEY, champion=champion, challengers=[challenger])
    assert result.outcome is ComparisonOutcome.PROMOTION_CANDIDATE
    assert result.winner_id == "chal"
    assert result.promotes


def test_insufficient_challenger_samples_blocks_promotion() -> None:
    cc = ChampionChallenger(required_window_wins=1, minimum_samples=100)
    champion = _eval("champ", windows=(5.0, 5.0))
    challenger = _eval("chal", samples=10, exp=25.0, pf=2.0, windows=(30.0, 30.0))
    result = cc.compare(context=KEY, champion=champion, challengers=[challenger])
    assert result.outcome is ComparisonOutcome.CHAMPION_RETAINED


def test_best_qualified_challenger_wins() -> None:
    cc = ChampionChallenger(required_window_wins=2)
    champion = _eval("champ", windows=(5.0, 5.0, 5.0))
    c1 = _eval("c1", exp=15.0, pf=1.8, windows=(20.0, 20.0, 6.0))
    c2 = _eval("c2", exp=30.0, pf=2.2, windows=(40.0, 40.0, 6.0))
    result = cc.compare(context=KEY, champion=champion, challengers=[c1, c2])
    assert result.winner_id == "c2"
