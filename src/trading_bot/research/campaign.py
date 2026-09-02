"""Research Campaign Controller (FASE 6, P12, P24).

Autonomous state machine for research campaigns:
  WAITING_FOR_DATA → DISCOVERY_READY → RUNNING_DISCOVERY →
  CANDIDATE_FOUND → WAITING_CONFIRMATION → RUNNING_CONFIRMATION →
  CONFIRMED / CAMPAIGN_REJECTED / STOP_NO_EDGE / QUEUE_EXHAUSTED

Key invariant (P12):
  If a complete campaign finds no edge:
  → Do NOT generate new thresholds automatically.
  → STOP_NO_EDGE is a valid terminal state.

The controller does NOT execute strategies — it orchestrates the
validation pipeline, registry, and window management.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from .registry import ExperimentRegistry
from .types import (
    CampaignRecord,
    CampaignStatus,
    DatasetWindow,
    PerformanceMetrics,
)
from .validation import ValidationPipeline, ValidationReport


@dataclass
class CampaignController:
    """Autonomous research campaign controller (P24).

    Manages the lifecycle of a single campaign:
    1. Detect fresh data
    2. Run discovery
    3. Evaluate candidate
    4. Run confirmation
    5. Report result

    Does NOT execute strategies — that's the caller's responsibility.
    The controller orchestrates windows, registry, and validation.
    """

    registry: ExperimentRegistry
    pipeline: ValidationPipeline
    family: str
    hypothesis: str = ""
    _log: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self._log is None:
            self._log = structlog.get_logger("campaign_controller")

    def create_campaign(self, campaign_id: str) -> CampaignRecord:
        """Create a new campaign record."""
        now = int(time.time() * 1000)
        record = CampaignRecord(
            campaign_id=campaign_id,
            family=self.family,
            created_at=now,
            hypothesis=self.hypothesis,
        )
        self._log.info("campaign.created", campaign_id=campaign_id, family=self.family)
        return record

    def check_fresh_data(
        self,
        symbol: str,
        timeframe: str,
        available_start: int,
        available_end: int,
    ) -> DatasetWindow | None:
        """Check if fresh (unconsumed) data is available (P11).

        Returns a DatasetWindow if data is fresh, None if consumed.
        """
        if self.registry.is_consumed(symbol, timeframe, available_start, available_end):
            self._log.info("campaign.no_fresh_data", symbol=symbol, timeframe=timeframe)
            return None

        return DatasetWindow(
            window_id=f"W-{symbol.replace('/', '')}-{timeframe}-{available_start}",
            symbol=symbol,
            timeframe=timeframe,
            start_ts=available_start,
            end_ts=available_end,
            candle_count=0,  # caller fills this
        )

    def run_discovery(
        self,
        campaign: CampaignRecord,
        discovery_window: DatasetWindow,
        discovery_metrics: PerformanceMetrics,
    ) -> ValidationReport:
        """Run discovery phase of a campaign.

        Caller must:
        1. Provide the discovery window (from check_fresh_data)
        2. Run the strategy on that window
        3. Compute metrics
        4. Pass metrics here

        The controller handles:
        - Preregistration
        - Validation
        - Status updates
        """
        exp_id = f"EXP-{campaign.campaign_id}-DISC"

        # Preregister
        self.registry.preregister(
            experiment_id=exp_id,
            strategy_version=campaign.family,
            hypothesis=campaign.hypothesis,
            rules={},
            parameters={},
            dataset_start=discovery_window.start_ts,
            dataset_end=discovery_window.end_ts,
            code_hash="pending",
            config_hash="pending",
            data_hash=f"{discovery_window.window_id}",
        )

        # Validate
        report = self.pipeline.validate_discovery(
            exp_id, discovery_window, discovery_metrics,
        )

        if report.all_passed:
            self.registry.update_status(
                exp_id, "CANDIDATE",
                results=discovery_metrics,
                decision="discovery passed",
            )
        else:
            failed = [g.gate_name for g in report.gate_results if not g.passed]
            self.registry.update_status(
                exp_id, "REJECTED",
                results=discovery_metrics,
                decision=f"discovery failed: {', '.join(failed)}",
            )

        return report

    def run_confirmation(
        self,
        campaign: CampaignRecord,
        confirmation_window: DatasetWindow,
        confirmation_metrics: PerformanceMetrics,
    ) -> ValidationReport:
        """Run confirmation phase of a campaign.

        P10: freeze exact candidate, no retuning.
        """
        exp_id = f"EXP-{campaign.campaign_id}-CONF"

        self.registry.preregister(
            experiment_id=exp_id,
            strategy_version=campaign.family,
            hypothesis=campaign.hypothesis,
            rules={},
            parameters={},
            dataset_start=confirmation_window.start_ts,
            dataset_end=confirmation_window.end_ts,
            code_hash="pending",
            config_hash="pending",
            data_hash=f"{confirmation_window.window_id}",
        )

        report = self.pipeline.validate_confirmation(
            exp_id, confirmation_window, confirmation_metrics,
        )

        if report.all_passed:
            self.registry.update_status(
                exp_id, "CONFIRMED",
                results=confirmation_metrics,
                decision="confirmation passed",
            )
        else:
            failed = [g.gate_name for g in report.gate_results if not g.passed]
            self.registry.update_status(
                exp_id, "REJECTED",
                results=confirmation_metrics,
                decision=f"confirmation failed: {', '.join(failed)}",
            )

        return report

    def complete_campaign(
        self,
        campaign: CampaignRecord,
        discovery_report: ValidationReport,
        confirmation_report: ValidationReport,
    ) -> CampaignRecord:
        """Complete a campaign and determine final status (P12).

        Terminal states:
        - CONFIRMED: both discovery and confirmation passed
        - CAMPAIGN_REJECTED: discovery or confirmation failed
        - STOP_NO_EDGE: complete campaign found no edge
        """
        now = int(time.time() * 1000)

        if discovery_report.all_passed and confirmation_report.all_passed:
            status: CampaignStatus = "CONFIRMED"
        elif not discovery_report.all_passed:
            status = "CAMPAIGN_REJECTED"
        else:
            status = "CAMPAIGN_REJECTED"

        return CampaignRecord(
            campaign_id=campaign.campaign_id,
            family=campaign.family,
            created_at=campaign.created_at,
            status=status,
            hypothesis=campaign.hypothesis,
            completed_at=now,
        )


__all__ = ["CampaignController"]
