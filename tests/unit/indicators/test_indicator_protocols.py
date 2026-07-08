from __future__ import annotations

from trading_bot.indicators import Indicator


class DummyIndicator:
    @property
    def indicator_type(self) -> str:
        return "dummy"

    def compute(self, candles: list[object], params: dict[str, object]) -> float:
        del candles, params
        return 1.0


def test_indicator_protocol_is_runtime_checkable() -> None:
    assert isinstance(DummyIndicator(), Indicator)
