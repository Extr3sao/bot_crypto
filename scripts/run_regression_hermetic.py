"""Hermetic regression runner (GOV-05, SHADOW-AND-LEGACY-VALIDATION-01).

The recurring baseline failure (``test_load_settings_happy_path``: bybit vs
binance) is HOST-driven: this shell exports ``EXCHANGE_ID=bybit`` (and
friends) from the local ``.env``, and pydantic-settings legitimately honors
real environment variables over file defaults. The repository default is NOT
wrong, so we do not alter application defaults to make tests pass.

Instead this runner strips ALL project-relevant host environment variables so
the suite sees only repository defaults (plus the real ``.env`` file, which
is the documented load path). That makes regression reproducible
independent of the host shell.

Usage:

    python scripts/run_regression_hermetic.py [extra pytest args...]

Exit code: pytest's exit code (0 = hermetic suite green).
"""

from __future__ import annotations

import os
import subprocess
import sys

#: Project-relevant env vars stripped from the child process. Anything a
#: user may legitimately export for the app (exchange config, campaign
#: switches) belongs here; PATH/SystemRoot/etc. are preserved.
HERMETIC_STRIP_PREFIXES = (
    "EXCHANGE_",  # EXCHANGE_ID, EXCHANGE_API_KEY, EXCHANGE_SANDBOX, ...
    "POC01_",
    "CAMPAIGN_",
    "TRADING_",
)

HERMETIC_STRIP_EXACT = (
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BYBIT_API_KEY",
    "BYBIT_API_SECRET",
    "BITUNIX_API_KEY",
    "BITUNIX_API_SECRET",
)


def hermetic_env() -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(k.startswith(p) for p in HERMETIC_STRIP_PREFIXES)
        and k not in HERMETIC_STRIP_EXACT
    }
    # Deterministic locale/timezone for reproducible timestamps in output.
    env.setdefault("PYTHONHASHSEED", "0")
    env["TZ"] = "UTC"
    return env


def main(argv: list[str]) -> int:
    cmd = [sys.executable, "-m", "pytest", *argv]
    print("[hermetic] stripping host env prefixes:", HERMETIC_STRIP_PREFIXES)
    print("[hermetic] running:", " ".join(cmd))
    return subprocess.call(cmd, env=hermetic_env())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
