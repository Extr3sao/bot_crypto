#!/usr/bin/env bash
# scripts/tsk-013.10-resweep.sh
#
# Gate TSK-013.10 sweep — verbatim rg + grep sequence from
# `.ai/commands/04-plan.md` Gate TSK-013.10.
#
# Purpose: after the TSK-013.8 + TSK-013.9 squash-merge lands on
# origin/main (fixing `rate_limit_ms` / `max_backoff_ms` on
# tests/unit/market_data/test_ccxt_connector.py), run this script
# on a clean checkout to:
#
#   PASS 1 (rg):  surface every test/fixture hit against the
#                 bounded-field candidate pattern declared in the gate.
#   PASS 2 (grep): surface every bounded Field declaration in
#                  src/trading_bot/config/*.py (the cross-reference
#                  required by the gate spec).
#
# Per gate spec, manual triage is REQUIRED on every rg hit before
# the PR can merge. Script exit code is informational ONLY; rc=0
# means "sweep completed", never "safe to merge".
#
# Usage:
#   ./scripts/tsk-013.10-resweep.sh
#   ./scripts/tsk-013.10-resweep.sh --repo-root=/path/to/repo
#
# Exit codes:
#   0  sweep completed cleanly  (output informational; manual triage decides)
#   1  ripgrep (rg) not on PATH
#   2  repo root does not contain src/trading_bot/config/
#   3  parse error / runtime failure
#
# Cherry-pick-safe: relative paths resolved at run-time, no hard-
# coded absolute paths. Verbatim rg + grep patterns copied from the
# gate spec so behaviour cannot drift across cherry-picks.
#
# Limitations (per reviewer round-2):
#   Coverage-evolution drift detection receives a PARTIAL signal:
#   the Drift-invitation section tokenises identifier names on
#   constraint-bearing lines, which surfaces the field name when
#   Pydantic v2 syntax `name: T = Field(default, ge=N)` keeps the
#   LHS on the same line as the constraint. Token noise (Python
#   keywords `int`, `Field`, `Optional`, `List`, etc. leak in)
#   requires the operator to diff against the rg-pattern name list
#   above. Full AST-level binding (per-field → per-constraint) is
#   out of scope for bash and remains an open ADR-0016 follow-up.
#
# Cross-link:
#   - .ai/commands/04-plan.md              (gate definition)
#   - tasks/backlog.md TSK-013.10          (catalog maintenance)
#   - tasks/decisions.md ADR-0016 / 0017   (umbrella + drift precedents)

set -euo pipefail

# ---------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------
REPO_ROOT="$(pwd)"
for arg in "$@"; do
  case "$arg" in
    --repo-root=*)
      REPO_ROOT="${arg#*=}"
      ;;
    --help|-h)
      sed -n '2,46p' "$0"
      exit 0
      ;;
    *)
      printf '[FATAL] unknown argument: %s\n' "$arg" >&2
      exit 3
      ;;
  esac
done

# ---------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------
if ! command -v rg >/dev/null 2>&1; then
  printf '[FATAL] ripgrep (rg) required but not on PATH.\n' >&2
  printf '        Install: https://github.com/BurntSushi/ripgrep\n' >&2
  exit 1
fi
if [[ ! -d "$REPO_ROOT/src/trading_bot/config" ]]; then
  printf '[FATAL] %s/src/trading_bot/config not found.\n' "$REPO_ROOT" >&2
  exit 2
fi

cd "$REPO_ROOT"

# ---------------------------------------------------------------
# Verbatim patterns from `.ai/commands/04-plan.md` Gate TSK-013.10.
# Edit ONLY via the Coverage evolution rule (gate spec).
# ---------------------------------------------------------------
RG_PATTERN='rate_limit_ms|max_backoff_ms|initial_backoff_ms|max_attempts|request_ms|recv_window_ms|max_open_positions|max_trades_per_day|max_risk_per_trade_pct|max_asset_exposure_pct|max_total_exposure_pct|min_order_notional_usdt|max_order_notional_usdt|default_stop_loss_pct|default_take_profit_pct|min_24h_volume_usdt|max_spread_bps|max_atr_percent|min_atr_percent|consecutive_loss_cooldown_minutes|prometheus_port'
GREP_PATTERN='\b(ge|gt|le|lt|min_length|max_length|pattern)\s*=\s*[0-9]'

# ---------------------------------------------------------------
# PASS 1: rg first-pass candidate sweep (tests/)
# ---------------------------------------------------------------
printf '\n=== PASS 1: rg bounded-field candidate sweep (tests/) ===\n'
printf 'rg pattern (verbatim from gate spec):\n%s\n\n' "$RG_PATTERN"

# rg exit: 0 = hits found, 1 = no hits, >=2 = error.
set +e
RG_OUTPUT=$(rg --no-heading --line-number "$RG_PATTERN" -g 'tests/**/*.py' 2>&1)
RG_RC=$?
set -e
RG_HIT_COUNT=0
case "$RG_RC" in
  0)
    RG_HIT_COUNT=$(printf '%s\n' "$RG_OUTPUT" | wc -l | tr -d ' ')
    printf '[HITS] %s candidate(s) in tests/ matching the rg pattern:\n' "$RG_HIT_COUNT"
    printf '%s\n' "$RG_OUTPUT"
    ;;
  1)
    printf '[OK] no rg hits in tests/ — no candidates to triage.\n'
    ;;
  *)
    printf '[ERROR] rg exited %s:\n%s\n' "$RG_RC" "$RG_OUTPUT" >&2
    exit 3
    ;;
esac

# ---------------------------------------------------------------
# PASS 2: grep declared bounded fields in config models
# ---------------------------------------------------------------
printf '\n=== PASS 2: grep declared bounded fields in src/trading_bot/config/*.py ===\n'
printf 'grep pattern (verbatim from gate spec):\n%s\n\n' "$GREP_PATTERN"

set +e
GREP_OUTPUT=$(grep -rnE "$GREP_PATTERN" src/trading_bot/config/*.py 2>&1)
GREP_RC=$?
set -e
GREP_HIT_COUNT=0
case "$GREP_RC" in
  0)
    GREP_HIT_COUNT=$(printf '%s\n' "$GREP_OUTPUT" | wc -l | tr -d ' ')
    printf '[HITS] %s bounded-field declaration(s):\n' "$GREP_HIT_COUNT"
    printf '%s\n' "$GREP_OUTPUT"
    ;;
  1)
    printf '[OK] no bounded fields declared in models.\n'
    ;;
  *)
    printf '[ERROR] grep exited %s:\n%s\n' "$GREP_RC" "$GREP_OUTPUT" >&2
    exit 3
    ;;
esac

# ---------------------------------------------------------------
# Side-by-side drift-invitation (manual eyeball required)
# ---------------------------------------------------------------
# We extract tokens from PASS 2's grep-output lines — these are the
# identifier names that CO-OCCUR with constraint-bearing lines.
# NOTE: the token list catches Python/Pydantic noise (`int`, `Field`,
# `Optional`, `List`, `Annotated`, `Literal`, etc.). The operator
# diffs against the rg-pattern name list above to spot genuine drift.
printf '\n=== Drift invitation (manual eyeball required) ===\n'
printf 'rg-pattern names (PASS 1 candidate list):\n  '
printf '%s\n' "$RG_PATTERN" | tr '|' '\n' | sort -u | xargs
printf '\nField-name tokens observed at PASS 2 grep hits (best-effort):\n'
# Extract IDENT tokens on the same line as a Field constraint; this is
# a fingerprint, not a complete mapping. We DO NOT claim it is drift-
# free; we just list ALL distinct identifiers on the constraint lines
# so the operator can search for any name NOT in the rg pattern above.
set +e
PASS2_TOKENS=$(printf '%s\n' "${GREP_OUTPUT:-}" \
  | grep -oE '\b[A-Za-z_][A-Za-z0-9_]{3,}\b' \
  | sort -u | xargs)
set -e
if [[ -n "${PASS2_TOKENS}" ]]; then
  printf '  %s\n' "$PASS2_TOKENS"
else
  printf '  (no PASS 2 tokens)\n'
fi

# ---------------------------------------------------------------
# Manual triage reminder (per gate spec)
# ---------------------------------------------------------------
printf '\n=== MANUAL TRIAGE REQUIRED (from .ai/commands/04-plan.md) ===\n'
cat <<'EOF'
For every rg hit in PASS 1, classify it before merge:

  [VALID]              value >= constraint floor         OK, no action
  [VIOLATION]          value <  constraint floor         FIX fixture first
  [BYPASS intencional] uses model_construct()            deuda potencial (TSK-013.10 catalogue)
  [NEGATIVE TEST]      invalid value under pytest.raises OK, pins contract
  [FIELD-DEPRECATED]   fixture passes removed field      cleanup required (extra=forbid breaks; extra=ignore swallows)

Drift detection (PASS 2 → PASS 1 name match):
  Any token in PASS 2 (sorted above) that is NOT a substring of any
  name in the rg pattern is a Coverage-evolution drift signal. The
  PR that introduced the missing field must self-extend the rg
  pattern in .ai/commands/04-plan.md in the SAME commit; otherwise
  the rg sweep silently misses the constraint.
EOF

# ---------------------------------------------------------------
# Summary + STATUS verdict
# ---------------------------------------------------------------
printf '\n=== SUMMARY ===\n'
printf 'rg hits  (PASS 1): %s\n' "$RG_HIT_COUNT"
printf 'grep hits (PASS 2): %s\n' "$GREP_HIT_COUNT"
printf 'repo root:          %s\n' "$REPO_ROOT"
printf '\n'
if [[ "$RG_HIT_COUNT" -gt 0 ]]; then
  printf '[STATUS TILT: NEEDS-TRIAGE            ] RG hits present; manual triage required.\n'
else
  printf '[STATUS TILT: CROSS-CHECK-DRIFT-ONLY   ] no rg hits; PASS 2 grep still needs drift eyeball.\n'
fi
printf 'Exit 0: sweep completed. Manual triage decides merge readiness.\n'
exit 0
