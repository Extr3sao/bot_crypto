# RFC-038 -- MANAGED FUTURES EVIDENCE DECISION

Audit whether RFC-037 rejected MF-TREND-001 for valid reasons, then decide whether modern futures data is worth acquiring for P1+P2. Frozen strategy; no tuning; no P2; no purchase.

## Verdict

RFC-037's rejection of MF-TREND-001 was **NOT** driven by valid evidence:
- **Capital**: G_CAP_RECON = **PASS** -> `RFC037_CAPITAL_DEFECT`. The +780% at $100M was a reference-rescaling artefact. Corrected, minimum viable capital = **25,000,000**, preferred = **50,000,000**.
- **Nulls**: G_NULL_VALIDITY = **PASS**, G_ADVERSARIAL = **PASS**. The RFC-037 market-label permutation is `NULL_MODEL_PARTIALLY_INVALID`; a valid market-preserving block-circular-shift null rejects at 5% in both windows.

MF-TREND-001 is therefore best classified **MODERN_VALIDATION_DATA_BLOCKED**, not economically rejected: it is blocked only by the absence of modern data.

## Decision

- Data acquisition decision = **BUY_CANDIDATE** (Databento -- GLBX.MDP3 (CME Globex MDP 3.0)).
- MODERN_DATA_STATUS = **PAID_CANDIDATE** (RFC-038 cannot exceed this without human approval). **No purchase was made.**
- Decision path = **A** (DATA ACQUISITION DECISION).

## PROJECT KPI

```
Historical executable validated edges = 1 / 1
Modern validated edges                 = 0 / 1
Historical robust edges                = 1 / 1
Paper candidates                       = 0 / 1
Forward profitable                     = 0
Live profitable                        = 0
Modern data status                     = PAID_CANDIDATE
```

## Three questions (final directive)

1. Was the RFC-037 capital test correctly computed? **NO** -- the fractional reference was never rescaled to the tested capital (`RFC037_CAPITAL_DEFECT`).
2. Was the null that failed it statistically adequate? **NO** -- market-label permutation is partially invalid; a valid market-preserving null rejects at 5%.
3. How much to know if the edge is alive today? **A paid modern dataset** (Databento, usage-based (metered by uncompressed bytes) or subscription (Standard $179-$199/month, 15+ yr history); full-history firm licence advertised at ~$4,500/month); cheapest credible shared P1+P2 option is Databento GLBX.MDP3 (~$179-$199/month or usage-based).

NEXT = **HUMAN DATA ACQUISITION DECISION** (no code until you decide). If approved, the FIRST experiment is the frozen MF-TREND-001 modern transport validation; P2 stays AUTHORIZED_WAITING.

