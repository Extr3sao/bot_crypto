# AUDITORIA DE RIESGO H6 — WP-EDGE-02B

| | |
|---|---|
| experimento | `AUD-EDGE01-H6-RISK` |
| audita | `ABL-EDGE01-H6` |
| ventana primaria | `DEV:BASE` / `plan_limit` |
| HEAD al ejecutar | `87f23577e0937c95a190187f23728a7b56349065` |
| veredicto | **`AUDIT_PASS`** |

183 of the 686 planned limit orders reached the level and the risk budget refused them (148 drawdown halt, 35 loss cooldown). Was the budget right at each of those instants, does the book keep its own invariants while refusing, and does the research budget's behaviour match the runtime Risk Engine's?

## Reproduccion del experimento auditado

- comparado con `reports/edge-recovery/WP-EDGE-01/retest-h6/RETEST.json`: **identico** (90 comparaciones)

## Ordenes y rechazos reconstruidos

| run | arm | ordenes | rellenos | rechazos por riesgo | motivos |
|---|---|---|---|---|---|
| `DEV:BASE:frozen_market` | `frozen_market` | 0 | 0 | 0 | risk_drawdown_halt: 493, risk_loss_cooldown: 17 |
| `DEV:BASE:plan_market` | `plan_market` | 0 | 0 | 0 | risk_drawdown_halt: 493, risk_loss_cooldown: 17 |
| `DEV:BASE:plan_limit` | `plan_limit` | 686 | 372 | 183 | risk_drawdown_halt: 148, risk_loss_cooldown: 35 |
| `DEV:2X_FEES:frozen_market` | `frozen_market` | 0 | 0 | 0 | risk_drawdown_halt: 546, risk_loss_cooldown: 15 |
| `DEV:2X_FEES:plan_market` | `plan_market` | 0 | 0 | 0 | risk_drawdown_halt: 546, risk_loss_cooldown: 15 |
| `DEV:2X_FEES:plan_limit` | `plan_limit` | 654 | 193 | 338 | risk_drawdown_halt: 316, risk_loss_cooldown: 22 |
| `VAL:BASE:frozen_market` | `frozen_market` | 0 | 0 | 0 | risk_loss_cooldown: 12 |
| `VAL:BASE:plan_market` | `plan_market` | 0 | 0 | 0 | risk_loss_cooldown: 12 |
| `VAL:BASE:plan_limit` | `plan_limit` | 350 | 269 | 15 | risk_loss_cooldown: 15 |
| `OOS:BASE:frozen_market` | `frozen_market` | 0 | 0 | 0 | risk_loss_cooldown: 8 |
| `OOS:BASE:plan_market` | `plan_market` | 0 | 0 | 0 | risk_loss_cooldown: 8 |
| `OOS:BASE:plan_limit` | `plan_limit` | 66 | 54 | 4 | risk_loss_cooldown: 4 |
| `OOS:2X_FEES:frozen_market` | `frozen_market` | 0 | 0 | 0 | risk_loss_cooldown: 5 |
| `OOS:2X_FEES:plan_market` | `plan_market` | 0 | 0 | 0 | risk_loss_cooldown: 5 |
| `OOS:2X_FEES:plan_limit` | `plan_limit` | 54 | 45 | 2 | risk_loss_cooldown: 2 |

## Cada rechazo de la ventana primaria, contra el estado que vio el presupuesto

- rechazos: **183**, correctos: **183**
- motivos: `risk_drawdown_halt`: 148, `risk_loss_cooldown`: 35
- auditoria completa (todas las ventanas y ramas): 2734 rechazos, 0 incorrectos
- acuerdo con la regla equivalente del Risk Engine de runtime: 2734/2734

| activo | instante | motivo | drawdown en el toque | halt | posiciones abiertas | trades hoy | correcto |
|---|---|---|---|---|---|---|---|
| `SOL` | `2025-04-27T18:45` | `risk_drawdown_halt` | 5.0041% | 5.0% | 0 | 2 | si |
| `BTC` | `2025-04-27T19:15` | `risk_drawdown_halt` | 5.0041% | 5.0% | 0 | 2 | si |
| `ETH` | `2025-04-28T05:30` | `risk_drawdown_halt` | 5.0041% | 5.0% | 0 | 0 | si |
| `BTC` | `2025-04-28T07:45` | `risk_drawdown_halt` | 5.0041% | 5.0% | 0 | 0 | si |
| `ETH` | `2025-04-28T10:45` | `risk_drawdown_halt` | 5.0041% | 5.0% | 0 | 0 | si |
| _(148 filas en total para `risk_drawdown_halt`; el CSV lleva todas)_ | | | | | | | |
| `SOL` | `2024-10-18T07:30` | `risk_loss_cooldown` | 0.2571% | 5.0% | 0 | 4 | si |
| `SOL` | `2024-10-19T15:30` | `risk_loss_cooldown` | 0.3778% | 5.0% | 0 | 1 | si |
| `BTC` | `2024-10-27T22:15` | `risk_loss_cooldown` | 0.6873% | 5.0% | 0 | 4 | si |
| `ETH` | `2024-10-27T22:15` | `risk_loss_cooldown` | 0.6873% | 5.0% | 0 | 4 | si |
| `BTC` | `2024-10-29T03:30` | `risk_loss_cooldown` | 0.7882% | 5.0% | 0 | 1 | si |
| _(35 filas en total para `risk_loss_cooldown`; el CSV lleva todas)_ | | | | | | | |

## Invariantes

| invariante | ambito | arm | resultado | detalle |
|---|---|---|---|---|
| `accounting_final_equity` | `DEV:BASE` | `frozen_market` | **PASS** | start 10,000.0000 + net -496.4298 = 9,503.5702 vs final 9,503.5702 |
| `cash_never_negative` | `DEV:BASE` | `frozen_market` | **PASS** | lowest equity mark 9,503.5702 (>= 0) |
| `sizing_at_or_below_configured_risk` | `DEV:BASE` | `frozen_market` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `DEV:BASE` | `frozen_market` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `DEV:BASE` | `frozen_market` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `DEV:BASE` | `frozen_market` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `DEV:BASE` | `frozen_market` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `DEV:BASE` | `frozen_market` | **PASS** | 0 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `DEV:BASE` | `frozen_market` | **PASS** | 0 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `DEV:BASE` | `frozen_market` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `DEV:BASE` | `plan_market` | **PASS** | start 10,000.0000 + net -496.4298 = 9,503.5702 vs final 9,503.5702 |
| `cash_never_negative` | `DEV:BASE` | `plan_market` | **PASS** | lowest equity mark 9,503.5702 (>= 0) |
| `sizing_at_or_below_configured_risk` | `DEV:BASE` | `plan_market` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `DEV:BASE` | `plan_market` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `DEV:BASE` | `plan_market` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `DEV:BASE` | `plan_market` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `DEV:BASE` | `plan_market` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `DEV:BASE` | `plan_market` | **PASS** | 0 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `DEV:BASE` | `plan_market` | **PASS** | 0 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `DEV:BASE` | `plan_market` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `DEV:BASE` | `plan_limit` | **PASS** | start 10,000.0000 + net -495.8756 = 9,504.1244 vs final 9,504.1244 |
| `cash_never_negative` | `DEV:BASE` | `plan_limit` | **PASS** | lowest equity mark 9,504.1244 (>= 0) |
| `sizing_at_or_below_configured_risk` | `DEV:BASE` | `plan_limit` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `DEV:BASE` | `plan_limit` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `DEV:BASE` | `plan_limit` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `DEV:BASE` | `plan_limit` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `DEV:BASE` | `plan_limit` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `DEV:BASE` | `plan_limit` | **PASS** | 686 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `DEV:BASE` | `plan_limit` | **PASS** | 183 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `DEV:BASE` | `plan_limit` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `DEV:2X_FEES` | `frozen_market` | **PASS** | start 10,000.0000 + net -501.7200 = 9,498.2800 vs final 9,498.2800 |
| `cash_never_negative` | `DEV:2X_FEES` | `frozen_market` | **PASS** | lowest equity mark 9,498.2800 (>= 0) |
| `sizing_at_or_below_configured_risk` | `DEV:2X_FEES` | `frozen_market` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `DEV:2X_FEES` | `frozen_market` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `DEV:2X_FEES` | `frozen_market` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `DEV:2X_FEES` | `frozen_market` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `DEV:2X_FEES` | `frozen_market` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `DEV:2X_FEES` | `frozen_market` | **PASS** | 0 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `DEV:2X_FEES` | `frozen_market` | **PASS** | 0 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `DEV:2X_FEES` | `frozen_market` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `DEV:2X_FEES` | `plan_market` | **PASS** | start 10,000.0000 + net -501.7200 = 9,498.2800 vs final 9,498.2800 |
| `cash_never_negative` | `DEV:2X_FEES` | `plan_market` | **PASS** | lowest equity mark 9,498.2800 (>= 0) |
| `sizing_at_or_below_configured_risk` | `DEV:2X_FEES` | `plan_market` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `DEV:2X_FEES` | `plan_market` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `DEV:2X_FEES` | `plan_market` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `DEV:2X_FEES` | `plan_market` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `DEV:2X_FEES` | `plan_market` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `DEV:2X_FEES` | `plan_market` | **PASS** | 0 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `DEV:2X_FEES` | `plan_market` | **PASS** | 0 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `DEV:2X_FEES` | `plan_market` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `DEV:2X_FEES` | `plan_limit` | **PASS** | start 10,000.0000 + net -495.5453 = 9,504.4547 vs final 9,504.4547 |
| `cash_never_negative` | `DEV:2X_FEES` | `plan_limit` | **PASS** | lowest equity mark 9,504.4547 (>= 0) |
| `sizing_at_or_below_configured_risk` | `DEV:2X_FEES` | `plan_limit` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `DEV:2X_FEES` | `plan_limit` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `DEV:2X_FEES` | `plan_limit` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `DEV:2X_FEES` | `plan_limit` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `DEV:2X_FEES` | `plan_limit` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `DEV:2X_FEES` | `plan_limit` | **PASS** | 654 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `DEV:2X_FEES` | `plan_limit` | **PASS** | 338 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `DEV:2X_FEES` | `plan_limit` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `VAL:BASE` | `frozen_market` | **PASS** | start 10,000.0000 + net -479.1833 = 9,520.8167 vs final 9,520.8167 |
| `cash_never_negative` | `VAL:BASE` | `frozen_market` | **PASS** | lowest equity mark 9,520.8167 (>= 0) |
| `sizing_at_or_below_configured_risk` | `VAL:BASE` | `frozen_market` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `VAL:BASE` | `frozen_market` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `VAL:BASE` | `frozen_market` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `VAL:BASE` | `frozen_market` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `VAL:BASE` | `frozen_market` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `VAL:BASE` | `frozen_market` | **PASS** | 0 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `VAL:BASE` | `frozen_market` | **PASS** | 0 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `VAL:BASE` | `frozen_market` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `VAL:BASE` | `plan_market` | **PASS** | start 10,000.0000 + net -479.1833 = 9,520.8167 vs final 9,520.8167 |
| `cash_never_negative` | `VAL:BASE` | `plan_market` | **PASS** | lowest equity mark 9,520.8167 (>= 0) |
| `sizing_at_or_below_configured_risk` | `VAL:BASE` | `plan_market` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `VAL:BASE` | `plan_market` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `VAL:BASE` | `plan_market` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `VAL:BASE` | `plan_market` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `VAL:BASE` | `plan_market` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `VAL:BASE` | `plan_market` | **PASS** | 0 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `VAL:BASE` | `plan_market` | **PASS** | 0 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `VAL:BASE` | `plan_market` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `VAL:BASE` | `plan_limit` | **PASS** | start 10,000.0000 + net -357.4449 = 9,642.5551 vs final 9,642.5551 |
| `cash_never_negative` | `VAL:BASE` | `plan_limit` | **PASS** | lowest equity mark 9,642.5551 (>= 0) |
| `sizing_at_or_below_configured_risk` | `VAL:BASE` | `plan_limit` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `VAL:BASE` | `plan_limit` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `VAL:BASE` | `plan_limit` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `VAL:BASE` | `plan_limit` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `VAL:BASE` | `plan_limit` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `VAL:BASE` | `plan_limit` | **PASS** | 350 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `VAL:BASE` | `plan_limit` | **PASS** | 15 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `VAL:BASE` | `plan_limit` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `OOS:BASE` | `frozen_market` | **PASS** | start 10,000.0000 + net -94.8077 = 9,905.1923 vs final 9,905.1923 |
| `cash_never_negative` | `OOS:BASE` | `frozen_market` | **PASS** | lowest equity mark 9,905.1923 (>= 0) |
| `sizing_at_or_below_configured_risk` | `OOS:BASE` | `frozen_market` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `OOS:BASE` | `frozen_market` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `OOS:BASE` | `frozen_market` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `OOS:BASE` | `frozen_market` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `OOS:BASE` | `frozen_market` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `OOS:BASE` | `frozen_market` | **PASS** | 0 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `OOS:BASE` | `frozen_market` | **PASS** | 0 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `OOS:BASE` | `frozen_market` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `OOS:BASE` | `plan_market` | **PASS** | start 10,000.0000 + net -94.8077 = 9,905.1923 vs final 9,905.1923 |
| `cash_never_negative` | `OOS:BASE` | `plan_market` | **PASS** | lowest equity mark 9,905.1923 (>= 0) |
| `sizing_at_or_below_configured_risk` | `OOS:BASE` | `plan_market` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `OOS:BASE` | `plan_market` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `OOS:BASE` | `plan_market` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `OOS:BASE` | `plan_market` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `OOS:BASE` | `plan_market` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `OOS:BASE` | `plan_market` | **PASS** | 0 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `OOS:BASE` | `plan_market` | **PASS** | 0 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `OOS:BASE` | `plan_market` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `OOS:BASE` | `plan_limit` | **PASS** | start 10,000.0000 + net -55.7084 = 9,944.2916 vs final 9,944.2916 |
| `cash_never_negative` | `OOS:BASE` | `plan_limit` | **PASS** | lowest equity mark 9,944.2916 (>= 0) |
| `sizing_at_or_below_configured_risk` | `OOS:BASE` | `plan_limit` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `OOS:BASE` | `plan_limit` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `OOS:BASE` | `plan_limit` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `OOS:BASE` | `plan_limit` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `OOS:BASE` | `plan_limit` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `OOS:BASE` | `plan_limit` | **PASS** | 66 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `OOS:BASE` | `plan_limit` | **PASS** | 4 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `OOS:BASE` | `plan_limit` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `OOS:2X_FEES` | `frozen_market` | **PASS** | start 10,000.0000 + net -133.2011 = 9,866.7989 vs final 9,866.7989 |
| `cash_never_negative` | `OOS:2X_FEES` | `frozen_market` | **PASS** | lowest equity mark 9,866.7989 (>= 0) |
| `sizing_at_or_below_configured_risk` | `OOS:2X_FEES` | `frozen_market` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `OOS:2X_FEES` | `frozen_market` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `OOS:2X_FEES` | `frozen_market` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `OOS:2X_FEES` | `frozen_market` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `OOS:2X_FEES` | `frozen_market` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `OOS:2X_FEES` | `frozen_market` | **PASS** | 0 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `OOS:2X_FEES` | `frozen_market` | **PASS** | 0 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `OOS:2X_FEES` | `frozen_market` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `OOS:2X_FEES` | `plan_market` | **PASS** | start 10,000.0000 + net -133.2011 = 9,866.7989 vs final 9,866.7989 |
| `cash_never_negative` | `OOS:2X_FEES` | `plan_market` | **PASS** | lowest equity mark 9,866.7989 (>= 0) |
| `sizing_at_or_below_configured_risk` | `OOS:2X_FEES` | `plan_market` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `OOS:2X_FEES` | `plan_market` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `OOS:2X_FEES` | `plan_market` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `OOS:2X_FEES` | `plan_market` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `OOS:2X_FEES` | `plan_market` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `OOS:2X_FEES` | `plan_market` | **PASS** | 0 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `OOS:2X_FEES` | `plan_market` | **PASS** | 0 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `OOS:2X_FEES` | `plan_market` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |
| `accounting_final_equity` | `OOS:2X_FEES` | `plan_limit` | **PASS** | start 10,000.0000 + net -87.9506 = 9,912.0494 vs final 9,912.0494 |
| `cash_never_negative` | `OOS:2X_FEES` | `plan_limit` | **PASS** | lowest equity mark 9,912.0494 (>= 0) |
| `sizing_at_or_below_configured_risk` | `OOS:2X_FEES` | `plan_limit` | **PASS** | 0 violation(s) of the configured risk per trade |
| `notional_within_caps` | `OOS:2X_FEES` | `plan_limit` | **PASS** | 0 cap violation(s) |
| `notional_at_or_above_minimum` | `OOS:2X_FEES` | `plan_limit` | **PASS** | 0 entry(ies) below the minimum notional |
| `open_positions_within_limit` | `OOS:2X_FEES` | `plan_limit` | **PASS** | 0 observation(s) above the open-position limit |
| `trades_per_day_within_limit` | `OOS:2X_FEES` | `plan_limit` | **PASS** | 0 day(s) above the daily trade limit |
| `one_outcome_per_order` | `OOS:2X_FEES` | `plan_limit` | **PASS** | 54 orders, 0 with an unknown outcome and 0 left resting |
| `refusals_are_attributed` | `OOS:2X_FEES` | `plan_limit` | **PASS** | 2 refused orders, 0 without a reason |
| `no_duplicate_refusals` | `OOS:2X_FEES` | `plan_limit` | **PASS** | 0 duplicated (asset, instant, reason) refusal(s) |

## Veredicto

- **`AUDIT_PASS`** — every audited refusal was justified by the state the budget saw and every declared invariant holds
- brecha de modelado: the research budget re-implements the runtime's limits; it does NOT model the runtime's daily loss limit, weekly loss limit, daily drawdown, weekend block, spread/ATR blocks or the kill switch. A live run of the same book therefore blocks AT LEAST as often, never less.

## Limites

- the observing wrapper records the state the frozen simulator's own entry path computed; it changes no value and is restored in a finally block, but it is the same process as the run it observes
- the independent reconstruction of the same state from the published trade ledger and the local corpus is done by scripts/edge01_wp02_verify.py, in a separate process that imports nothing from the package
- the research budget models a subset of the runtime Risk Engine's rules, so this audit's verdict is about the subset, never a statement that live trading would behave identically
- long side only (spot); no historical order book; nothing is wired into PAPER
