"""RFC-038 BLOCK C (§27-§40) -- modern data provider review + acquisition decision.

RFC-037 found no FREE independent individual-contract futures dataset post-2000.
That does NOT mean such data does not exist -- it means it must be PAID FOR.
This module builds a provider matrix from PUBLIC information only, scores the
research value of a shared P1+P2 dataset, and classifies the decision:

    DO_NOT_BUY / REQUEST_QUOTE / BUY_CANDIDATE

BUY_CANDIDATE never purchases anything.  No credit card, subscription, API
purchase or paid account is created here (§36).  Unknown prices are left as
QUOTE_REQUIRED rather than invented (§31).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

OUT = REPO / "reports" / "managed-futures-decision"
OUT.mkdir(parents=True, exist_ok=True)

# RFC-036 traded universe: 26 markets, 6 asset classes, all CME-Group-listed
# (CME / CBOT / NYMEX / COMEX), so a single CME-Group feed can cover P1 end to end.
RFC036_UNIVERSE_ASSET_CLASSES = ["EQUITY_INDEX", "GOVERNMENT_BOND_RATES", "FX",
                                 "ENERGY", "METALS", "AGRICULTURE"]


def provider_matrix() -> list[dict[str, Any]]:
    """Machine-readable provider comparison (§31).  Facts are public/verifiable."""
    return [
        {
            "provider": "Databento",
            "dataset": "GLBX.MDP3 (CME Globex MDP 3.0)",
            "coverage": "CME Group: equity index, rates, FX, energy, metals, agriculture",
            "history": "15+ years",
            "individual_contracts": True,
            "term_structure": True,
            "volume": True,
            "open_interest": True,
            "pit_suitability": "HIGH (ts_event / ts_recv, per-contract, no survivors-only bias)",
            "licence": "commercial data licence; redistribution restricted",
            "api_file_format": "API + tabular (DBN/CSV/Parquet)",
            "p1_suitability": "HIGH",
            "p2_suitability": "HIGH (expiry metadata -> simultaneous maturities)",
            "price": "usage-based (metered by uncompressed bytes) or subscription "
                     "(Standard $179-$199/month, 15+ yr history); full-history firm "
                     "licence advertised at ~$4,500/month",
            "quote_required": False,
            "source": "https://databento.com/pricing ; https://databento.com/futures",
        },
        {
            "provider": "CME DataMine",
            "dataset": "CME Group historical datasets (settlements, contracts, volume/OI, continuous)",
            "coverage": "CME Group (all six RFC-036 asset classes)",
            "history": "long (multiple decades, per product)",
            "individual_contracts": True,
            "term_structure": True,
            "volume": True,
            "open_interest": True,
            "pit_suitability": "HIGH (exchange settlement archive)",
            "licence": "exchange data licence",
            "api_file_format": "bulk files + DataMine platform/API",
            "p1_suitability": "HIGH",
            "p2_suitability": "HIGH",
            "price": "QUOTE_REQUIRED (dataset/subscription pricing; historical product "
                     "guide cited ~$1,200/month for some datasets)",
            "quote_required": True,
            "source": "https://www.cmegroup.com/datamine.html",
        },
        {
            "provider": "Portara / CQG DataFactory",
            "dataset": "historical futures (individual + continuous)",
            "coverage": "broad CME/ICE/Eurex futures",
            "history": "daily from 1899",
            "individual_contracts": True,
            "term_structure": True,
            "volume": True,
            "open_interest": True,
            "pit_suitability": "MEDIUM-HIGH (verify PIT export)",
            "licence": "commercial",
            "api_file_format": "download / files",
            "p1_suitability": "HIGH",
            "p2_suitability": "HIGH",
            "price": "QUOTE_REQUIRED",
            "quote_required": True,
            "source": "https://portaracqg.com/",
        },
        {
            "provider": "Algoseek",
            "dataset": "US futures historical research package",
            "coverage": "US futures (CME/COMEX/NYMEX/CBOT)",
            "history": "intraday, shorter deep history",
            "individual_contracts": True,
            "term_structure": True,
            "volume": True,
            "open_interest": True,
            "pit_suitability": "MEDIUM-HIGH",
            "licence": "commercial",
            "api_file_format": "datasets / S3",
            "p1_suitability": "MEDIUM",
            "p2_suitability": "MEDIUM",
            "price": "$2,500/month (futures research package)",
            "quote_required": False,
            "source": "https://algoseek.com/dataset/us-futures-trade-only-minute-bar/",
        },
        {
            "provider": "Nasdaq Data Link (CHRIS)",
            "dataset": "continuous futures (CHRIS)",
            "coverage": "broad",
            "history": "long",
            "individual_contracts": False,
            "term_structure": False,
            "volume": False,
            "open_interest": False,
            "pit_suitability": "LOW (continuous only)",
            "licence": "n/a",
            "api_file_format": "API",
            "p1_suitability": "LOW (continuous cannot reconstruct executable PnL)",
            "p2_suitability": "LOW",
            "price": "DEPRECATED (no longer updated)",
            "quote_required": False,
            "source": "https://github.com/PacktPublishing/Python-for-Algorithmic-Trading-Cookbook/issues/5",
        },
        {
            "provider": "FirstRate Data",
            "dataset": "futures (individual + adjusted continuous), intraday/daily",
            "coverage": "broad US futures",
            "history": "~25 years intraday",
            "individual_contracts": True,
            "term_structure": True,
            "volume": True,
            "open_interest": True,
            "pit_suitability": "MEDIUM (verify per-contract PIT)",
            "licence": "commercial (one-time purchase options)",
            "api_file_format": "download",
            "p1_suitability": "MEDIUM",
            "p2_suitability": "MEDIUM",
            "price": "QUOTE_REQUIRED / one-time packages",
            "quote_required": True,
            "source": "https://firstratedata.com/",
        },
        {
            "provider": "TurtleTrader (RFC-036 source)",
            "dataset": "free historical individual contracts",
            "coverage": "26 markets, 6 classes (RFC-036 universe)",
            "history": "~1959-2000",
            "individual_contracts": True,
            "term_structure": True,
            "volume": True,
            "open_interest": True,
            "pit_suitability": "HIGH but ends ~2000",
            "licence": "free/download",
            "api_file_format": "zip/text",
            "p1_suitability": "HISTORICAL only (used by RFC-036)",
            "p2_suitability": "HISTORICAL only",
            "price": "FREE",
            "quote_required": False,
            "historical_only": True,
            "source": "https://www.turtletrader.com/hpd/",
        },
    ]


def _tok(x: str) -> str:
    """Normalise a suitability label to its leading token ('HIGH (...)' -> 'HIGH')."""
    return str(x).split(" ")[0].strip().upper()


def score(p: dict[str, Any]) -> float:
    """DATA_RESEARCH_VALUE (§33): weighted, frozen before ranking."""
    def b(x: bool) -> float:
        return 1.0 if x else 0.0
    p1t, p2t = _tok(p["p1_suitability"]), _tok(p["p2_suitability"])
    p1 = 3.0 * b(p1t in ("HIGH", "MEDIUM")) + b(p1t == "HIGH")
    p2 = 3.0 * b(p2t in ("HIGH", "MEDIUM")) + b(p2t == "HIGH")
    modern = 2.0 if not p.get("historical_only", False) and not str(
        p["price"]).startswith("DEPRECATED") else 0.0
    quality = (b(p["individual_contracts"]) + b(p["volume"]) + b(p["open_interest"])
               + b(p["term_structure"]))
    pit = b(_tok(p["pit_suitability"]) in ("HIGH", "MEDIUM-HIGH"))
    reusability = 2.0 if (p1t in ("HIGH", "MEDIUM") and p2t in ("HIGH", "MEDIUM")) else 0.0
    return float(p1 + p2 + modern + quality + pit + reusability)


def eligible(p: dict[str, Any]) -> bool:
    return bool(p["individual_contracts"] and p["term_structure"]
                and _tok(p["p1_suitability"]) in ("HIGH", "MEDIUM")
                and _tok(p["p2_suitability"]) in ("HIGH", "MEDIUM")
                and not str(p["price"]).startswith("DEPRECATED"))


def decide(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    """Frozen decision rule (§32-§34): best eligible shared P1+P2 dataset.

    Tie-break order: DATA_RESEARCH_VALUE desc, then transparent public price, then API.
    """
    elig = [p for p in matrix if eligible(p)]
    for p in matrix:
        p["data_research_value"] = score(p)
    elig.sort(key=lambda p: (p["data_research_value"],
                             not p["quote_required"],
                             "API" in p["api_file_format"]), reverse=True)
    best = elig[0] if elig else None
    if best is None:
        classification = "DO_NOT_BUY"
    elif best["quote_required"]:
        classification = "REQUEST_QUOTE"
    else:
        classification = "BUY_CANDIDATE"
    return {
        "eligible": [p["provider"] for p in elig],
        "ranked": [p["provider"] for p in sorted(
            matrix, key=lambda p: p["data_research_value"], reverse=True)],
        "best_provider": best["provider"] if best else None,
        "best_dataset": best["dataset"] if best else None,
        "best_price": best["price"] if best else None,
        "classification": classification,
        "rule": ("among eligible datasets (individual contracts + term structure + P1&P2 "
                 "MEDIUM+ + live), pick highest DATA_RESEARCH_VALUE; tie-break public "
                 "price then API. BUY_CANDIDATE never purchases -- it needs human approval."),
    }


def main() -> None:
    matrix = provider_matrix()
    for p in matrix:
        p["data_research_value"] = score(p)
    ranking = decide(matrix)
    print(json.dumps({"matrix": matrix, **ranking}, indent=2, default=str))


if __name__ == "__main__":
    main()
