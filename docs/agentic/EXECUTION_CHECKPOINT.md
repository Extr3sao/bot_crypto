# Execution checkpoint — reanudación entre sesiones

> Documento vivo. **Antes de empezar cualquier sesión**: leer este fichero y validarlo contra Git
> (`git log -1`, `git status --porcelain`, rama actual). Si hay discrepancia, manda Git y este
> fichero se corrige con el estado real. **Después de cada paquete de trabajo relevante**:
> actualizar las secciones marcadas.
>
> Política completa en `AGENTS.md` §7. Reglas de campaña: `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`,
> nada de trading real, credenciales, apalancamiento ni cambios de límites de riesgo.

*Última actualización: 2026-10-17T12:15Z, sesión de WP-EDGE-017 (integridad de la captura
prospectiva y paridad de riesgo neto).*

## 0. WP-EDGE-017 (sesión actual, RFC-EDGE-017)

**Objetivo (issue #10):** cerrar cuatro defectos operativos que la certificación de EDGE-016 no
cubría —el colector destructivo, el contador de cobertura que sólo podía valer 0/1, el riesgo
decidiendo sobre bruto con el coste contabilizado después, y cuatro bloqueos defensivos
declarados pero no leídos— sin tocar límites, reservas ni la política de fin de semana.

**Resultado: `CAPTURE_APPEND_ONLY_VERIFIED` + `COVERAGE_IDENTITY_HOLDS` +
`NET_RISK_PARITY_VERIFIED` + `DEFENSIVE_BLOCKS_ENFORCED` + `ECONOMIC_RESULTS_NET_NEGATIVE` +
`PROSPECTIVE_CAPTURE_MANUAL_NOT_SCHEDULED` + `INDEPENDENT_VERIFIED`.**

| hecho | evidencia ejecutada |
| --- | --- |
| **El colector ya no destruye la muestra.** Fusión por `(símbolo, hora)`, primera escritura inmutable, `os.replace` atómico, reanudación desde la última barra, paginación con confirmación de página corta y sólo barras cerradas | 3 → 9 filas (+6) en la primera captura corregida; dos re-ejecuciones después: **0 añadidas, 0 perdidas, bytes idénticos** (`983944ba…d34a6b66`); registro independiente `OOS_CAPTURE_LEDGER.jsonl` con 3 entradas |
| **La cobertura cuenta barras, no símbolos** | `CAPTURE_INTEGRITY.json`: 9 esperadas, 9 observadas, 9 evaluadas, **0 faltantes**; identidad `esperadas = observadas + faltantes` por símbolo; racha consecutiva 3 h (08:00–10:00Z) |
| **La tasa de disco es una medición, no un fallback** | 418,3 B/h de datos + 9 158,0 B/h de sobrecarga = **9 576,3 B/h**; el fallback de 240 MB/h sobrestimaba **25 061,8×**; el guardián, con su reserva (2 GB), su 1,5× y su válvula (64 MiB) **sin tocar**, devuelve `COHERENT`. `CAPTURE_BLOCKED_DISK` era un diagnóstico equivocado |
| **El coste se paga dentro del libro antes de decidir** | `PaperBroker` cobra comisión, medio spread y slippage por símbolo; `pnl = bruto_ref − coste_ejecución − comisiones` en cada operación; `RiskManager.mark_equity` marca el equity neto antes de cada `check_signal` |
| **Replay de las 146 operaciones bajo riesgo neto** | 1×: 146 operaciones, −238,7705 USDT (comisiones 146,00 + ejecución 40,334); 2×: **110**, −293,0325 (55 rechazos por límite semanal); 3×: **67**, −294,0563 (105 rechazos). Con coste 0 el motor reproduce **146/146 operaciones idénticas** a EDGE-016 |
| **Los cuatro bloqueos defensivos se evalúan** | `risk/defensive_blocks.py` cableado en `start_paper_trading → PaperCycleEngine.run_cycle_sync`, con la política del loader real; falla cerrado si falta spread, ATR o latencia; fin de semana por calendario. En el replay: ATR evaluado en 201 propuestas (máx. 2,973 % vs 8 %), 52 entradas rechazadas por fin de semana |
| **Política intacta** | `config/risk.yaml` sin cambios (fin de semana sigue `false`), `config/runtime.yaml` sigue con live desactivado, ninguna reserva ni límite movido |
| **Verificación independiente con inyección de fallos** | `scripts/edge17_verify.py` (no importa ningún módulo constructor): **27/27** checks `VERIFIED`, **11/11** mutaciones detectadas (barra caída, duplicada, digest reescrito, hora ausente llamada tranquila, PnL inflado, coste cero, escalera de fills invertida, tasa imposible que «cabe», bloqueos desconectados, live activado, equivalencia rota) |
| **Pruebas** | nuevas: `test_edge17_capture.py` (15), `test_edge17_net_risk.py` (10), `test_edge17_defensive_blocks.py` (12). Dirigidas: `tests/unit/{paper,risk,config}` + PIT/causalidad EDGE-016 → **257 passed**; `tests/unit/paper` → 73. Suite completa `pytest tests/unit -q`: **4048 passed, 5 failed en 21:56** (`RFC-EDGE-017/FULL_UNIT_SUITE.log`) |

**Los 5 fallos de la suite, nombrados (ninguno del paquete):** 3 son de la línea WP-8
(`test_active_recovery_wp.py::test_audit_is_deterministic_and_committed`,
`test_recovery_determinism.py::test_repeated_reproduction_is_byte_identical` y
`::test_the_clean_checkout_rehearsal_passes_on_this_commit`): su auditoría comprometida está
desfasada respecto a `evidence/real_decisions/*.jsonl`, que **ya estaban modificados por otra
línea al abrir la sesión** y este paquete no tocó; los otros 2 son los mismos de ST6 que EDGE-016
ya registró (su dato acumulado contradice su aserción de «una sola ventana»).

**Git:** la reparación se publicó en `5b86b65` (*Charge the venue cost inside the paper book, and
stop the holdout from destroying itself.*). Los artefactos y este checkpoint van en los commits de
evidencia posteriores. Sólo se prepararon ficheros del paquete; los ~160 sucios de otras líneas
siguen intactos.

## 1. Objetivo anterior (cerrado)

**WP-EDGE-016**: integridad point-in-time, paridad de riesgo y captura prospectiva honesta →
`PIT_FIXED_RISK_PARITY_VALIDATED` + `ECONOMIC_RESULTS_RESTATED_NO_EDGE`. Sus artefactos quedan
congelados en `reports/economic-recovery/RFC-EDGE-016/` y describen el código de `2536928`.
`edge16_verify.py` devuelve hoy **42/44**: V57 y V58 fallan porque este paquete cambió
`src/trading_bot/paper/broker.py` (nueva clase de coste, líneas desplazadas) y
`scripts/edge16_paper_lane.py`; los hashes de sus 32 artefactos siguen coincidiendo. No se
regeneraron sus evidencias: describen el commit anterior y así se declaran. Sus 38/38 mutaciones
siguen detectándose.

## 2. Estado Git

- Rama: `agent/edge-recovery/WP-EDGE-00-baseline`.
- Commit de código de esta ronda: `5b86b65`.
- **No preparar ni tocar** lo ajeno: `data/st6/**`, `.ci/**`, `data/recovery/wp8/**`,
  `evidence/real_decisions/**`, `reports/economic-recovery/RFC-EDGE-014*/**`, los tests nuevos de
  `swing`/`rfc035*` de otro agente, y en general los ~160 ficheros sucios de otras líneas.

## 3. Hecho (con evidencia ejecutada)

### P0-A — captura

| defecto | estado | evidencia |
| --- | --- | --- |
| `_write_slice` abría con `w`: cada captura truncaba el holdout | **cerrado**: fusión append-only, primera escritura inmutable, conflicto registrado | `oos_capture.merge_slice`; `test_repeated_capture_keeps_every_row_and_is_byte_identical` |
| `since` fijo + `limit=1000`: la historia creciente se estancaba | **cerrado**: reanudación desde la última barra y paginación con confirmación de página corta | `test_pagination_recovers_history_beyond_one_page`, `test_truncated_page_is_confirmed_with_one_more_request`; `pagination` en el manifiesto |
| `captured_bars_per_symbol` constante 0/1 y dedupe tautológico | **cerrado**: escalera por `(símbolo, hora)` | `coverage_ladder`; 9/9/0 en `CAPTURE_INTEGRITY.json` |
| barra de la hora en curso admitida | **cerrado**: `is_closed` | `test_partial_current_hour_bar_is_excluded`; manifiesto `partial_bars_excluded=0` |
| escritura no atómica | **cerrado**: temporal + `os.replace` + `fsync` | `test_a_failed_replace_leaves_the_previous_slice_intact` |

### P0-B — almacenamiento

`STORAGE_MEASUREMENT.json`: 139,4 B/barra, 418,3 B/h de datos, 9 158,0 B/h de sobrecarga,
9 576,3 B/h efectivos, factor de sobrestimación 25 061,8×, pico transitorio 2 510 B. Guardián sin
cambios (1,5×, 2 GB, 64 MiB, 24 h) → `COHERENT`. `widths` de la ventana: 278 595 h por disco y
7 008 h por válvula.

### P0-C — riesgo neto

Ver §0. Extra: `baseline_comparison` explica la diferencia de 0,98 USDT frente al neto reexpresado
de EDGE-016 (la cantidad comprada es menor porque el spread ya se pagó).

### P0-D — bloqueos defensivos

Ver §0 y `RISK_BLOCKS_MATRIX.json`. `WEEKEND_POLICY.json` de EDGE-016 sigue siendo la referencia
del conflicto 7/7: **no se cambió la política**; cambiarla requiere ADR.

## 4. Pendiente

1. **Ninguna barra observada en vivo**: las 9 son rellenas por la primera ejecución corregida
   (desfase máximo 2,648 h). La siguiente captura manual, ejecutada dentro de la hora, produce las
   primeras barras «capturadas al cierre».
2. **Ninguna estrategia admitida** (`config/strategy_admission.json`): el camino de paper del
   runtime no tiene nada que ejecutar; el carril experimental salta la admisión por diseño.
3. **Sin planificador**: crear la tarea exige privilegios de administrador, no autorizados.
4. **Ensayo de checkout limpio**: pendiente de ejecutar sobre el commit de evidencias; el volumen
   tiene ~4,4 GB libres y el checkout rastreado pesa 0,14 GB, así que cabe.

## 5. Bloqueos / items abiertos (no ocultar)

- **Volumen al 99 %** (4,4 GB libres). El colector ya no es el problema (9,6 KB/h), pero el host
  no está sano y este paquete no reclamó espacio.
- **Contención con la tarea programada ST6** (entorno, no defecto): alarga la suite.
- **`edge16_verify.py` en 42/44** por los dos checks que resuelven líneas/hashes del código
  vigente; declarado, no regenerado.
- **Auditoría WP-8 desfasada** por los `evidence/real_decisions/*.jsonl` sucios de otra línea; no
  se regeneró para no hornear estado no comprometido ajeno.

## 6. Comandos de reanudación

```bash
# 0. Estado real
git -C "$(git rev-parse --show-toplevel)" log --oneline -3
git -C "$(git rev-parse --show-toplevel)" status --porcelain | head -40

# 1. Capturar (append-only, idempotente; después commitear antes de verificar)
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_oos_preregistration.py --capture

# 2. Reproducir el paquete (rápido)
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge16_paper_lane.py --extend-prospective --out reports/economic-recovery/RFC-EDGE-017/experimental_paper
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge17_capture.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge17_reports.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge17_verify.py       # 27/27
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_verify.py        # 35/35

# 3. Gates
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m ruff check src/trading_bot/research/oos_capture.py src/trading_bot/risk/defensive_blocks.py src/trading_bot/paper/broker.py src/trading_bot/risk/manager.py src/trading_bot/paper/paper_cycle.py src/trading_bot/paper/harness.py scripts/edge17_*.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m mypy src/trading_bot/research/oos_capture.py src/trading_bot/risk/defensive_blocks.py src/trading_bot/paper/harness.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m pytest tests/unit/paper tests/unit/risk tests/unit/research/test_edge17_capture.py -q

# 4. Suite completa (~22 min con la tarea ST6 activa)
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m pytest tests/unit -q --tb=short -rf -p no:cacheprovider > reports/economic-recovery/RFC-EDGE-017/FULL_UNIT_SUITE.log 2>&1; echo "EXIT=$?"
```

## 7. Protocolo de actualización

- Al **cerrar un hito**: marcar la fila correspondiente en §3 y actualizar §4/§5.
- Al **cortarse la sesión**: anotar el comando exacto que se estaba ejecutando y su log.
- **Nunca** mover un elemento de §4 a §3 sin evidencia ejecutada (log, artefacto, exit code).
