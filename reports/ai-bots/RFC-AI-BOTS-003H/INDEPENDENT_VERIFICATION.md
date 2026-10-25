# INDEPENDENT_VERIFICATION — RFC-TAP-AI-BOTS-003H

**Sesión verificada:** `reports/ai-bots/RFC-AI-BOTS-003H/smoke`
**Herramienta:** [ai_bots_003h_verify.py](../../../scripts/ai_bots_003h_verify.py)
**Resultado:** **33 PASS / 0 FAIL**, exit 0 · **imports de `trading_bot`: 0**
**Veredicto de independencia:** `INDEPENDENT_VERIFICATION_PENDING` — el verificador lo escribió
el mismo agente que construyó el código. Lo que sigue es verificación *de bytes*, no revisión
por un tercero.

---

## 1. Qué es

El verificador de 003H **importa** el de 003G (`scripts/ai_bots_003g_verify.py`, sin
modificarlo) y añade ocho checks. Los 25 primeros son exactamente los de 003G —cadena del
stream, minutos cerrados y ordenados, series de 5 m reconstruidas por hash, `data_time ≤
decision_time`, precio de cada relleno, rango post-relleno, identidad de PnL, cadenas de
ledger, prefijo determinista, hashes del runtime y ausencia de ruta LIVE— y siguen ejecutándose
byte a byte.

Los ocho nuevos atacan el defecto D5 y los huecos de validación que 003G dejó:

| # | check | qué recomputa | resultado |
| --- | --- | --- | --- |
| 26 | `accounting_contract_is_versioned_and_defined` | que cada término de coste/PnL exista, con su significado, bajo `paper-accounting/2` | PASS |
| 27 | `costs_usdt_still_means_realised_cost` | `costs_usdt` contra la suma de las patas de las filas `CLOSE` | PASS (0 = 0) |
| 28 | `open_position_commissions_are_accrued_once` | el devengo desde las filas `FILL` (`entry_commission_usdt`), y que `costs_total = costs_usdt + devengado` | PASS (0,5 = 0,5) |
| 29 | `marked_equity_rebuilds_from_raw_minutes` | marca del **JSONL 1 m**, precio de entrada del `FILL`, comisión del `FILL` → equity marcado | PASS (10 000,49443125) |
| 30 | `no_position_is_counted_twice` | `position_id` abiertos ∩ cerrados, y una fila `FILL` por posición | PASS |
| 31 | `fill_instants_are_ordered_and_named` | `received ≤ quote_ts`, `quote_lag = quote_ts − received`, `opinion_age = quote_ts − decision_ts` | PASS |
| 32 | `live_minutes_were_seen_after_they_settled` | minutos con `open_ms ≥ inicio de sesión` vistos al menos `settle_ms` tras su cierre | PASS (62 minutos, mínimo 2 544 ms ≥ 2 500) |
| 33 | `session_summary_matches_the_lane_ledger` | la proyección `SUMMARY.json` contra la fila `RUN_END` del ledger | PASS |

Salida completa: [smoke/VERIFICATION_003H.md](smoke/VERIFICATION_003H.md),
[VERIFICATION.json](VERIFICATION.json).

## 2. Prueba de que no es vacuo

Un verificador que pasa siempre no verifica nada. El mismo programa, sobre la sesión **de 003G**
—producida por el código anterior al contrato— da:

```text
$ python scripts/ai_bots_003h_verify.py --session reports/ai-bots/RFC-AI-BOTS-003G/session       --root . --out-dir logs/rfc003h/003h-on-003g
**Checks:** 28 PASS / 5 FAIL (33 total)        exit 1
FAIL tested_runtime_equals_used_runtime            (drift declarado, STATE_AUDIT.md §6.1)
FAIL accounting_contract_is_versioned_and_defined  schema=None, 8 términos ausentes
FAIL open_position_commissions_are_accrued_once    la sesión no publica la comisión devengada
FAIL marked_equity_rebuilds_from_raw_minutes       no hay términos con los que reconstruir
FAIL session_summary_matches_the_lane_ledger       la proyección no publica contabilidad
```

Es la respuesta correcta: esa sesión **no dice** que su posición abierta debía 0,5 USDT, y un
lector no puede aceptarla como completa. Cuatro de los cinco fallos son eso; el quinto es el
drift de runtime. Salida y JSON en `logs/rfc003h/003h-on-003g*`.

## 3. Qué NO cubre

1. **Independencia de autor.** Mismo agente constructor y verificador.
2. **Economía.** 1 relleno, 0 cierres: la identidad de PnL de operaciones cerradas es
   trivialmente cierta en esta sesión. La rama de cierre está probada por tests
   (`test_a_close_moves_the_commission_from_accrued_to_realised_once`), no por esta sesión.
3. **Proveedor real.** `paper-script`; nada aquí mide un modelo.
4. **Mercado.** Una sola ventana de 45 minutos, dos símbolos, un régimen.
5. **Coste del modelo.** 0,00 USD por construcción.
