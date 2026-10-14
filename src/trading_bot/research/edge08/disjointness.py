"""WP-EDGE-08 — the holdout claim, made checkable instead of asserted.

The cross-section is only worth reading if no committed artefact of this repository has read it
before. That claim is checkable, so it is checked — twice, by two different means:

* **from disk** (``shards_outside_the_cross_section``): no local corpus directory holds a shard for
  one of these symbols. A symbol with a shard elsewhere is not a holdout, it is a re-read.
* **from git** (``tracked_references``): every *tracked* file that mentions the symbol is
  classified by path, and only the colourless kinds are allowed — a venue catalogue that lists every
  symbol on the exchange, a fetch/list script, or a test over either. A tracked **corpus shard** or
  a tracked **result artefact** mentioning one of these symbols fails the check, loudly, with the
  file named.

The classifier reads paths, not intentions: it cannot be talked out of a violation, and a new
mention of one of these symbols anywhere in the tree surfaces as a violation the next time it runs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from trading_bot.research.edge08.registration import EXISTING_CORPORA, REPO_ROOT

__all__ = [
    "ALLOWED_CLASSES",
    "classify_path",
    "disjointness_report",
    "shards_outside_the_cross_section",
    "tracked_references",
]

#: The only kinds of tracked file allowed to mention a holdout symbol. Everything else is a
#: violation, including anything under ``reports/`` or ``data/`` — with one deliberate exception:
#: this work package's own files, which name the symbols because they define the holdout.
ALLOWED_CLASSES: tuple[str, ...] = (
    "catalogue",
    "fetch_or_list_script",
    "test",
    "documentation",
    "this_work_package",
)

_CATALOGUE_HINTS = ("exchange_info", "symbols.json", "markets")
_CORPUS_DIRS = (
    "reports/alpha-expansion-v1/data/",
    "data/raw/alpha003/price/",
    "data/edge07/holdout-1h/",
)


def classify_path(path: str) -> str:
    """Classify one tracked path by what kind of file it is, from its name alone."""
    normalised = path.replace("\\", "/")
    lower = normalised.lower()
    # The work package's own files are self-references, not prior readings: the registration that
    # names the symbols, the code that implements the books, the fetch script and this package's
    # own artefacts. They are their own class so a reader can see the distinction rather than
    # have it hidden inside an allow-list.
    if normalised.startswith(
        (
            "data/edge08/",
            "reports/edge-recovery/WP-EDGE-08/",
            "src/trading_bot/research/edge08/",
        )
    ) or normalised in (
        "scripts/edge08_fetch_universe.py",
        "scripts/edge08_preregister.py",
        "scripts/edge08_universe_report.py",
    ):
        return "this_work_package"
    for corpora in _CORPUS_DIRS:
        if normalised.startswith(corpora):
            return "corpus_shard"
    if any(hint in lower for hint in _CATALOGUE_HINTS):
        return "catalogue"
    if normalised.startswith("scripts/"):
        return "fetch_or_list_script"
    if normalised.startswith("tests/"):
        return "test"
    if normalised.startswith("docs/") or lower.endswith(".md"):
        return "documentation"
    if normalised.startswith(("reports/", "data/", "config/", "evidence/")):
        return "result_artefact"
    if normalised.startswith("src/") or normalised.startswith(("AGENTS.md", "pyproject.toml")):
        return "source"
    return "other"


def tracked_references(symbols: tuple[str, ...]) -> dict[str, list[dict[str, str]]]:
    """Every tracked file mentioning each symbol, with its classified kind.

    ``git grep`` is asked for tracked files only, so an untracked scratch file cannot be used to
    argue that a symbol is clean, and a committed one cannot hide.
    """
    out: dict[str, list[dict[str, str]]] = {}
    for symbol in symbols:
        try:
            proc = subprocess.run(
                ["git", "grep", "-l", "--fixed-strings", symbol, "--", "."],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:  # pragma: no cover - git is present on every machine this runs on
            out[symbol] = [{"path": f"<git unavailable: {exc}>", "kind": "error"}]
            continue
        paths = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        out[symbol] = [{"path": path, "kind": classify_path(path)} for path in sorted(set(paths))]
    return out


def shards_outside_the_cross_section(symbols: tuple[str, ...]) -> dict[str, list[str]]:
    """Local corpus files for each symbol, outside ``data/edge08`` (must be empty)."""
    found: dict[str, list[str]] = {}
    for symbol in symbols:
        asset = symbol[: len(symbol) - 4]
        hits: list[str] = []
        for relative in EXISTING_CORPORA:
            root = REPO_ROOT / Path(relative)
            if not root.is_dir():
                continue
            for path in sorted(root.glob(f"{asset}USDT*")):
                hits.append(str(path.relative_to(REPO_ROOT)).replace("\\", "/"))
        found[symbol] = hits
    return found


def disjointness_report(symbols: tuple[str, ...]) -> dict[str, Any]:
    """Both halves of the claim, with the violations named."""
    references = tracked_references(symbols)
    shards = shards_outside_the_cross_section(symbols)
    violations: list[dict[str, str]] = []
    for symbol, files in references.items():
        for entry in files:
            if entry["kind"] not in ALLOWED_CLASSES:
                violations.append({"symbol": symbol, "path": entry["path"], "kind": entry["kind"]})
    for symbol, shard_paths in shards.items():
        for shard_path in shard_paths:
            violations.append(
                {"symbol": symbol, "path": shard_path, "kind": "local_corpus_shard"}
            )
    return {
        "symbols": list(symbols),
        "allowed_kinds": list(ALLOWED_CLASSES),
        "references": references,
        "shards_outside_the_cross_section": shards,
        "violations": violations,
        "claim_holds": not violations,
        "method": (
            "git grep over TRACKED files (an untracked scratch file cannot argue a symbol is "
            "clean, and a committed shard cannot hide), classified by path; plus a glob for a shard "
            "of the symbol in every corpus this repository already holds"
        ),
    }
