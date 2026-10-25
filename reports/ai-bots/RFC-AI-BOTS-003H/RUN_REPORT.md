# RUN_REPORT — RFC-TAP-AI-BOTS-003H

**Fecha:** 2026-10-19 · **Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Base Git:** `fe9b5e2` · **Commit que contiene este informe:** `git log -1 -- reports/ai-bots/RFC-AI-BOTS-003H/RUN_REPORT.md`
**Modo:** PAPER · **LIVE:** no habilitado (sin ruta de orden) · **`config/risk.yaml`:** leído,
nunca escrito · **`REAL_MODEL_CALLED=false`** · **`FALSE_SUCCESS=0`**

---

## 1. Entorno congelado

```text
$ git rev-parse HEAD && git rev-parse --abbrev-ref HEAD
fe9b5e2623b0d023833249e9687b753eaacd27d4
agent/ai-bots/RFC-TAP-AI-BOTS-003
$ ./.venv/Scripts/python.exe --version
Python 3.11.15
```

Antes del smoke se congelaron 11 ficheros de runtime con su sha256 en
`logs/rfc003h/freeze.json`; la sesión guardó los mismos hashes en
`smoke/SESSION_START.json → runtime_sha256`, y el verificador comprueba que coinciden con los
bytes presentes (`tested_runtime_equals_used_runtime`).

## 2. Comandos ejecutados (exit code real)

```text
pytest tests/unit/market_data tests/unit/vision/test_accounting_integrity.py \
       tests/unit/observability/test_dashboard_server.py -q
  159 passed                                                          exit 0
pytest tests/unit/vision tests/unit/market_data tests/unit/paper \
       tests/unit/observability -q
  445 passed                                                          exit 0
pytest tests/unit/vision tests/unit/market_data tests/unit/paper tests/unit/risk \
       tests/unit/intelligence tests/unit/reports tests/unit/observability -q
  671 passed                                                          exit 0
ruff check <8 ficheros nuevos o tocados>                              exit 0
mypy src/trading_bot/{vision/lane,vision/prospective,market_data/minute_collector}.py
  Success: no issues found                                            exit 0
pytest tests/unit/observability/test_dashboard_server.py -q        (con escritor concurrente)
  14 passed                                                           exit 0
scripts/ai_bots_003g_paper.py --out .../003H/smoke --duration-s 3600 --max-cycles 10
  10 ciclos, 1 relleno                                                exit 0
scripts/ai_bots_003h_verify.py --session .../003H/smoke --root .
  33 PASS / 0 FAIL                                                    exit 0
scripts/ai_bots_003g_compare.py --session .../003H/smoke              exit 0
scripts/ai_bots_003g_compare.py --session .../003H/smoke --full-store exit 0
scripts/ai_bots_003g_verify.py --session .../003G/session --root .
  24 PASS / 1 FAIL (drift de runtime declarado, STATE_AUDIT.md §6.1)   exit 1
```

De los 671 de la regresión ancha, los dos únicos comandos posteriores tocaron **solo scripts**
(`ai_bots_003g_compare.py`, `ai_bots_003h_verify.py`), no módulos bajo test; el subconjunto que
incluye el test limpiado después volvió a correr: **159 passed**.

## 3. Smoke PAPER con código congelado

**Directorio:** `reports/ai-bots/RFC-AI-BOTS-003H/smoke/`
**Inicio:** 2026-10-19T09:03:19Z · **10 ciclos** de 5 m · **0 ciclos bloqueados**
**Datos:** 286 minutos reales por símbolo (04:59→09:44 UTC), 0 gaps, 0 duplicados almacenados.
**Retardo de entrega medido:** 8 462 ms (p95) · **latencia declarada:** 30 000 ms.
**Prefijo determinista:** 18/18 filas comparadas en el ciclo final, `ok=true`; `data_time ≤
decision_time` en 10/10 ciclos.

| Ciclo | Vela 5 m | `data_time` | `decision_time` | Filas ledger | Prefijo comparado | Rellenos |
| ---: | --- | --- | --- | ---: | ---: | ---: |
| 1 | 08:55 | 09:00 | 09:04:10.920 | 2 | 0 | 0 |
| 2 | 09:00 | 09:05 | 09:05:13.296 | 5 | 0 | 0 |
| 3 | 09:05 | 09:10 | 09:10:12.696 | 8 | 2 | 1 |
| 4 | 09:10 | 09:15 | 09:15:13.182 | 10 | 6 | 1 |
| 5 | 09:15 | 09:20 | 09:20:14.296 | 12 | 8 | 1 |
| 6 | 09:20 | 09:25 | 09:25:15.387 | 14 | 10 | 1 |
| 7 | 09:25 | 09:30 | 09:30:11.040 | 16 | 12 | 1 |
| 8 | 09:30 | 09:35 | 09:35:15.188 | 18 | 14 | 1 |
| 9 | 09:35 | 09:40 | 09:40:17.353 | 20 | 16 | 1 |
| 10 | 09:40 | 09:45 | 09:45:15.079 | 22 | 18 | 1 |

`cycles/cycle-000N/ledger.jsonl` sigue siendo el ledger **acumulado** (2, 5, 8, 10, … 22 filas).
El ledger final contiene 18 filas `DECISION` (9 ciclos × 2 símbolos; el ciclo 1 no decide porque
la sesión sólo decide desde su propio inicio), 1 `DECISION_OUTCOME`, 1 `FILL` y las filas
`RUN`/`RUN_END`. El comparador cuenta 18 decisiones en la ventana prospectiva.

### 3.1 Traza del relleno

```text
DECISION      BTC/USDT OPEN_LONG      decision_ts=09:05:08.462Z  decision_seq=2
              (declared provider latency 30 000 ms)
received_at                          = 09:05:38.462Z
quote_ts                             = 09:06:00.000Z  quote_price=82 821.08
              quote_lag=21 538 ms   opinion_age=51 538 ms   source=binance_spot_1m_klines
FILL          entry_price=82 840.90 (+2,393 bps de spread/impacto declarados)
              quantity=0.0060356658961393675  notional=500,00 USDT
              entry_commission_usdt=0.5  commission_bps=10,0
              position_id=pos-paper-prospective-003g-00000001
              entry_bar_range=[09:06, 09:10) minutes=3
              high=82 815.53  low=82 758.00  last=82 763.95
```

La vela de entrada (09:05) había **abierto** antes de que llegara la respuesta (09:05:38), así
que su apertura no era conocible; el primer precio que esa respuesta podía tomar es la apertura
de 09:06:00, y el stop sólo ve los minutos estrictamente posteriores al relleno.

### 3.2 Contabilidad de la posición abierta (el defecto D5, ahora medido)

| Término | Valor |
| --- | --- |
| `costs_usdt` (realizado, semántica intacta) | 0,00000000 |
| `entry_commissions_accrued_open_usdt` | **0,50000000** |
| `costs_total_usdt` | **0,50000000** |
| `pnl_realised_usdt` | 0,00000000 |
| `pnl_unrealised_usdt` | **+0,49443125** |
| `pnl_total_usdt` | +0,49443125 |
| `marked_equity_usdt` | **10 000,49443125** |
| `final_equity_usdt` (caja) | 10 000,00000000 |
| Marca de la posición | 83 005,66 (BTC/USDT) · no realizado bruto +0,99443125 |
| Identidades de reconciliación | **11/11 `true`** |

La misma sesión, leída con la semántica de 003G, habría publicado `costs_usdt = 0` y equity
10 000,00 sin mencionar la comisión pagada: 0,5 USDT de coste real invisibles. Ahora el total lo
nombra y el verificador lo **recalcula desde la fila `FILL`** (comisión × bps), no lo cree.

## 4. CURRENT vs PROPOSED

Mismos datos, mismo guion, misma latencia declarada, mismo capital, costes y política; el
comparador reconstruye la serie desde los minutos crudos y aborta si el hash no coincide.

| Ámbito | | CURRENT | PROPOSED |
| --- | --- | --- | --- |
| **Prospectiva** (18 decisiones) | rellenos | 0 | **1** |
| | `costs_total_usdt` | 0,00000000 | **0,50000000** |
| | `pnl_total_usdt` | 0,00000000 | **+0,49443125** |
| | DD (MTM) | 0,000000 % | 0,009644 % |
| | `quote_lag` mediano | — | 21 538 ms |
| **Ventana completa** (76 decisiones) | rellenos | 0 | **1** |
| | `costs_total_usdt` | 0,00000000 | 0,50000000 |
| | `pnl_total_usdt` | 0,00000000 | +0,34367213 |
| | DD (MTM) | 0,000000 % | 0,030206 % |

Puerta económica: **`INSUFFICIENT_SAMPLE`** (0 cierres; 003F exige ≥ 30). Esta tabla **no**
declara rentabilidad: declara que PROPOSED ejecuta donde CURRENT no encuentra precio, y que su
coste —incluida la comisión devengada— queda a la vista.

## 5. Verificación

`scripts/ai_bots_003h_verify.py` (no importa `trading_bot`; importa el verificador de 003G y
añade 8 checks): **33 PASS / 0 FAIL**, exit 0. Salida completa en
[VERIFICATION.md](smoke/VERIFICATION_003H.md) y [VERIFICATION.json](VERIFICATION.json).

Checks nuevos y qué atacan:

| # | check | resultado |
| --- | --- | --- |
| 26 | `accounting_contract_is_versioned_and_defined` | PASS (`paper-accounting/2`, 8 términos, cada uno con su significado) |
| 27 | `costs_usdt_still_means_realised_cost` | PASS (0 = suma de las patas de las filas `CLOSE`) |
| 28 | `open_position_commissions_are_accrued_once` | PASS (0,5 recalculado desde la fila `FILL`) |
| 29 | `marked_equity_rebuilds_from_raw_minutes` | PASS (marca 83 005,66 del JSONL 1 m → 10 000,49443125) |
| 30 | `no_position_is_counted_twice` | PASS (1 `position_id` distinto, 0 en ambas listas) |
| 31 | `fill_instants_are_ordered_and_named` | PASS (`received ≤ quote_ts`, `quote_lag`, `opinion_age`) |
| 32 | `live_minutes_were_seen_after_they_settled` | PASS (62 minutos en vivo, mínimo 2 544 ms ≥ 2 500) |
| 33 | `session_summary_matches_the_lane_ledger` | PASS (proyección = ledger `RUN_END`) |

**El verificador no es vacuo:** sobre la sesión de 003G (producida por el código anterior)
falla exactamente los cuatro checks que dependen del contrato nuevo (26, 28, 29, 33), porque esa
sesión no publica ningún término contable. Ese es el comportamiento correcto: un lector no puede
dar por buena una sesión que omite el coste de su posición abierta.

## 6. Defectos encontrados y su tratamiento

| ID | Defecto | Tratamiento |
| --- | --- | --- |
| 003H-D1 (D5 de 003G) | `costs_usdt` ignoraba la posición abierta; la fila `FILL` no llevaba comisión | **Corregido** + contrato versionado + 5 tests + checks 26-30 |
| 003H-D2 | El test del dashboard hasheaba `reports/` entero y fallaba con un escritor ajeno | **Reproducido** (1 fichero de 7 845) y **corregido** aislando el sujeto; 14/14 con escritor activo |
| 003H-D3 | `--full-store` sobrescribía `session/compare/` (pérdida de evidencia) | **Corregido**: cada ámbito escribe en su directorio |
| 003H-D4 | El resumen de sesión no publicaba términos contables | **Corregido**: proyección con `accounting` + `open_positions_at_end`, comprobada por el check 33 |
| 003H-D5 | El verificador de 003G falla 1/25 sobre su propia sesión | **Declarado**, no corregido: es el drift de runtime que 003H provocó; hashes y causa en `STATE_AUDIT.md` §6.1 |
| 003H-D6 | Una re-ejecución del verificador de 003G sobrescribió su `VERIFICATION.json|md` (25 PASS → 24 PASS/1 FAIL) | **Declarado** + `--out-dir` añadido a ambos verificadores; texto original transcrito en `PRESERVED_003G_VERIFICATION.md` (no es un artefacto restaurado) |

## 7. Bloqueos declarados

1. `INDEPENDENT_VERIFICATION_PENDING`: el verificador lo escribió el mismo agente que el código.
2. `INSUFFICIENT_SAMPLE`: 1 relleno, 0 cierres; sin veredicto económico.
3. `REAL_MODEL_CALLED=false`: proveedor `paper-script`, sin clave ni autorización de gasto.
4. LIVE: no existe ruta de orden en este camino; no se ha intentado.

## 8. Reproducción

```bash
cd "$(git rev-parse --show-toplevel)"
./.venv/Scripts/python.exe -m pytest tests/unit/market_data \
    tests/unit/vision/test_accounting_integrity.py \
    tests/unit/observability/test_dashboard_server.py -q            # 159 passed
./.venv/Scripts/python.exe scripts/ai_bots_003g_paper.py \
    --out reports/ai-bots/RFC-AI-BOTS-003H/smoke --duration-s 3600 --max-cycles 10
./.venv/Scripts/python.exe scripts/ai_bots_003h_verify.py \
    --session reports/ai-bots/RFC-AI-BOTS-003H/smoke --root .       # 33 PASS / 0 FAIL
./.venv/Scripts/python.exe scripts/ai_bots_003g_compare.py \
    --session reports/ai-bots/RFC-AI-BOTS-003H/smoke                # 18 decisiones: 0 vs 1
```

Una sesión nueva escribe en su propio directorio; la evidencia publicada es la del
2026-10-19T09:03:19Z y sus hashes están en `smoke/SESSION_START.json` y `logs/rfc003h/`.
