# RUN_REPORT — RFC-TAP-AI-BOTS-003G

**Fecha:** 2026-10-19 · **Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003`
**Base Git:** `fe9b5e2` · **Commit publicado:** **ninguno** — el operador no autorizó commit; todo
el trabajo de 003G está sin commitear en el árbol de trabajo sobre `fe9b5e2`.
**Modo:** PAPER · **LIVE:** no habilitado · **`config/risk.yaml`:** sin cambios
(`sha256 3c27c866…593a2e`) · **`REAL_MODEL_CALLED=false`** · **`FALSE_SUCCESS=0`**

---

## 1. Entorno medido

```text
$ ./.venv/Scripts/python.exe --version
Python 3.11.15
matplotlib 3.9.2 · numpy 2.0.2 · pandas 3.0.3 · PyYAML 6.0.3
$ GET https://api.binance.com/api/v3/time   -> skew local-exchange = -206 ms
$ df -h .  -> 18,5 GB libres al cierre (inventario y limpieza en STATE_AUDIT.md §3)
```

## 2. Comandos ejecutados (exit code real)

```text
pytest tests/unit/market_data -q
  134 passed                                                          exit 0
pytest tests/unit/vision/test_prospective_session.py -q
  6 passed                                                            exit 0
pytest tests/unit/vision/test_lane_vertical.py test_causal_execution.py \
       test_open_phase_causality.py test_guards_and_controls.py -q
  56 passed                                                           exit 0
pytest tests/unit/vision tests/unit/market_data tests/unit/paper \
       tests/unit/risk tests/unit/intelligence tests/unit/reports \
       tests/unit/observability -q
  657 passed, 1 failed                                                exit 1
pytest tests/unit/observability/test_dashboard_server.py -q
  14 passed                                                           exit 0
ruff check <9 ficheros nuevos o tocados>                              exit 0
mypy src/trading_bot/{market_data/minute_collector,vision/prospective,vision/lane}.py
  Success: no issues found                                            exit 0
scripts/ai_bots_003g_paper.py --duration-s 2400 --max-cycles 8        exit 0
scripts/ai_bots_003g_verify.py --session .../session                  exit 0
scripts/ai_bots_003g_compare.py --session .../session                 exit 0
scripts/ai_bots_003g_compare.py --session .../session --full-store    exit 0
```

**El único fallo de la suite** es `test_runtime_artifacts_are_untouched_by_serving`: hashea
`reports/` mientras la sesión PAPER estaba escribiendo sus minutos. Al repetirlo con el árbol
quieto pasa **14/14**. No se ha tocado el test ni se ha declarado PASS global: se declara el
fallo y su causa medida.

## 3. Sesión PAPER prospectiva

**Directorio:** `reports/ai-bots/RFC-AI-BOTS-003G/session/`
**Inicio:** 2026-10-19T07:28:46Z · **Fin:** 2026-10-19T08:00:12Z
**Datos:** 276 minutos reales por símbolo (03:24→07:59 UTC), 0 gaps, 0 duplicados
**almacenados** (el feed repitió minutos; los idénticos se ignoraron y no se guardaron dos veces).
**Fuente:** `binance_spot_rest_1m` (pública, sin clave). **Proveedor de señal:** `paper-script`
(guion determinista; **no es un modelo**).

| Ciclo | Vela 5 m | `data_time` | `decision_time` | Barras | Filas ledger | Rellenos (acum.) |
| ---: | --- | --- | --- | ---: | ---: | ---: |
| 1 | 07:20 | 07:25 | 07:29:04.684 | 48 | 2 | 0 |
| 2 | 07:25 | 07:30 | 07:30:12.059 | 49 | 5 | 0 |
| 3 | 07:30 | 07:35 | 07:35:10.078 | 50 | 8 | 1 |
| 4 | 07:35 | 07:40 | 07:40:08.108 | 51 | 10 | 1 |
| 5 | 07:40 | 07:45 | 07:45:07.172 | 52 | 12 | 1 |
| 6 | 07:45 | 07:50 | 07:50:07.459 | 53 | 14 | 1 |
| 7 | 07:50 | 07:55 | 07:55:07.876 | 54 | 16 | 1 |
| 8 | 07:55 | 08:00 | 08:00:12.290 | 55 | 18 | 1 |

Cada `cycle-000N/ledger.jsonl` es el **ledger acumulado** hasta ese ciclo (2, 5, 8, 10, … 18
filas), no un delta; las 14 filas `DECISION` son 14 decisiones distintas, sin duplicados.
`data_time <= decision_time` en **8/8** ciclos. Retardo de entrega medido: **2 956 ms**
(p95 de minutos que cerraron después del inicio). Latencia declarada del proveedor: 30 000 ms.
**0 ciclos bloqueados.** Prefijo determinista del ciclo 8: 14 filas comparadas, `ok=true`.

### Traza del único relleno

```text
DECISION_OUTCOME  BTC/USDT OPEN_LONG  approved=true  risk_gate=check_signal  decision_seq=2
FILL              BTC/USDT buy        quote=82 884.01 (apertura 07:31:00Z)
                  entry_price=82 903.85 (+2,39 bps de slippage/impacto declarados en terms)
                  received_at=07:30:32.956Z  quote_lag=27 044 ms  opinion_age=57 044 ms
                  source=binance_spot_1m_klines  fill_bar_index=49  decision_bar_index=48
                  entry_bar_range=[07:31, 07:35) minutes=3
                  high=83 158.00  low=82 903.00  last=83 122.66
```

La respuesta llegó a las 07:30:32.956; la vela de entrada **abrió** a las 07:30:00, 32,9 s
antes, así que su apertura no era conocible y no se usó. El primer precio observable posterior
es la apertura de 07:31:00 (`quote_lag` 27 044 ms), y el rango con el que se evalúa el stop
usa los minutos **estrictamente posteriores** al relleno (07:32, 07:33, 07:34; la fila declara
`from=07:31 until=07:35 minutes=3`), nunca el 07:30 ni el 07:31. **CURRENT** (sin
sub-bar) no rellenó ninguna de las 14 decisiones: todas esperaron una cotización que llegó
después de la ventana de la opinión.

### Resultado económico

| | Valor |
| --- | --- |
| Rellenos | 1 |
| Operaciones cerradas | **0** |
| Posiciones abiertas al cierre | 1 (BTC/USDT largo desde 07:31) |
| Neto realizado | 0,000000 USDT |
| Equity marcado al cierre | 9 998,371187 USDT (−1,628813; incluye comisión 0,5) |
| Drawdown (MTM) | 0,024483 % |
| Coste de IA | 0,00 USD (`paper-script`, 0 llamadas reales) |

Con 0 cierres **no se juzga economía**: la puerta de 003F exige ≥ 30. El veredicto es
`INSUFFICIENT_SAMPLE`, no PASS.

## 4. CURRENT vs PROPOSED

Misma serie, mismo guion, misma latencia declarada (30 s), mismo capital, costes y política.
El comparador reconstruye la serie desde los minutos crudos y **aborta** si el hash no coincide
con el publicado.

| Ámbito | CURRENT | PROPOSED | Δ |
| --- | --- | --- | --- |
| Ventana prospectiva (14 decisiones) | 0 rellenos | 1 relleno | +1 |
| Ventana completa recogida (72 decisiones, retrospectiva) | 0 rellenos | 1 relleno | +1 |
| Neto / cierres | 0 / 0 | 0 / 0 | 0 |
| Sub-bar fills | 0 | 1 | +1 |

Artefactos: [COMPARISON.json](session/compare/COMPARISON.json) y
[COMPARISON.json](session/compare-full/COMPARISON.json).
La lectura es de **capacidad de ejecución**, no de predicción: sin sub-bar, el carril no
encuentra precio dentro de la ventana de la opinión y no opera.

## 5. Verificación

`scripts/ai_bots_003g_verify.py` (no importa `trading_bot`): **25 PASS / 0 FAIL**, exit 0.
Reconstruye serie, precios, rangos, identidades de coste, cadenas y hashes del runtime.
Ver [INDEPENDENT_VERIFICATION.md](INDEPENDENT_VERIFICATION.md) y
[session/VERIFICATION.md](session/VERIFICATION.md).

**Mutaciones ejecutadas (4/4 detectadas):**

| Mutación | Check que la rechaza |
| --- | --- |
| precio de relleno +1 USDT (cadena re-sellada) | `subbar_fills_are_observed_prices` + cadena del ciclo |
| minuto crudo del centro de la serie alterado | `published_series_rebuilds_from_minutes` + manifiesto |
| `decision_time < data_time` (stream re-sellado) | `data_time_le_decision_time` |
| `received_at` posterior al relleno | `subbar_fills_are_observed_prices` + cadena |

## 6. Defectos encontrados durante la ejecución (y qué se hizo)

### 003G-D1 — grupo 5 m cortado por el inicio de la ventana

La primera sesión se bloqueó en el ciclo 1 con `INCOMPLETE_DECISION_BAR`: `aggregate_complete`
trataba como hueco el grupo más antiguo, cortado por el `limit` del warm-up. **Corregido**:
se descarta como `leading_partial_group` (igual que el grupo pendiente del final) y un hueco
**interior** sigue siendo error. Test añadido. Evidencia del fallo:
`session-aborted-aggregation/STREAM.jsonl`.

### 003G-D2 — el venue revisa una vela ya cerrada

`ETHUSDT` minuto 07:18 se guardó a las 07:18:01.192 (1 192 ms tras el cierre) con
`low=2434.27 close=2434.28 vol=60.3066`. A las **07:19:18.032** (78 s tras el cierre) el venue
devolvió la misma vela con `low=2434.02 close=2434.02 vol=60.9785`. El colector registró
`DUPLICATE_CONFLICT`, **bloqueó ETHUSDT** y la sesión dejó de operar (evidencia:
`session-venue-revision/`, 31 eventos de conflicto). No se reescribió el dato.
**Corregido por política:** `settle_ms` (2 500 ms) ahora se exige antes de guardar un minuto
recién cerrado, y `lookback` baja a 3 minutos. Una revisión posterior de un minuto ya guardado
sigue bloqueando: es la respuesta fail-closed que pide el RFC. Test añadido.

### 003G-D3 — el verificador también tenía el defecto de los grupos parciales

Su primera pasada dio 24 PASS / 1 FAIL (`published_series_rebuilds_from_minutes`) por contar
los grupos de borde como huecos. Se corrigió para reflejar la política declarada; la mutación
de un minuto **interior** sigue siendo detectada (comprobado). Se declara el episodio: un
verificador que se ajusta hasta pasar no es evidencia por sí mismo.

### 003G-D4 — test del dashboard no tolera un escritor concurrente

`test_runtime_artifacts_are_untouched_by_serving` falló durante la suite porque la sesión PAPER
estaba escribiendo en `reports/`. Aislado: 14/14. No se modifica el test en este WP.

### 003G-D5 — `costs_usdt` sólo suma operaciones cerradas (pre-existente, no corregido)

La sesión terminó con **una posición abierta** que ya pagó 0,5 USDT de comisión de entrada.
`lane.py:1365` y `lane.py:1485` agregan costes recorriendo `trades` (operaciones cerradas), así
que `SUMMARY.json` publica `costs_usdt = 0`, `entry_commission_usdt = 0` y
`final_equity_usdt = 10 000,0` mientras el equity marcado es **9 998,371187** (que sí descuenta
comisión y pérdida no realizada). Las identidades de reconciliación pasan porque comparan
neto realizado contra costes realizados: son coherentes entre sí y **no** cubren la posición
viva. No se corrige aquí (el código de la sesión está congelado y este WP es de ejecución
sub-bar); se declara para que ningún lector tome `costs_usdt` como coste total. Con 0 cierres
no se emite veredicto económico, así que la afirmación no se apoya en ese campo.

## 7. Bloqueos declarados

1. `REAL_MODEL_CALLED=false`: sin clave ni autorización de gasto. La señal es un guion.
2. `INDEPENDENT_VERIFICATION_PENDING`: no hay segundo agente verificador disponible.
3. Economía: 1 relleno, 0 cierres. No hay veredicto económico.
4. LIVE: no existe ruta de orden en este camino; no se ha intentado.

## 8. Reproducción

```bash
cd "$(git rev-parse --show-toplevel)"
./.venv/Scripts/python.exe -m pytest tests/unit/market_data tests/unit/vision/test_prospective_session.py -q
./.venv/Scripts/python.exe scripts/ai_bots_003g_paper.py --duration-s 2400 --max-cycles 8
./.venv/Scripts/python.exe scripts/ai_bots_003g_verify.py \
  --session reports/ai-bots/RFC-AI-BOTS-003G/session --root .
./.venv/Scripts/python.exe scripts/ai_bots_003g_compare.py \
  --session reports/ai-bots/RFC-AI-BOTS-003G/session
```

La sesión nueva escribe en un directorio con timestamp si no se pasa `--out`; la evidencia
publicada es la del 2026-10-19T07:28:46Z y sus hashes están en `RUN_REPORT.json`.
