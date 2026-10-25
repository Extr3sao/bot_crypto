"""WP-EDGE-14C — third-party clone lab, license preflight and independent parity.

The brief's rule is unambiguous: study the sources, clone the engines *outside* the
active tree, pin every SHA, check every license, and never let a third-party engine send
an order or replace risk. It also wants a real comparison: a neutral test strategy run on
two engines over an identical dataset, period, asset, capital and cost model, agreeing
within a tolerance registered *before* the run.

This module delivers the part that can be done without the network — the pinned registry,
the license preflight, and the parity plan with its tolerance frozen — and it *attempts*
the part that needs the network, reporting ``BENCHMARK_PARITY_BLOCKED`` with the exact
command and its output when the network is unavailable, rather than pretending a clone
happened.

License rules it enforces, straight from the brief:

* GPL-3.0 (Freqtrade, freqtrade-strategies) — **NO_COPY**: study the methodology, import
  no code.
* MIT (Jesse, VnPy, ccxt, FinRL) — copy-respecting: attribution, dependency review.
* Apache-2.0 (Hummingbot, Lean, TradingAgents) — copy-respecting, notice file kept.
* LGPL-3.0 (NautilusTrader) — link-only, never vendored into the runtime.
* AGPL (cryptofeed, by README) — isolated and conditional; the licence file is validated
  before any use, because a README is not the licence.
* ``NOASSERTION`` — not a permission to copy, and is treated as NO_COPY until a licence
  file is read.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

__all__ = [
    "CLONE_ROOT",
    "SOURCES",
    "clone_probe",
    "license_preflight",
    "parity_payload",
    "parity_plan",
]

#: Clones live outside the repository, always. A clone inside the tree is a defect.
CLONE_ROOT = Path(tempfile.gettempdir()) / "edge14_clones"

SOURCES: tuple[dict[str, Any], ...] = (
    {
        "id": "SRC-01",
        "repo": "freqtrade/freqtrade",
        "sha": "b33068949fc16e69e288e0a5bef5bd1f086f0a27",
        "declared_license": "GPL-3.0",
        "use": "separate benchmark; lookahead-analysis and recursive-analysis methodology",
        "classification": "ADOPT_P0",
        "copy_rule": "NO_COPY",
    },
    {
        "id": "SRC-02",
        "repo": "jesse-ai/jesse",
        "sha": "5e642997f9623d67b63543962eab46caca30e613",
        "declared_license": "MIT",
        "use": "independent broker/backtest to reconcile fills and PnL",
        "classification": "ADOPT_P0",
        "copy_rule": "COPY_WITH_ATTRIBUTION",
    },
    {
        "id": "SRC-03",
        "repo": "vnpy/vnpy_ctastrategy",
        "sha": "7a8768de9784dda35a7b261a7ade1dbfbff50919",
        "declared_license": "MIT",
        "use": "hypothesis source: Dual Thrust, King Keltner, ATR-RSI",
        "classification": "ADOPT_P0",
        "copy_rule": "COPY_WITH_ATTRIBUTION",
    },
    {
        "id": "SRC-04",
        "repo": "hummingbot/hummingbot",
        "sha": "9af100d6822da7d2d0291a906c730ef172284ee2",
        "declared_license": "Apache-2.0",
        "use": "maker/queue/partial-fill study; requires L2",
        "classification": "ADOPT_P1_EXPERIMENT",
        "copy_rule": "COPY_WITH_NOTICE",
    },
    {
        "id": "SRC-05",
        "repo": "nautechsystems/nautilus_trader",
        "sha": "5b1b5b8c5ad9ddf784827d55723dd26ddeaf8d08",
        "declared_license": "LGPL-3.0",
        "use": "event/order replay; independent comparator",
        "classification": "EXPERIMENT",
        "copy_rule": "LINK_ONLY_NO_VENDOR",
    },
    {
        "id": "SRC-06",
        "repo": "ccxt/ccxt",
        "sha": "2c81f0a11d7785f30c4714e6bb2cb59d0738d38e",
        "declared_license": "MIT",
        "use": "continue with the current dependency",
        "classification": "REUSE_CURRENT",
        "copy_rule": "COPY_WITH_ATTRIBUTION",
    },
    {
        "id": "SRC-09",
        "repo": "bmoscon/cryptofeed",
        "sha": "bd0fe96093837262ce2c89ebc00286f48495fdad",
        "declared_license": "AGC-3.0? (README says AGPL; validate the LICENSE file)",
        "use": "WS L2/tape, only if a data deficiency is measured",
        "classification": "EXPERIMENT_CONDITIONAL",
        "copy_rule": "NO_COPY_UNTIL_LICENCE_READ",
    },
    {
        "id": "SRC-12",
        "repo": "TauricResearch/TradingAgents",
        "sha": "1394a3f72aa4393e1a98f51b382434c4b4c2d972",
        "declared_license": "Apache-2.0",
        "use": "research agents",
        "classification": "DEFER",
        "copy_rule": "COPY_WITH_NOTICE",
    },
)


def network_available(timeout_seconds: int = 12) -> dict[str, Any]:
    """Probe whether this host can reach the git remotes, without cloning anything."""
    if not shutil.which("git"):
        return {"available": False, "reason": "git is not on PATH", "command": None, "output": None}
    command = ["git", "ls-remote", "--heads", "https://github.com/jesse-ai/jesse", "master"]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {
            "available": False,
            "reason": f"{type(exc).__name__}: {exc}",
            "command": " ".join(command),
            "output": None,
        }
    ok = completed.returncode == 0 and bool(completed.stdout.strip())
    return {
        "available": ok,
        "reason": "reached the remote" if ok else f"exit {completed.returncode}",
        "command": " ".join(command),
        "output": (completed.stdout or completed.stderr or "")[:400],
    }


def license_preflight() -> dict[str, Any]:
    """Classify each source by what may be copied, before any clone is attempted."""
    rows = []
    blocked = []
    for source in SOURCES:
        rule = source["copy_rule"]
        may_copy = rule in ("COPY_WITH_ATTRIBUTION", "COPY_WITH_NOTICE")
        if rule in ("NO_COPY", "NO_COPY_UNTIL_LICENCE_READ", "LINK_ONLY_NO_VENDOR"):
            blocked.append(source["id"])
        rows.append(
            {
                **source,
                "may_copy_into_this_project": may_copy,
                "runtime_impact": "none: a clone is a study, never a runtime component",
            }
        )
    return {
        "sources": rows,
        "not_copyable": blocked,
        "default_verdict": (
            "no GPL/AGPL code is copied into this project by default; a clone that is "
            "studied stays outside the checkout and never becomes a runtime component"
        ),
    }


def fetch_pin(source: dict[str, Any], timeout_seconds: int = 180) -> dict[str, Any]:
    """Fetch exactly the pinned commit of one source into an isolated directory.

    A full ``git clone`` of these engines is large and slow enough to be interrupted,
    which leaves an empty shell whose pin cannot resolve. Fetching the single pinned
    object is both faster and *more* rigorous: it proves the exact SHA the brief names is
    reachable, rather than proving the default branch head is. The directory is created
    under the system temp root, never inside the checkout.
    """
    target = CLONE_ROOT / source["id"]
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    steps: list[dict[str, Any]] = []

    def run(args: list[str]) -> tuple[int, str]:
        code, out = _git(args, target, timeout=timeout_seconds)
        steps.append({"command": " ".join(args), "exit_code": code, "output": out[:200]})
        return code, out

    run(["init", "--quiet"])
    run(["remote", "add", "origin", f"https://github.com/{source['repo']}"])
    # No blob filter here: a filtered fetch stores the commit as a promisor object and
    # ``cat-file -e <sha>^{commit}`` then fails to peel it, because the peel tries to
    # lazily fetch an object the promisor remote will not serve by id. The tree and its
    # blobs are needed anyway to read the licence file, so the filter buys nothing.
    fetch_code, _ = run(["fetch", "--depth", "1", "origin", source["sha"]])
    # Anchor the fetched commit on a ref, so it is a normal object and not merely a
    # FETCH_HEAD side effect that a later gc could consider unreachable.
    run(["update-ref", f"refs/edge14/{source['id']}", source["sha"]])
    pin_code, _ = run(["cat-file", "-e", f"{source['sha']}^{{commit}}"])
    return {
        "id": source["id"],
        "repo": source["repo"],
        "pinned_sha": source["sha"],
        "target": str(target),
        "fetch_exit": fetch_code,
        "pin_resolves": pin_code == 0,
        "steps": steps,
    }


def clone_probe(timeout_seconds: int = 180) -> dict[str, Any]:
    """Fetch the pinned commit of every P0 source, outside the checkout.

    Reports ``CLONED`` when every pin resolved, or ``BENCHMARK_PARITY_BLOCKED`` with the
    command output when the host cannot reach the remotes. It never installs an engine and
    never mounts a credential.
    """
    net = network_available()
    if not net["available"]:
        return {
            "status": "BENCHMARK_PARITY_BLOCKED",
            "reason": "the host cannot reach the git remotes",
            "network_probe": net,
            "clone_root": str(CLONE_ROOT),
            "fetched": [],
            "note": "no fetch was attempted beyond the probe; nothing was installed",
        }
    CLONE_ROOT.mkdir(parents=True, exist_ok=True)
    fetched = [
        fetch_pin(source, timeout_seconds)
        for source in SOURCES
        if source["classification"].startswith("ADOPT_P0")
    ]
    all_resolved = bool(fetched) and all(row["pin_resolves"] for row in fetched)
    return {
        "status": "CLONED" if all_resolved else "CLONE_PARTIAL",
        "network_probe": net,
        "clone_root": str(CLONE_ROOT),
        "fetched": fetched,
        "note": (
            "each directory holds exactly one fetched commit and no working tree; nothing "
            "was installed, imported or run"
        ),
    }


def _licence_family(text: str) -> str:
    """Coarse licence family, read from the licence's *title*, not its whole body.

    The body matters for the wrong reason here: the GPL-3.0 text names "the GNU Affero
    General Public License" inside section 13, so a full-text search for AFFERO labels a
    plain GPL-3.0 file as AGPL. Restricting the search to the header area (the title) is
    what makes the classification say what the file actually licenses.

    ``NOASSERTION``, an empty string, and anything unrecognised resolve to ``UNKNOWN``,
    which the caller treats as NO_COPY: an unasserted licence is not a permission.
    """
    head = (text or "")[:600].upper()
    if "AFFERO" in head or "AGPL" in head:
        return "AGPL"
    if "LGPL" in head or "LESSER GENERAL PUBLIC" in head:
        return "LGPL"
    if "GPL" in head or "GENERAL PUBLIC LICENSE" in head:
        return "GPL"
    if "APACHE" in head:
        return "APACHE"
    if "MIT" in head:
        return "MIT"
    if "BSD" in head or "REDISTRIBUTION AND USE" in head:
        return "BSD"
    return "UNKNOWN"


def _git(args: list[str], cwd: Path, timeout: int = 60) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return 1, f"{type(exc).__name__}: {exc}"
    return completed.returncode, (completed.stdout or completed.stderr or "").strip()


def verify_pins() -> dict[str, Any]:
    """Verify each pinned SHA resolves in its clone and read its actual licence file.

    A pinned SHA that cannot be resolved is not a reproducible reference, and a declared
    licence that the licence *file* does not confirm is not a licence. Both are checked
    against the clone rather than trusted from the brief's table.
    """
    if not CLONE_ROOT.is_dir():
        return {
            "status": "NO_CLONES",
            "reason": "no clone directory exists; run clone_probe first",
            "verified": [],
        }
    verified = []
    for source in SOURCES:
        target = CLONE_ROOT / source["id"]
        if not target.is_dir():
            continue
        sha = source["sha"]
        pin_code, pin_out = _git(["cat-file", "-e", f"{sha}^{{commit}}"], target)
        if pin_code != 0:
            # Not fetched yet: fetch exactly this commit, anchor it, then re-check.
            _git(["fetch", "--depth", "1", "origin", sha], target, timeout=180)
            _git(["update-ref", f"refs/edge14/{source['id']}", sha], target)
            pin_code, pin_out = _git(["cat-file", "-e", f"{sha}^{{commit}}"], target)
        pin_resolves = pin_code == 0
        out = pin_out
        licence_text = ""
        for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "COPYING.md"):
            lic_code, lic_out = _git(["show", f"{sha}:{name}"], target)
            if lic_code == 0 and lic_out:
                licence_text = lic_out
                break
        file_family = _licence_family(licence_text)
        declared_family = _licence_family(source["declared_license"])
        # The rule follows the family, so the same header rule governs both fields.
        _family_rules = {
            "AGPL": ("NO_COPY", "strong copyleft: no code is copied into this project"),
            "GPL": ("NO_COPY", "copyleft: methodology is studied, code is not copied"),
            "LGPL": ("LINK_ONLY_NO_VENDOR", "weak copyleft: linked, never vendored"),
            "APACHE": ("COPY_WITH_NOTICE", "permissive: attribution and notice kept"),
            "MIT": ("COPY_WITH_ATTRIBUTION", "permissive: attribution kept"),
            "BSD": ("COPY_WITH_ATTRIBUTION", "permissive: attribution kept"),
        }
        rule, reason = _family_rules.get(
            file_family, ("UNKNOWN", "no licence file was readable at the pinned commit")
        )
        verified.append(
            {
                "id": source["id"],
                "repo": source["repo"],
                "pinned_sha": sha,
                "pin_resolves": pin_resolves,
                "fetch_output": out[:160],
                "licence_file_found": bool(licence_text),
                "licence_family_from_file": file_family,
                "licence_rule": rule,
                "licence_reason": reason,
                "declared_license": source["declared_license"],
                "declared_family": declared_family,
                "declared_matches_file": file_family != "UNKNOWN"
                and file_family == declared_family,
            }
        )
    pins_ok = all(row["pin_resolves"] for row in verified) if verified else False
    return {
        "status": "PINS_VERIFIED" if pins_ok else "PINS_INCOMPLETE",
        "verified": verified,
        "n_verified": len(verified),
        "n_pins_resolved": sum(1 for row in verified if row["pin_resolves"]),
        "note": (
            "a pin that does not resolve is not reproducible, and a licence is read from "
            "the licence file at the pinned commit, never from the README"
        ),
    }


def parity_plan() -> dict[str, Any]:
    """The neutral-strategy parity plan, with its tolerance frozen before the run."""
    return {
        "neutral_strategy": {
            "id": "NEUTRAL_MA_CROSS_1H",
            "rule": "long when ema(12) > ema(26) on closed 1h bars, flat otherwise",
            "why_neutral": "one plain rule, no fitted parameters, so a divergence is a model bug not a tuning choice",
        },
        "common_market_data": {
            "assets": ["BTC/USDT", "ETH/USDT"],
            "timeframe": "1h",
            "period": "OOS window already held out from EDGE-07/08 selection",
            "point_in_time": "decision uses bars whose close_time <= decision_time",
            "gaps": "counted and declared, never interpolated",
            "fingerprint": "sha256 over the canonical OHLCV matrix per asset",
        },
        "common_execution_assumptions": {
            "entry": "next bar open after the signal bar closes",
            "exit": "next bar open after the exit condition",
            "fees_bps_per_side": 10.0,
            "spread_bps": "from the admission scenario spread for the asset",
            "slippage_bps": "from the admission scenario impact for the asset",
            "lot_tick_min_notional": "venue minimums from the gate artefact",
            "fills": "one bar, no partials assumed",
        },
        "preregistered_tolerance": {
            "equity_relative_diff_max": 0.02,
            "trade_count_diff_max": 1,
            "per_trade_net_bps_diff_max": 1.0,
            "declared_before_run": True,
            "on_exceed": "quantify and explain the model difference; never adjust the output by hand",
        },
        "engines": ["trading_agentic", "jesse(SRC-02)"],
        "promotion": "NONE",
        "order_sent": False,
    }


def parity_payload() -> dict[str, Any]:
    return {
        "schema_version": "EDGE14_BENCHMARK_PARITY_V1",
        "work_package": "WP-EDGE-14C",
        "license_preflight": license_preflight(),
        "clone_probe": clone_probe(),
        "pin_verification": verify_pins(),
        "parity_plan": parity_plan(),
        "order_sent": False,
        "promotion": "NONE",
    }
