"""Trading-bot strategy admission: registry, promotion governance, shadow plane."""

from trading_bot.admission.assets import DOGE_RECORD, XRP_RECORD
from trading_bot.admission.confirmation import (
    ConfirmationAuthorityError,
    ConfirmationManifest,
    load_manifest,
)
from trading_bot.admission.engine import PromotionProposal, StrategyAdmissionEngine
from trading_bot.admission.registry import (
    EvidenceRef,
    RegistryIntegrityError,
    StrategyRegistry,
    StrategyVersionRecord,
)
from trading_bot.admission.router_contract import (
    PlaneAuthorityError,
    assert_plane,
    router_authorizes,
)
from trading_bot.admission.shadow import (
    DuplicateShadowTradeError,
    ShadowIsolationError,
    ShadowLedger,
    ShadowPlane,
    ShadowTrade,
    assert_no_execution_authority,
)
from trading_bot.admission.states import (
    AdmissionState,
    IllegalTransitionError,
    require_minimum_state,
    validate_transition,
)
from trading_bot.admission.verifier import (
    StrategyAdmissionVerifier,
    VerificationError,
    VerificationResult,
)

__all__ = [
    "DOGE_RECORD",
    "PROTOCOL_VERSION",
    "XRP_RECORD",
    "AdmissionState",
    "ConfirmationAuthorityError",
    "ConfirmationManifest",
    "DuplicateShadowTradeError",
    "EvidenceRef",
    "IllegalTransitionError",
    "PlaneAuthorityError",
    "PromotionProposal",
    "RegistryIntegrityError",
    "ShadowIsolationError",
    "ShadowLedger",
    "ShadowPlane",
    "ShadowTrade",
    "StrategyAdmissionEngine",
    "StrategyAdmissionVerifier",
    "StrategyRegistry",
    "StrategyVersionRecord",
    "VerificationError",
    "VerificationResult",
    "assert_no_execution_authority",
    "assert_plane",
    "load_manifest",
    "require_minimum_state",
    "router_authorizes",
    "validate_transition",
]

PROTOCOL_VERSION = "CONFIRMATION-PROTOCOL-V2"
