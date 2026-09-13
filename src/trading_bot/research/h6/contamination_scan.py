"""P21 — repository scan for forbidden real H6 artifacts.

For this preparation checkpoint, forbidden artifacts include:
- real H6 trade list
- H6 PnL / expectancy / PF / Sharpe / win rate
- H6 future-return analysis
- H6 parameter ranking
- H6 threshold optimization

This module is diagnostic-only for the current checkpoint.
"""

from __future__ import annotations

from pathlib import Path

FORBIDDEN_PATTERNS = (
    "H6_TRADE_LIST",
    "H6_PNL",
    "H6_EXPECTANCY",
    "H6_PF",
    "H6_SHARPE",
    "H6_WIN_RATE",
    "H6_FORWARD_RETURN",
    "H6_PERFORMANCE",
    "H6_PARAMETER_RANKING",
    "H6_THRESHOLD_OPTIMIZATION",
)

# V4 repair (V3-AUTH-001): the scanned directory was the superseded V1 package.
# Active H6 evidence lives under the versioned V4 repair package.
SCANNED_DIRECTORIES = (
    Path("src/trading_bot"),
    Path("scripts"),
    Path("reports"),
    Path("docs/external-audit-01/h6-v4-repair"),
)


def scan_forbidden_h6_artifacts() -> list[Path]:
    """Return any paths containing forbidden real H6 evidence."""
    hits: list[Path] = []
    for root in SCANNED_DIRECTORIES:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in {".json", ".jsonl", ".md", ".txt", ".py"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for pattern in FORBIDDEN_PATTERNS:
                if pattern in text:
                    hits.append(path)
    return hits
