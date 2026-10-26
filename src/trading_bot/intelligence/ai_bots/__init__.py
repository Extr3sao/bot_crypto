"""ai_bots — opinion-only plugins that share the canonical book (RFC-TAP-AI-BOTS-002).

``contracts``  AITradeOpinion / TradeProposal and the forbidden-field rejection
``registry``   BotCapabilityRegistry: disabled by default, no bot holds an execution tool
``bots``       BOT-VIS-01 (PNG) and BOT-CTX-01 (numeric MTF, no image) plus traces

No module here imports ``PaperBroker``: bots emit opinions, the runner owns the book.
"""

from __future__ import annotations
