#!/usr/bin/env bash
# ============================================================
# Hermetic certification environment (CP-PO-003.1 STEP 3/4).
#
# Wraps a command with a scrubbed environment so that local
# operator configuration (shell exports, real .env credentials)
# cannot influence L5 certification runs.
#
# Usage:
#   scripts/cert_env.sh uv run pytest tests/unit -q
#   scripts/cert_env.sh uv run pytest tests/unit/cert -q
#   scripts/cert_env.sh uv run python scripts/verify_l5_independent.py
#   scripts/cert_env.sh uv run python scripts/start_paper_trading.py --max-cycles 2
#
# Guarantees:
#   - Every credential / live-selection variable is UNSET.
#     Both the flat env names (FLAT_ENV_ALIASES in
#     trading_bot/config/settings.py + direct os.getenv calls)
#     and the pydantic-settings nested names (env_nested_delimiter
#     "__" -> RUNTIME__MODE, EXCHANGE__API_KEY, ...) are scrubbed.
#   - CERT_HERMETIC=1 is exported so the permanent pytest guard
#     (tests/unit/cert/test_cert_env_isolation.py) activates and
#     verifies the full scrub before/while certification runs.
#   - Safety then comes from the COMMITTED configuration defaults
#     (config/runtime.yaml: mode "paper", live_trading_enabled false;
#     config/exchange.yaml: empty api_key, sandbox true), which the
#     guard asserts.
#
# The operator's real .env is never read, copied or modified: from a
# clean worktree no .env exists, and the guards load settings with
# env_file=None so the operator .env cannot leak into certification.
# ============================================================
set -euo pipefail

CERT_SCRUBBED_VARS=(
  # ---- FLAT_ENV_ALIASES (trading_bot/config/settings.py): live selection
  "TRADING_MODE"
  "LIVE_TRADING_ENABLED"
  "I_UNDERSTAND_THE_RISKS"
  # ---- FLAT_ENV_ALIASES: exchange selection + credentials
  "EXCHANGE_ID"
  "RUNTIME_EXCHANGE_ID"
  "EXCHANGE_API_KEY"
  "EXCHANGE_API_SECRET"
  "EXCHANGE_PASSWORD"
  "EXCHANGE_SANDBOX"
  # ---- pydantic-settings nested forms (env_nested_delimiter "__")
  "RUNTIME__MODE"
  "RUNTIME__LIVE_TRADING_ENABLED"
  "RUNTIME__EXCHANGE_ID"
  "RUNTIME__I_UNDERSTAND_THE_RISKS"
  "EXCHANGE__ID"
  "EXCHANGE__API_KEY"
  "EXCHANGE__API_SECRET"
  "EXCHANGE__PASSWORD"
  "EXCHANGE__SANDBOX"
  # ---- Direct os.getenv (trading_bot/market_data/bitunix.py, bitunix_futures.py)
  "BITUNIX_API_KEY"
  "BITUNIX_API_SECRET"
  # ---- Generic credential spellings + persistence target
  "API_KEY"
  "API_SECRET"
  "DATABASE_URL"
)

for var in "${CERT_SCRUBBED_VARS[@]}"; do
  unset "${var}" 2>/dev/null || true
done

export CERT_HERMETIC=1

exec "$@"