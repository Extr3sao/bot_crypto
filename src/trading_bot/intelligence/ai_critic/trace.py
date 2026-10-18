"""trace — append-only receipts for every review, decision and model attempt.

Four files, four different claims:

``CRITIC_REVIEWS.jsonl``   the sealed ``CriticReview`` objects, one per line.
``DECISION_TRACE.jsonl``   what the gate did with each review and whether it touched the book.
``MODEL_INVOCATIONS.jsonl`` one row per provider attempt, including failures and refusals
                            that never reached a provider (``receipt_kind=NONE``).
``AGENT_MESSAGES.jsonl``   the hashed turns of the exchange, so a replay can rebuild them.

Rows are appended as they happen: a crash still leaves the receipt of what was spent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trading_bot.intelligence.ai_critic.contracts import (
    AgentMessage,
    CriticReview,
    ReviewDecisionTrace,
)


class CriticTraceWriter:
    def __init__(self, directory: Path | str) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.reviews = self.directory / "CRITIC_REVIEWS.jsonl"
        self.decisions = self.directory / "DECISION_TRACE.jsonl"
        self.invocations = self.directory / "MODEL_INVOCATIONS.jsonl"
        self.messages = self.directory / "AGENT_MESSAGES.jsonl"
        for path in (self.reviews, self.decisions, self.invocations, self.messages):
            path.touch()

    @staticmethod
    def _append(path: Path, row: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")

    def review(self, review: CriticReview) -> None:
        self._append(self.reviews, review.model_dump(mode="json"))

    def decision(self, trace: ReviewDecisionTrace) -> None:
        self._append(self.decisions, trace.model_dump(mode="json"))

    def invocation(self, row: dict[str, Any]) -> None:
        self._append(self.invocations, row)

    def message(self, message: AgentMessage) -> None:
        self._append(self.messages, message.model_dump(mode="json"))

    def counts(self) -> dict[str, int]:
        def lines(path: Path) -> int:
            return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

        return {
            "critic_reviews": lines(self.reviews),
            "decision_traces": lines(self.decisions),
            "model_invocations": lines(self.invocations),
            "agent_messages": lines(self.messages),
        }
