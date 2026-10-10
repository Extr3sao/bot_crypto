# RFC-049 — FINAL REPORT (PHASE A)

- CURRENT_HEAD: `cba8a337e802e66941a7ba72af71c499322bd2fa`
- RFC049_STATUS: **RFC049_PREPARED_AWAITING_CAMPAIGN_AUTHORIZATION**
- campaigns executed: **0** · economic results: **none** · FALSE_SUCCESS: **0**

## What Phase A did

- audited the baseline (RFC-048V state, governance, cost model, instruments, datasets, closed lines)
- retrieved, hashed and coverage-audited the new vendor series (stablecoin supply, hashrate, FRED macro)
- froze **2** hypothesis specifications and registered **1** deferred candidate and **6** reviewed-and-rejected ideas
- declared a three-class exposure policy and a sealed forward OOS for the decisive test
- stopped at the activation gate: `NEXT_CAMPAIGN = NOT_AUTHORIZED`

## What Phase A did not do

- no signal, no return, no PnL and no trade was computed
- no parameter was searched
- no result file contains a number that a campaign would need to produce

## Acceptance criteria

| id | criterion | status | evidence |
| --- | --- | --- | --- |
| ACC-049-01 | Baseline runtime auditado | PASS | data/rfc049/BASELINE_AUDIT.json (HEAD, RFC-048V state, cost model, instruments, datasets) |
| ACC-049-02 | Tres hipótesis como máximo | PASS | 2 admitted + 1 deferred candidate + 6 recorded rejections (data/rfc049/HYPOTHESIS_REGISTRY.json) |
| ACC-049-03 | Fuentes y mecanismos verificables | PASS | docs/research/RFC049_SOURCE_REGISTRY.md; every source read at full-text level or vendor-metadata level |
| ACC-049-04 | Especificaciones congeladas antes de evaluar | PASS | data/rfc049/specs/*.json + PREREGISTRATION_MANIFEST.json freeze timestamp and canonical hashes |
| ACC-049-05 | Datos PIT válidos | BLOCKED | PIT conventions declared per series and audited at coverage level; the executable PIT audit runs only with the campaign |
| ACC-049-06 | OOS realmente no utilizado o correctamente clasificado como expuesto | PASS | data/rfc049/DATA_EXPOSURE_AUDIT.json: every historical window classed RESEARCH_EXPOSED; sealed forward OOS defined |
| ACC-049-07 | Costes por instrumento | PASS | spot COST_MODEL_V3 re-derived at 200/1000 USDT (BASELINE_AUDIT); no admitted hypothesis uses futures, so the experimental futures model is not required |
| ACC-049-08 | Riesgo determinista aplicado | NOT_RUN | risk engine is RFC-048V-certified offline but no simulation has been executed (campaign not authorized) |
| ACC-049-09 | Sin optimización no autorizada | PASS | 0 parameter searches declared; freeze before measurement; no economic computation performed in Phase A |
| ACC-049-10 | Evaluación económica reproducible | NOT_RUN | ECONOMIC_RESULTS.json = NOT_RUN contract with the per-run schema prepared |
| ACC-049-11 | Robustez calculada | NOT_RUN | ROBUSTNESS_REPORT.json = NOT_RUN contract with the planned battery |
| ACC-049-12 | Comparación con baselines adecuados | PASS (declared) | buy-and-hold, 200d trend baseline and sibling-hypothesis controls frozen in every admitted spec |
| ACC-049-13 | Verificador independiente | PASS (Phase A scope) | scripts/rfc049_verify.py, builder-free, re-derives every hash and claim; campaign-level verification remains NOT_RUN |
| ACC-049-14 | Negative controls | PASS (Phase A scope) | INDEPENDENT_VERIFICATION.json negative controls (tampered hash, missing result, governance drift) |
| ACC-049-15 | FALSE_SUCCESS = 0 | PASS (Phase A scope) | no PASS is recorded without evidence; FALSE_SUCCESS counted in INDEPENDENT_VERIFICATION.json |
| ACC-049-16 | Sin trading real | PASS | LIVE_TRADING=DISABLED, TRADES_AUTHORIZED=0; no order path exists in the admitted specs |
| ACC-049-17 | Sin promoción automática | PASS | candidate states capped at ADMITTED_FOR_PREREGISTRATION; ELIGIBLE_FOR_PAPER_REVIEW not reachable in Phase A |
| ACC-049-18 | Stop rules respetadas | PASS | the activation gate stopped the campaign at WP-049-05; no experiment budget consumed |
| ACC-049-19 | Evidencias completas | PASS | all 17 required artifacts present and hashed (FINAL_REPORT.json manifest) |
| ACC-049-20 | Tests dirigidos al mismo runtime evaluado | NOT_RUN | no runtime execution occurs in Phase A; the Phase B requirement stays open |

## Economic conclusion (plain language)

- **What was investigated**: three mechanisms with free, verifiable data and a causal story — stablecoin primary issuance, US dollar net liquidity, and miner supply stress.
- **What was admitted**: the two liquidity mechanisms, with frozen rules and sealed forward OOS.
- **What was deferred**: miner supply stress, because its event frequency cannot support the preregistered sample floor; it is kept for a later, feasible design.
- **What was rejected before admission**: six further ideas, recorded with reasons in the registry.
- **What would be needed to advance**: campaign authorization; then a dev/validation run on exposed history, and a single sealed OOS opening with real forward observations.
- **Is any candidate eligible for paper review?** No. Nothing has been evaluated; eligibility cannot exist before an economic run, and paper promotion is a separate gate with capital implications.

## Honest limitations

- all historical windows are research-exposed; the confirmatory evidence is necessarily forward
- the two admitted hypotheses share a `liquidity -> risk appetite` family label; the frozen cross-incremental tests are the control, and if either fails them it is rejected, not renamed
- H-049-001's source for its exact construction is the vendor series itself; the academic sources support the mechanism (exchange-flow variant) and one of them is explicit counter-evidence
- the cost model's execution terms are ESTIMATED; fees are KNOWN and published, not account-verified
