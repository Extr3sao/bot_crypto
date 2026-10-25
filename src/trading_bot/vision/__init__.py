"""vision — a multimodal LLM that reads a chart and decides, inside the paper book.

RFC-AI-VISION-001. The pieces, in the order they run:

``chart``     bars -> deterministic PNG + SHA-256 (the only market input the model gets)
``prompt``    versioned text contract, hashed next to the image
``contract``  strict ``VisionDecision`` schema and its parser (LONG/SHORT/CLOSE/NO_TRADE)
``provider``  provider-agnostic multimodal call, retries, cost, raw-response capture
``ledger``    append-only, hash-chained record of image -> decision -> risk -> PnL
``lane``      the vertical slice: chart -> model -> Signal -> RiskManager -> PaperBroker

Nothing here can send a live order: the lane only ever talks to ``PaperBroker`` and the
runtime's own ``RiskManager``, and no module in this package imports an exchange client.
"""

from __future__ import annotations

__all__ = ["CHART_SPEC_VERSION", "DEFAULT_WINDOW_BARS"]

from trading_bot.vision.chart import CHART_SPEC_VERSION, DEFAULT_WINDOW_BARS
