"""Research module — quantitative research infrastructure.

FASE 2: Common types
FASE 3: Alpha Engine, Admission Controller, Portfolio Backtest
FASE 4: Experiment Registry
FASE 5: Discovery/Confirmation Validation Pipeline
FASE 6: Campaign Controller
FASE 7: Reporting
FASE 8: Data Integrity + Stability + Regime
P4: Blocked Event Store
P9: Auto Hash Verification
P13: Testing Discipline
P15: Marginal Portfolio Value
P18: Market Regime
P19: Cross-Sectional
P21: Shared Code Path Validator
P25: LLM Safety Guard
V0.2.1: Operational Qualification (evidence, data quality, real backtest,
         strategy engineer, confirmation, qualification gate)
"""

from .admission import AdmissionController, AdmissionResult, AdmissionState
from .alpha import AlphaFamily, AlphaRegistry
from .types import (
    AlphaSignal,
    BlockedEvent,
    BlockedReason,
    CampaignRecord,
    CampaignStatus,
    DatasetWindow,
    Direction,
    ExperimentRecord,
    ExperimentStatus,
    FeaturesBag,
    PerformanceMetrics,
    WindowStatus,
)
from .types import (
    AlphaSignal,
    BlockedEvent,
    BlockedReason,
    CampaignRecord,
    CampaignStatus,
    DatasetWindow,
    Direction,
    ExperimentRecord,
    ExperimentStatus,
    FeaturesBag,
    PerformanceMetrics,
    WindowStatus,
)
