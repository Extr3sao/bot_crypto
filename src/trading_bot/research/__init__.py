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
from .campaign import CampaignController
from .code_path import CodeHash, CodePathValidation, SharedCodePathValidator
from .cross_sectional import CrossSectionalEngine, CrossSectionalSnapshot, QuantileSelection
from .data_integrity import DataIntegrityChecker, IntegrityReport
from .event_store import BlockedEventStore
from .llm_safety import LLMAuthorization, LLMSafetyGuard
from .marginal import (
    MarginalContribution,
    MarginalPortfolioAnalyzer,
    MarginalReport,
    StandaloneResult,
)
from .portfolio_backtest import (
    PortfolioBacktestConfig,
    PortfolioBacktestEngine,
    PortfolioBacktestResult,
    PortfolioEquityPoint,
    PortfolioTrade,
)
from .regime import RegimeConfig, RegimeEngine, RegimeSnapshot
from .registry import ExperimentRegistry
from .reporting import ReportBundle, ReportGenerator
from .stability import StabilityAnalyzer, StabilityReport
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
from .validation import (
    GateResult,
    QualityGates,
    TestingDisciplineLabel,
    ValidationPipeline,
    ValidationReport,
)

__all__ = [
    "AdmissionController",
    "AdmissionResult",
    "AdmissionState",
    "AlphaFamily",
    "AlphaRegistry",
    "AlphaSignal",
    "BlockedEvent",
    "BlockedEventStore",
    "BlockedReason",
    "CampaignController",
    "CampaignRecord",
    "CampaignStatus",
    "CodeHash",
    "CodePathValidation",
    "CrossSectionalEngine",
    "CrossSectionalSnapshot",
    "DataIntegrityChecker",
    "DatasetWindow",
    "Direction",
    "ExperimentRecord",
    "ExperimentRegistry",
    "ExperimentStatus",
    "FeaturesBag",
    "GateResult",
    "IntegrityReport",
    "LLMAuthorization",
    "LLMSafetyGuard",
    "PerformanceMetrics",
    "PortfolioBacktestConfig",
    "PortfolioBacktestEngine",
    "PortfolioBacktestResult",
    "PortfolioEquityPoint",
    "PortfolioTrade",
    "QualityGates",
    "RegimeConfig",
    "RegimeEngine",
    "RegimeSnapshot",
    "ReportBundle",
    "ReportGenerator",
    "SharedCodePathValidator",
    "StabilityAnalyzer",
    "StabilityReport",
    "StandaloneResult",
    "TestingDisciplineLabel",
    "ValidationPipeline",
    "ValidationReport",
    "WindowStatus",
]
