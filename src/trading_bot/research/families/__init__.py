"""Alpha families package.

Each family is a self-contained alpha generator following the AlphaFamily
contract: input OHLCV + precomputed indicators → output AlphaSignal list.
Families are orthogonal: they measure different market phenomena so their
signals can be combined without redundancy.
"""

from .breakout_family import BreakoutFamily
from .ema_crossover_family import EmaCrossoverFamily
from .mean_reversion_family import MeanReversionFamily
from .momentum_family import MomentumFamily
from .trend_family import TrendFamily
from .volatility_family import VolatilityFamily

__all__ = [
    "BreakoutFamily",
    "EmaCrossoverFamily",
    "MeanReversionFamily",
    "MomentumFamily",
    "TrendFamily",
    "VolatilityFamily",
]
