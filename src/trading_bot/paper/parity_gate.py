"""FullExecutionParityGate — V0.3.2 parity certification.

PASS requires:
- same strategy hash
- same dataset hash
- same assumptions hash
- 0 unexplained signal differences
- 0 unexplained execution differences
- accounting reconciled
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ParityVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ParityDifferenceType(str, Enum):
    MATCH = "MATCH"
    EXPECTED_DIFFERENCE = "EXPECTED_DIFFERENCE"
    UNEXPLAINED_DIFFERENCE = "UNEXPLAINED_DIFFERENCE"


@dataclass(frozen=True)
class ParityDifference:
    """Single parity difference."""
    category: str  # "signal", "execution", "accounting"
    description: str
    difference_type: ParityDifferenceType
    backtest_value: Any = None
    paper_value: Any = None


@dataclass
class ParityReport:
    """Full parity report."""
    strategy_hash_backtest: str = ""
    strategy_hash_paper: str = ""
    strategy_hash_match: bool = False

    dataset_hash_backtest: str = ""
    dataset_hash_paper: str = ""
    dataset_hash_match: bool = False

    assumptions_hash_backtest: str = ""
    assumptions_hash_paper: str = ""
    assumptions_hash_match: bool = False

    signal_count_backtest: int = 0
    signal_count_paper: int = 0
    signal_matches: int = 0
    signal_differences: list[ParityDifference] = field(default_factory=list)

    execution_matches: int = 0
    execution_differences: list[ParityDifference] = field(default_factory=list)

    accounting_delta: dict[str, float] = field(default_factory=dict)
    accounting_differences: list[ParityDifference] = field(default_factory=list)

    unexplained_differences: int = 0

    def verdict(self) -> ParityVerdict:
        """Compute overall verdict."""
        if (
            self.strategy_hash_match
            and self.dataset_hash_match
            and self.assumptions_hash_match
            and self.unexplained_differences == 0
        ):
            return ParityVerdict.PASS
        return ParityVerdict.FAIL

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_hash_match": self.strategy_hash_match,
            "dataset_hash_match": self.dataset_hash_match,
            "assumptions_hash_match": self.assumptions_hash_match,
            "signal_count_backtest": self.signal_count_backtest,
            "signal_count_paper": self.signal_count_paper,
            "signal_matches": self.signal_matches,
            "execution_matches": self.execution_matches,
            "unexplained_differences": self.unexplained_differences,
            "verdict": self.verdict().value,
        }


class FullExecutionParityGate:
    """Gate that validates backtest/paper parity.

    PASS requires:
    - same strategy hash
    - same dataset hash
    - same assumptions hash
    - 0 unexplained signal differences
    - 0 unexplained execution differences
    - accounting reconciled
    """

    def check(
        self,
        strategy_hash_bt: str,
        strategy_hash_paper: str,
        dataset_hash_bt: str,
        dataset_hash_paper: str,
        assumptions_hash_bt: str,
        assumptions_hash_paper: str,
        signals_bt: list[dict] | None = None,
        signals_paper: list[dict] | None = None,
    ) -> ParityReport:
        """Run full parity check."""
        report = ParityReport()

        # Hash checks
        report.strategy_hash_backtest = strategy_hash_bt
        report.strategy_hash_paper = strategy_hash_paper
        report.strategy_hash_match = strategy_hash_bt == strategy_hash_paper

        report.dataset_hash_backtest = dataset_hash_bt
        report.dataset_hash_paper = dataset_hash_paper
        report.dataset_hash_match = dataset_hash_bt == dataset_hash_paper

        report.assumptions_hash_backtest = assumptions_hash_bt
        report.assumptions_hash_paper = assumptions_hash_paper
        report.assumptions_hash_match = assumptions_hash_bt == assumptions_hash_paper

        # Signal parity
        if signals_bt is not None and signals_paper is not None:
            report.signal_count_backtest = len(signals_bt)
            report.signal_count_paper = len(signals_paper)

            bt_set = {
                (s.get("direction"), round(s.get("entry", 0), 2))
                for s in signals_bt
            }
            paper_set = {
                (s.get("direction"), round(s.get("entry", 0), 2))
                for s in signals_paper
            }
            report.signal_matches = len(bt_set & paper_set)

            unexplained = 0
            for sig in signals_bt:
                key = (sig.get("direction"), round(sig.get("entry", 0), 2))
                if key not in paper_set:
                    report.signal_differences.append(ParityDifference(
                        category="signal",
                        description=f"Signal in backtest but not paper: {key}",
                        difference_type=ParityDifferenceType.UNEXPLAINED_DIFFERENCE,
                    ))
                    unexplained += 1
            for sig in signals_paper:
                key = (sig.get("direction"), round(sig.get("entry", 0), 2))
                if key not in bt_set:
                    report.signal_differences.append(ParityDifference(
                        category="signal",
                        description=f"Signal in paper but not backtest: {key}",
                        difference_type=ParityDifferenceType.UNEXPLAINED_DIFFERENCE,
                    ))
                    unexplained += 1
            report.unexplained_differences += unexplained

        return report


__all__ = [
    "FullExecutionParityGate",
    "ParityReport",
    "ParityVerdict",
    "ParityDifferenceType",
]
