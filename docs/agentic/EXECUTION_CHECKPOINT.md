## 2026-10-18 · RFC-TAP-AI-BOTS-003 bloque A — reloj de cierre y paridad de riesgo

**Objetivo:** que una decisión sobre el cierre de una vela no pueda existir antes de que esa vela
cierre, y que el motor de riesgo vea la misma equity neta que publica la curva.

**Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003`, creada desde `b7e100a` (EVIDENCE-004F ya incluido).
**Commit:** `2557a9f`.

**Hecho**

1. `src/trading_bot/vision/clock.py`: `timeframe_ms` (lanza `UnknownTimeframe` en vez de adivinar)
   e `information_ms = open + timeframe + data_delay`.
2. `guards.assert_causal(bars, instant, bar_interval_ms=…)` exige que **cada vela haya cerrado**;
   el intervalo es argumento obligatorio. La prueba AIV-03 antigua comparaba aperturas y pasaba
   siempre: ahora falla en el caso que decía cubrir.
3. `lane.py`: decisión sellada en el cierre, `decision_bar_ts_ms` nombra la vela,
   `received_at_ms = cierre + latencia`, y `_marks` deja de contener el cierre de la vela antes de
   ejecutar en su apertura.
4. `lane.run`: al cerrar cada vela, `risk.mark_equity(mtm)`; la curva publica el mismo número en
   `equity` y `risk_equity`. Antes el riesgo sólo veía PnL realizado.
5. `lane.data_delay_ms` (+ `VISION_DATA_DELAY_MS`) declarado y registrado en el ledger: cero
   significa «no medido», no «instantáneo».

**Consecuencia declarada:** con el reloj correcto, cualquier latencia real descarta el fill
(la vela de ejecución abre justo cuando la respuesta vence). `NO_TRADE` es resultado legítimo.

**Verificación**

```text
pytest tests/unit/vision/test_causal_clock.py -q                      exit 0   7 passed
pytest tests/unit/vision tests/unit/intelligence tests/unit/reports -q exit 0  200 passed
ruff check src/trading_bot/vision tests/unit/vision                   exit 0
mypy src/trading_bot/vision/{clock,guards,lane,settings}.py           exit 0
scripts/evidence004_verify.py (misma rama)                            exit 0   42 PASS / 0 FAIL
RED comprobado: 5 fallos con `decision_ts_ms = bar.ts_ms`;
                paridad falla con equity 10001.37988951 vs riesgo 10000.0
```

**Pendiente / bloqueado**

- `REAL_MODEL_CALLED = false`. Sin clave ni autorización de gasto no hay llamada real.
- `data_delay_ms` no es una medición de red; es un parámetro declarado.
- Falta el bloque B (costes), y el run prospectivo VIS/CTX/CURRENT/NO_TRADE con el mismo
  calendario, capital y fricción.

**Reanudación**

```bash
cd "$(git rev-parse --show-toplevel)"
git checkout agent/ai-bots/RFC-TAP-AI-BOTS-003
git log -1 --format='%H %s'                                   # esperado: 2557a9f
./.venv/Scripts/python.exe -m pytest tests/unit/vision/test_causal_clock.py -q   # 7 passed
./.venv/Scripts/python.exe scripts/evidence004_verify.py      # 42 PASS / 0 FAIL
```

## 2026-10-18 · WP-TAP-EVIDENCE-004F — cierre de identidad, y traspaso a AI-BOTS-003

**Objetivo:** cerrar los cinco defectos residuales de EVIDENCE-004 (E4-01..E4-05) sin abrir otro
RFC ni rehacer el paquete, y publicar la reparación con verificación desde checkouts
independientes. Después, AI-BOTS-003 en una rama aparte.

**Base:** `243ba12` (rama `agent/evidence/RFC-TAP-EVIDENCE-004`).
**Commit de este bloque:** `978c485`.

**Hecho**

1. **E4-01 — un origen, una identidad.** `SourceSpan` guarda `content_sha256` en el dominio
   `TEXT_CANONICAL_LF`; clasificador, generador y verificador aplican la misma regla (antes
   `_read_source` hasheaba bytes del checkout y el verificador normalizaba a LF).
2. **E4-01b — la comprobación de spans tenía cero sujetos.** El generador publicaba eventos sin
   `sources`, así que `stored_spans_point_at_the_bytes_they_hashed` pasaba sin evaluar nada.
   Ahora los spans se publican y, sin spans, el check falla.
3. **E4-02 — texto no es bytes.** `SUPERSESSION_MANIFEST.json` v2 declara dominio y autoridad por
   documento (`preservation.content_sha256`); v1 se conserva intacto en
   `evidence-004/superseded-manifests/SUPERSESSION_MANIFEST.v1.json`.
4. **E4-03 — cifras renderizadas.** Los claims NARRATIVE se generan desde contadores; el texto
   libre con un número se rechaza. La frase publicada es «9 registradas, 7 ejecutadas, 2 no
   ejecutadas», y `CLAIMS.json` v1 queda archivado.
5. **E4-04 — verificador portable.** Detalles repo-relativos; dos raíces (LF y CRLF) producen
   `VERIFICATION.json` idéntico **byte a byte**.
6. **E4-05 — publicación transaccional.** Proyección candidata completa → relectura y re-hash →
   conmutación de `CURRENT_MANIFEST.json` → poda solo de huérfanas. La proyección anterior sobrevive
   y queda registrada en `SUPERSEDED_PROJECTIONS.json`.
7. **`.gitignore`**: `reports/*` ignoraba el árbol entero, así que cada proyección nueva nacía
   invisible para git y un checkout limpio no podría verificarla. Se re-incluye el paquete paso a
   paso, como los paquetes de evidencia anteriores.

**Verificación real (no reutilizada de informes previos)**

```text
scripts/evidence004_verify.py                     exit 0   42 PASS / 0 FAIL
scripts/evidence004_verify.py --mutations         exit 0   18/18 rechazadas
scripts/ai_bots_rea_verify.py                     exit 0   73 PASS / 0 FAIL
pytest reports+vision+intelligence                exit 0   193 passed (17 nuevos)
ruff / mypy (scripts + tests/unit/reports)        exit 0
git archive HEAD -> raíz LF                       exit 0   42 PASS / 0 FAIL
git archive HEAD -> raíz convertida a CRLF        exit 0   42 PASS / 0 FAIL
VERIFICATION.json LF vs CRLF vs commit            idénticos (cmp, sin diferencias)
--mutations sobre la extracción del archivo       exit 0   18/18 rechazadas
```

**Pendiente / bloqueado**

- `REAL_MODEL_CALLED = false`: sin credencial ni autorización de gasto. Cinco de las siete
  evidencias siguen siendo declaradas, no verificadas byte a byte.
- **AI-BOTS-003 no empezado en este checkpoint**; el siguiente bloque lo actualiza con su rama,
  su commit y sus resultados.
- Suite completa del repositorio no ejecutada: hay ficheros ajenos modificados en el árbol (otros
  agentes). Declarar un PASS global con eso en vuelo sería el defecto que este WP elimina.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --format='%H %s'                                    # esperado: 978c485 o su sucesor
./.venv/Scripts/python.exe scripts/evidence004_verify.py       # esperado: 42 PASS / 0 FAIL, exit 0
./.venv/Scripts/python.exe -m pytest tests/unit/reports -q     # esperado: 41 passed, exit 0
git archive HEAD | tar -x -C "$TEMP/ev004-lf"                  # extracción limpia
./.venv/Scripts/python.exe scripts/evidence004_verify.py --root "$TEMP/ev004-lf"   # 42 PASS
```

# Execution checkpoint — reanudación entre sesiones

> Documento vivo. **Antes de empezar cualquier sesión**: leer este fichero y validarlo contra Git
> (`git log -1`, `git status --porcelain`, rama actual). Si hay discrepancia, manda Git y este
> fichero se corrige con el estado real. **Después de cada paquete de trabajo relevante**: actualizar
> las secciones marcadas.
>
> Política completa en `AGENTS.md` §7. Reglas de campaña: `FALSE_SUCCESS=0`, `BUILDER != VERIFIER`,
> nada de trading real, credenciales, apalancamiento ni cambios de límites de riesgo.

*Última actualización: 2026-10-17T17:30Z, sesión WP-EDGE-017F (cierre real de los defectos que
sobrevivieron a la publicación de 017, y suite definitiva sobre el commit publicado).*

**Estado publicado al cerrar esta sesión**: `HEAD` = `origin/agent/edge-recovery/WP-EDGE-00-baseline`
= el commit que contiene este párrafo (`git rev-parse HEAD`), 8 commits sobre `5c81aad`, fast-forward
verificado con `git merge-base --is-ancestor`. La suite se midió en su padre
`64da0cd8c0c2a2b72369638300e26647fb9c168c`; el delta es solo documentación, sin código ni tests, así
que `TEST_TARGET == RUNTIME_TARGET` se mantiene. Comprobarlo con `git rev-parse`, no leyéndolo aquí.

## RFC-AI-BOTS-002 — sesión 2026-10-17T22:30Z (rama `agent/ai-vision/RFC-AI-VISION-001`)

**Objetivo**: ejecutar el RFC de AI Bots sobre AI-VISION-001 sin tocar WEB-017F ni
`config/risk.yaml`. Confirmar Git antes de escribir: rama propia, `HEAD` = `091d55d` al
empezar, y varias modificaciones ajenas sin commitear en `reports/`, `data/` y
`config/vision.yaml` que **no** se han tocado ni staged.

| bloque | estado | evidencia |
| --- | --- | --- |
| P0 defectos visuales (volumen doble, margen, cuerpos) | **cerrado** | RED medido (80 rects vs 40; 34 px en borde; 5,93 px/vela) → GREEN en `tests/unit/vision/test_visual_defects.py` |
| Guards PIT/esquema y hueco de datos | **cerrado** | `guards.py` + `test_guards_and_controls.py`; el lane rechaza ejecutar en una barra no contigua |
| Registro de bots | **cerrado** | `ai_bots/registry.py`, capacidades cerradas, desactivados por defecto (`AI_BOTS_ENABLED` + `AI_BOTS_ALLOW`) |
| BOT-VIS-01 / BOT-CTX-01 | `MOCK_TEST` ejecutado | 40 llamadas cada uno, 14 cierres, mismo libro; VIS adjunta 40 PNG, CTX 0 |
| Verificación independiente | **PASS 34/0** | `scripts/ai_bots_verify.py` sobre artefactos en disco |
| Llamada multimodal real | **BLOCKED** | `--mode live` → exit 2 `MISSING_CREDENTIAL`; sin `VISION_API_KEY` no hay petición |
| Comparación económica | `NOT_EVIDENCE` | el modelo fue un guion; no se declara edge |

Suite medida en el árbol de trabajo antes de publicar: **366 passed**
(`tests/unit/{vision,intelligence,paper,risk}`), ruff y mypy limpios.
Artefactos: `reports/ai-bots/RFC-AI-BOTS-002/` (RUN_REPORT, FINAL_REPORT,
INDEPENDENT_VERIFICATION, REA_FINDINGS, manifests, ledgers) y
`docs/ai-bots/RFC-AI-BOTS-002/` (autoridad, fuentes, matriz de patrones).

**Publicado** (fast-forward sobre 091d55d): 520a6df (P0 visual y guards), 317d161
(registro y runner de bots), 76d3992 (evidencia y verificación). Comprobar con
git log --oneline -3, no leyéndolo aquí.

**Pendiente real**: credencial del proveedor para `REAL_MODEL_CALLED`; sin ella el veredicto
económico no puede existir. **No** se ha tocado riesgo, no hay ruta de orden real, y REA
quedó en `doctor/help` ejecutados con análisis de terceros `NOT_EXECUTED`.

## 0. WP-EDGE-017F — qué se cerró y con qué evidencia

**Punto de partida validado**: `HEAD` = `origin/agent/edge-recovery/WP-EDGE-00-baseline` =
`5c81aad94e1bf67b72c56d479a5ac06034397d73`. La rama ya estaba publicada; el bloqueo anterior
(6 commits locales sin subir) quedó resuelto en la sesión previa.

| bloque | estado | evidencia ejecutada |
| --- | --- | --- |
| **P0.1 ventana semanal** | **cerrado** | 11 de 14 tests fallaban antes; después **14 passed**. 12 `WEEK_BOUNDARY` por corrida, `weekly_pnl` a 0 en todos, 10 con pérdida previa ≠ 0 |
| **P0.2 replay regenerado** | **cerrado** | ejecuciones reales 1×/2×/3×: **146 / 146 / 121** fills; neto **−238.770489 / −425.692312 / −500.571772** USDT |
| **P0.3 drawdown** | **cerrado** | `EQUITY_CURVE.jsonl` (2 000 puntos MTM por corrida); **2.387705 / 4.256923 / 5.005718 %**; 12 tests; C-checks del verificador + M13/M14 |
| **P1 evidencia prospectiva** | **cerrado (manual)** | slice 9 → **24** filas, 0 conflictos, 0 ausentes; **6 al cierre**, **18 recuperadas**; 9 evaluadas, 0 propuestas, 0 fills |
| **P0.4 suite global** | **parcial / FAIL declarado** | ver §4: resultado literal en `RFC-EDGE-017/FULL_UNIT_SUITE.log`; V57/V58 clasificados |
| **Verificación independiente** | **cerrado** | `edge17_verify.py`: **31/31 checks, 14/14 fallos detectados**; `edge15_verify.py`: **35/35** tras commitear la captura |

**Cifras anteriores retiradas**: 146/110/67 fills y `drawdown_pct = 10 000.0`. Las dos eran
artefactos: la segunda era `peak_equity` (un saldo, no un porcentaje) y las primeras salieron de un
motor cuyo veto semanal no se levantaba nunca, de modo que 2× y 3× dejaban de operar tras una mala
semana.

### Lo que cambió en el código

- `src/trading_bot/risk/manager.py`: `week_start_ms_for()` (semana UTC lunes 00:00),
  `RiskManager.weekly_start_ms`, `roll_week()`, llamada en `check_signal`, `record_trade_result` y
  `reset_daily`; `extract_state`/`restore_state` transportan el ancla.
- `src/trading_bot/paper/reconciliation_v4.py`: el ancla viaja en el snapshot durable.
- `scripts/edge16_paper_lane.py`: curva de equity MTM por barra, `WEEK_BOUNDARY /
  RISK_RESET_WEEKLY` con `weekly_pnl_before_reset`, bloque `weekly_risk`.
- `src/trading_bot/research/equity_drawdown.py` (nuevo): drawdown pico-valle con estado `UNKNOWN`.
- `scripts/edge17_reports.py`: drawdown desde la curva y texto derivado de los datos.
- `scripts/edge17_capture.py`: `capture_class` por barra (al cierre / recuperada / ausente).
- `scripts/edge17_verify.py`: 3 checks de drawdown (uno por multiplicador) + M13/M14.
- Documentación: `docs/risk-policy.md` (ventana explícita) y `tasks/decisions.md` **ADR-017F-01**.

**Nada de esto cambió** `max_weekly_loss_pct` (3.0), ningún otro límite, la reserva de disco (2 GB),
el multiplicador 1.5×, la válvula de 64 MiB ni la política de fin de semana (`false`).

## 1. Estado Git

- Rama: `agent/edge-recovery/WP-EDGE-00-baseline`.
- Commits de esta ronda (se publican en el push final, fast-forward):
  - `9dbbbae` — ventana semanal UTC + persistencia + ADR-017F-01.
  - `05b977e` — drawdown desde curva de equity + verificación independiente.
  - `ff339bb` — proveniencia por barra y reportes derivados de datos.
  - `126cf95` — captura nueva (slice 9 → 24, ledger, manifiesto).
  - `7ef6458` — EDGE-015 re-verificado 35/35 tras commitear la captura.
  - `34622f3` — replay 1×/2×/3× regenerado + curvas + verificación 31/31.
  - `64da0cd` — cierre: suite real, propietario por test, `RUN_REPORT.md`, `FINAL_REPORT.md`.
  - *(cierre documental)* — suite definitiva sobre `64da0cd`, índice de evidencias reconstruido y
    este checkpoint apuntando al commit publicado.
- **Publicado**: `git push origin HEAD:agent/edge-recovery/WP-EDGE-00-baseline` →
  `5c81aad..64da0cd` (fast-forward, sin force). El remoto se comprueba con `git rev-parse`.
- La cabecera publicada se comprueba con `git rev-parse origin/agent/edge-recovery/WP-EDGE-00-baseline`,
  no leyéndola aquí.
- **No tocar** lo ajeno: `data/st6/**`, `.ci/**`, `data/recovery/wp8/**`,
  `evidence/real_decisions/**`, `reports/economic-recovery/RFC-EDGE-014*/**`,
  `reports/economic-recovery/RFC-EDGE-016/**`, `scripts/cap004c_verify.py`,
  `scripts/st6_scheduler_witness.py`, `src/trading_bot/research/economic_recovery/alpha15.py`,
  `docs/source_registry.md` y los ~165 ficheros sucios de otras líneas.

## 2. Resultados (reproducibles con §5)

| cantidad | valor |
| --- | --- |
| fills 1× / 2× / 3× | 146 / 146 / 121 |
| neto 1× / 2× / 3× | −238.770489 / −425.692312 / −500.571772 USDT |
| drawdown 1× / 2× / 3× | 2.387705 / 4.256923 / 5.005718 % |
| rechazos 1× / 2× | 3 × cooldown de pérdidas consecutivas |
| rechazos 3× | 43 × max drawdown, 1 × cooldown |
| reinicios semanales por corrida | 12 |
| veto semanal efectivo en el dataset | **0** (peor semana −120.13 USDT = 1.2 % < 3 %) |
| equivalencia frictionless vs EDGE-016 | 146/146 idénticos |
| captura: esperadas / observadas / ausentes | 24 / 24 / **0** |
| captura: al cierre / recuperadas | **6 / 18** |
| tasa del colector | 9 787 B/h (fallback 240 MB/h; sobrestimación 24 522×) |
| guardián de disco | `COHERENT`, reserva y válvula intactas |

**Evolución semanal del riesgo (1×, `weekly_pnl` antes de cada reset)**: −22.05, −14.50, −8.12,
−39.89, −4.35, −25.10, +3.76, −14.64, −33.42, −78.76 USDT (13 semanas; las dos primeras sin
pérdida cerrada). 2×/3× en `NET_RISK_REPLAY.runs.*.weekly_risk`.

## 3. Ficheros de evidencia

- `reports/economic-recovery/RFC-EDGE-017/FINAL_REPORT.md` — informe final 017F.
- `reports/economic-recovery/RFC-EDGE-017/RUN_REPORT.md` — comandos y PASS/FAIL/BLOCKED.
- `reports/economic-recovery/RFC-EDGE-017/NET_RISK_REPLAY.json` — fills, neto, drawdown, semanas.
- `reports/economic-recovery/RFC-EDGE-017/scratch/net_{1,2,3}x/EQUITY_CURVE.jsonl` — curva verificable.
- `reports/economic-recovery/RFC-EDGE-017/CAPTURE_INTEGRITY.json` — cobertura y proveniencia.
- `reports/economic-recovery/RFC-EDGE-017/INDEPENDENT_VERIFICATION.{json,md}` — 31/31, 14/14.
- `reports/economic-recovery/RFC-EDGE-017/FULL_UNIT_SUITE.log` — resultado literal de la suite.

## 4. Pendiente y bloqueado (no ocultar)

1. **Suite global ejecutada dos veces**: **4070 passed, 14 failed** en 21:53 sobre `34622f3` y
   **4070 passed, 14 failed en 19:44** (exit 1, 1184.06 s) sobre el commit publicado `64da0cd`,
   con los **mismos 14 tests** en ambas corridas. Los 14 son
   **BLOCKED** ajenos al paquete: **9 cost-barrier** (el gate fija el audit `023b66ff…` mientras
   el audit comprometido en `HEAD` ya es `c6ea3438…`: inconsistencia previa a 017F), **3 WP-8**
   (`evidence/real_decisions/*.jsonl` sucios de otra línea; vista comprometida obsoleta) y
   **2 ST6** (su dato acumulado contradice su aserción de cobertura). Detalle y evidencia por
   test en `RUN_REPORT.md` §6. Ninguno se convirtió en PASS.
2. **EDGE-016 V57** — **BLOCKED**: `RFC-EDGE-016/INDEPENDENT_VERIFICATION.json` ya estaba modificado
   por otra línea al abrir la sesión y su hash no coincide con el índice.
3. **EDGE-016 V58** — **BLOCKED (causado por el paquete, evidencia congelada)**: EDGE-017 movió
   `def check_positions_ohlc` de la línea 398 a la **490** y el sha de `broker.py` de `0250fc47…` a
   `4366809a…`; el mapa de EDGE-016 sigue citando el par antiguo. Reescribirlo haría que un artefacto
   que declara describir `2536928` describiera otro código: la regeneración corresponde a EDGE-016.
4. **Sin planificador**: crear la tarea exige privilegios de administrador, no autorizados.
5. **Sin estrategia admitida** (`config/strategy_admission.json` intacto): el carril de paper del
   runtime no tiene nada que ejecutar; el carril experimental salta la admisión por diseño.
6. **Spread y latencia** siguen `NOT_MEASURED` en un replay de barras; se aplican en el entrypoint.
7. **Volumen al ~99 %** (≈4.2 GB libres). El colector consume ~9.8 KB/h, así que el disco ya no es la
   causa, pero el host no está sano.
8. **Scheduler/ST6**: la tarea programada de otra línea sigue alargando la suite por contención.

## 5. Comandos de reanudación

```bash
# 0. Estado real
git -C "$(git rev-parse --show-toplevel)" log --oneline -3
git -C "$(git rev-parse --show-toplevel)" status --porcelain | head -40
git -C "$(git rev-parse --show-toplevel)" rev-parse origin/agent/edge-recovery/WP-EDGE-00-baseline

# 1. Tests del paquete
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m pytest tests/unit/risk/test_edge17_weekly_window.py tests/unit/research/test_edge17_drawdown.py tests/unit/research/test_edge17_capture.py -q

# 2. Capturar (append-only, escritor único) y verificar
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_oos_preregistration.py --capture
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge17_capture.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge17_reports.py
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge17_verify.py    # 31/31, 14/14
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python scripts/edge15_verify.py     # 35/35 (captura commiteada)

# 3. Replay (si hace falta regenerarlo)
cd "$(git rev-parse --show-toplevel)" && for m in 1 2 3; do ./.venv/Scripts/python scripts/edge16_paper_lane.py --cost-mode net --cost-multiplier $m --out reports/economic-recovery/RFC-EDGE-017/scratch/net_${m}x; done

# 4. Suite completa (~20 min con ST6 activa) — dejar el log dentro del paquete
cd "$(git rev-parse --show-toplevel)" && ./.venv/Scripts/python -m pytest tests/unit -q --tb=short -rf -p no:cacheprovider > reports/economic-recovery/RFC-EDGE-017/FULL_UNIT_SUITE.log 2>&1; echo "EXIT=$?"
```

## 6. Protocolo de actualización

- Al **cerrar un hito**: marcar la fila en §0/§2 y actualizar §4.
- Al **cortarse la sesión**: anotar el comando exacto en curso y su log.
- **Nunca** mover un elemento de §4 a §0/§2 sin evidencia ejecutada (log, artefacto, exit code).
- `reports/economic-recovery/*` está en `.gitignore`: la evidencia nueva se añade con `git add -f`,
  sólo la propia del bloque.

## RFC-TAP-AI-BOTS-002 v3 (REA-FIRST) — sesión 2026-10-18T00:20Z (rama `agent/ai-vision/RFC-AI-VISION-001`)

**Objetivo**: cerrar los P0 propios que podían producir una operación falsa y obtener
evidencia REA **real** de al menos un target externo. `HEAD` al empezar: `6f637a7`
(comprobarlo con `git log --oneline -1`, no leyéndolo aquí). No se tocó `config/risk.yaml`
ni EDGE-017F.

| bloque | estado | evidencia |
| --- | --- | --- |
| REA sobre target real | **ejecutado** | 4 operaciones, exit 0: `analyze-javascript-application` (bundle público de nof1.ai, `ev_aee35b0f…`), `list-browser-targets` (`ev_f7020db1…`), `capture-web-screenshot` (`ev_47c01acc…`), `analyze-web-bundle` (`ev_82d99570…`) |
| P0 hash de imagen | **cerrado** | `INTEGRITY_FAILURE` ⇒ `return None`: 0 decisiones, 0 fills. Test nuevo sobre `VisionLane` |
| P0 latencia | **cerrado** | `LATE_RESPONSE` al ejecutar: una respuesta posterior a la apertura de la barra no rellena. Test nuevo (control con latencia 0 sí opera) |
| P0 comparador | **cerrado** | `NOT_COMPARABLE` como veredicto si cambian cadencia/insumos; la aritmética se reporta aparte |
| Defensas + `roll_week` | **verificado existente** | `paper_cycle._defensive_verdict` falla cerrado; `RiskManager.check_signal` llama `roll_week()`; `tests/unit/risk/test_edge17_defensive_blocks.py` |
| Targets restantes | **BLOCKED medido** | disco 2,9 GB libres (99 % usado); Streamlit/Python sin superficie JS propia; FortuneMal sin licencia (API 404) |
| Llamada multimodal real | **BLOCKED** | sin credencial ni autorización de gasto: cero llamadas, `REAL_MODEL_CALLED=false` |
| Adopción externa | **not certified** | sólo nof1 tiene evidencia y no alcanza la cadena gráfico→modelo→decisión: `DEFER` |

**Medición de tests**: contra `HEAD` antes del arreglo **6 failed / 9 passed**; después
**15 passed**; suites focalizadas (`vision`, `intelligence`, `paper`, `risk`) **372 passed**;
`ruff` y `mypy` limpios. Verificador independiente propio:
`scripts/ai_bots_rea_verify.py` → **21 PASS / 0 FAIL** (rechazó dos incoherencias del informe
antes de publicarse: la cadena de licencia de FortuneMal y una afirmación de estado ausente).

**Comandos de reanudación**:

```
.venv/Scripts/python.exe scripts/ai_bots_rea_verify.py          # 21 PASS / 0 FAIL esperado
.venv/Scripts/python.exe -m pytest tests/unit/vision -q         # tests del lane y del comparador
npx -y rea-agents@6.4.0 analyze-javascript-application <ruta> --format json --fetch-source-maps
```

**Pendiente real y siguiente paso con valor**: ampliar el análisis de nof1 con
`--fetch-source-maps` (nombres legibles) o conseguir un artefacto local autorizado de un
target Python y observar su ciclo con REA CDP; ambos necesitan espacio en disco.

---

## Cierre de la pasada de completitud (2026-10-18)

Objetivo: contrastar el entregable real contra el pliego §5/§9 y cerrar lo que faltaba.
Verificador ampliado de **21 → 31 PASS / 0 FAIL** (`scripts/ai_bots_rea_verify.py`), y las
comprobaciones nuevas se probaron **no vacuas**: al retirar `SOURCE_RUNTIME_CORRELATION.md`
del dossier de nof1 el verificador sale con exit 1 y nombra el fichero ausente.

Añadido en este cierre: `INFORME_EJECUTIVO.md`, `SOURCE_RUNTIME_CORRELATION.md` y
`RECONSTRUCTION_OBLIGATIONS.json` en los seis dossiers, `PATTERN_ADOPTION_MATRIX.md`
reescrito con la regla `NO_REA_EVIDENCE = NO_EXTERNAL_PATTERN_CERTIFICATION`, y punteros en
`FINAL_REPORT.md`/`RUN_REPORT.md` hacia el conjunto REA-FIRST.

**Aviso operativo para la próxima sesión**: `.gitignore:60` es `reports/*`. Los artefactos
de `reports/` hay que añadirlos con `git add -f`; si no, existen en disco y **no se publican**.

Estado sin cambios: `REAL_MODEL_CALLED=false`, ningún patrón externo certificado, disco
2,9 GB libres.

## 2026-10-18 · RFC-TAP-AI-BOTS-002 v3.1 (REA Target Authority)

**Objetivo:** corregir la atribución no demostrada entre los bundles de `www.nof1.ai` y
`195440/nof1.ai`, y ejecutar REA de verdad sobre artefactos del commit exacto de tres
proyectos.

**Base:** `a0ca055` (rama `agent/ai-vision/RFC-AI-VISION-001`).

**Hecho**

1. **P0 de procedencia, refutado con artefacto.** El commit `5d27641dfa47cc942aa0709ffb3f5237de876373`
   (árbol `b3ae235a…`) se clonó en sandbox (2,3 MB) y **no contiene Next.js**: build `tsdown`,
   cero literales `__NEXT`/`turbopack`, y su dashboard son `public/app.js` +
   `public/monitor-script.js` en `open-nof1.195440.com`. El bundle público es Turbopack
   (`__NEXT` 9/12, `turbopack` 7/12). La asociación no era sólo indemostrada: es imposible.
2. **Evidencia de la v3 preservada** en `rea/targets/T-NF-PUBLIC/` (4 `evidence_id`, hashes
   intactos), reetiquetada `UNATTRIBUTED_NO_DEPLOYMENT_RECEIPT`.
3. **REA sobre el repo exacto**: `analyze_javascript_application` sobre `public/` →
   `ev_4b2bf9c5…`, 3 ficheros, 4.812 nodos AST, exit 0.
4. **REA sobre Semantic Signal** (`65e67dc2…`, MIT): estático `ev_9b45318c…`, bundle
   `ev_b954b8b0…`, captura `ev_ee6845ff…`.
5. **REA sobre FenixAI** (`bd7373d5…`, Apache-2.0): `npm ci` + `vite build` desde el commit
   (exit 0) → `ev_be8c7d74…`, bundle `ev_fc2b6552…`, captura `ev_b3b1e837…`.
6. **Auditoría de fuente** de los tres backends: nof1 no es visual y deja el apalancamiento al
   modelo con el drawdown comentado; FenixAI manda la imagen sin hash ni símbolo; QRAK liga la
   imagen por construcción y el risk manager recorta el tamaño.
7. **Verificador ampliado** (31 → 59 → 70 → **73** comprobaciones), con mutaciones que lo rechazan:
   reatribuir el bundle público ⇒ 2 FAIL; borrar `PROVENANCE.md` del repo exacto ⇒ 2 FAIL;
   disfrazar el probe de `REA_EVIDENCE` ⇒ 2 FAIL.
8. **Ejecución instrumentada del renderizador de FenixAI** (`4dba317`): `ChartService` del
   commit `bd7373d5…` con 120 velas sintéticas en venv desechable, sin red ni claves → PNG
   181.314 B `96c7f41c…`, determinista, caché por símbolo. Hallazgos: sin `mplfinance` devuelve
   `PLACEHOLDER` con `ok=True`, y `get_cached(max_age=0)` trata el 0 como "no especificado".
   Etiquetado `INSTRUMENTED_EXECUTION_NOT_REA`; nunca se cuenta como llamada de modelo.
9. **`exit 0` dejó de contar como éxito.** `compare-source-to-bundle` devolvió `exit_code: 0`
   con resultado `NOT_EXECUTED_INVALID_INPUT`, y `RUN_REPORT.md` lo sumaba como operación
   correcta ("9 operaciones REA con exit 0"). Corregido a 7 con `evidence_id` + 2 declaradas no
   ejecutadas, y el verificador ahora comprueba la tabla fila por fila
   (`run_table_annotates_exit_zero_without_evidence`, `run_table_counts_evidenced_work_only`)
   además del log consolidado (`rea/REA_COMMAND_LOG.jsonl`, 16 entradas = suma de los 4 dossiers).
   La misma sobreafirmación estaba en otros tres sitios y los tres quedaron ligados al mismo
   número: `RUN_REPORT.json` (`rea_operations_exit_0: 9` → `rea_operations_evidenced: 7` +
   `rea_operations_not_executed: 2`), `source_registry.md` ("Las 9 operaciones REA…") y
   `REA_FINDINGS_V2.json` ("all exit 0"). Mutar cualquiera de los tres ⇒ 3 FAIL.

**Pendiente / bloqueado**

- `REAL_MODEL_CALLED = false`: sin credencial ni autorización de gasto.
- `import-reference-source` → **exit 1 `unsupported_host`** en Windows: `compare-source-to-bundle`
  queda bloqueado por falta de productor de `HistoricalSourceGraph`. Registrado, no simulado.
- Backends Python/TypeScript de los tres targets sin ejecutar (requieren claves/servicios).
- `T-TA-CRITIC` y `T-FM-DEMO` sin REA: sin superficie JS / sin licencia.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --format='%H %s'
./.venv/Scripts/python.exe scripts/ai_bots_rea_verify.py | tail -2   # esperado: 73 PASS / 0 FAIL, exit 0
./.venv/Scripts/python.exe -m pytest tests/unit/vision tests/unit/intelligence -q | tail -2
./.venv/Scripts/ruff.exe check scripts/ai_bots_rea_verify.py
```

**Commits de este paquete:** `6403c71` (procedencia + REA de los tres commits), `4dba317`
(renderizador de FenixAI ejecutado) y el commit que contiene estas líneas (log consolidado y
`exit 0 != éxito` en el verificador). Comprobar con `git log --oneline -3`, no leyéndolo aquí.

**Aviso que sigue vigente:** `.gitignore:60` es `reports/*`; los artefactos nuevos de
`reports/` necesitan `git add -f` o no se publican.

**Añadido al cerrar: ejecución instrumentada (no REA) del render de FenixAI.**
`rea/targets/T-FE-FENIX/instrumentation/` guarda el probe, su salida y un README: el
`ChartService` del commit exacto corrió offline con velas sintéticas (exit 0, backend
`MPLFINANCE`, PNG 181.314 B, determinista, caché sin cruzar símbolos) y la misma corrida midió
dos defectos reales: relleno silencioso con `ok=True` cuando falta un backend, y
`get_cached(max_age=0)` que aplica el TTL por defecto porque el cero es falsy.

Verificador: **65 PASS / 0 FAIL** (antes 59). Mutación nueva comprobada: disfrazar el probe de
`REA_EVIDENCE` ⇒ 2 FAIL. La consistencia hash-probe↔dossier la vigila el propio verificador:
detectó que la baseline sólo citaba 8 caracteres del sha y se corrigió el documento, no la
comprobación.

## RFC-TAP-EVIDENCE-004 — sesión 2026-10-18 (rama `agent/evidence/RFC-TAP-EVIDENCE-004`)

> Sección añadida al final, sin reescribir las anteriores: otro agente puede tener este fichero
> abierto. Si algo aquí discrepa de Git, manda Git.

**Objetivo**: que ninguna cifra del RFC AI-BOTS-002 vuelva a contradecirse entre informes, y que
ningún `exit_code == 0` se lea como trabajo completado.

**Base**: `c4e6e3b5ec3f40090a0aa66fee2733c0b00c9546` (rama `agent/ai-vision/RFC-AI-VISION-001`).

**Hecho**

1. **Clasificador** `scripts/evidence004_ledger.py`: 16 eventos de los 5 logs crudos, merge de
   copias duplicadas con rechazo si discrepan, `execution_class` independiente de `exit_code`,
   `evidence_id` sólo válido como id de REA si cumple `ev_<64 hex>`, artefacto verificado por sha256.
2. **Generador** `scripts/evidence004_generate.py`: `CANONICAL_RUN.json` → `RUN_REPORT.json/.md`,
   `INFORME_EJECUTIVO_NUMEROS.md` y bloques numéricos en `FINAL_REPORT.md`/`INFORME_EJECUTIVO.md`.
   Claims atados a contador o `evidence_id`; escritura atómica; lock de escritor único.
3. **Verificador independiente** `scripts/evidence004_verify.py`: relee los logs por su cuenta (no
   importa clasificador ni generador), descubre todos los informes, y rechaza **14/14** mutaciones.
4. **Sello histórico**: `evidence-004/SUPERSESSION_MANIFEST.json` conserva 6 documentos con hash de
   bytes. El informe que contaba 9 operaciones por código de salida sigue en el árbol, intacto y
   marcado; no se ha reescrito para que cuadre.
5. **Dos denominadores**: 7 evidenciadas + 2 no ejecutadas (trabajo de esta iteración) y 12 ids
   distintos (los cuatro dossiers). Ningún documento los suma.

**Medido**

```text
scripts/evidence004_generate.py                 exit 0
scripts/evidence004_verify.py                   exit 0   36 PASS / 0 FAIL
scripts/evidence004_verify.py --mutations       exit 0   14/14 rechazadas
scripts/ai_bots_rea_verify.py                   exit 0   73 PASS / 0 FAIL  (sin degradar)
pytest tests/unit/reports tests/unit/vision tests/unit/intelligence
                                                exit 0   176 passed
ruff / mypy sobre los tres scripts              exit 0
```

**Pendiente / bloqueado**

- `REAL_MODEL_CALLED = false`; ninguna operación REA reejecutada: este paquete cuenta logs.
- 5 de las 7 evidencias son declaradas, sin artefacto en disco: no se certifica ningún patrón.
- Suite completa del repositorio no ejecutada (hay 169 ficheros ajenos en vuelo). Declarado, no PASS.

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --format='%H %s'
./.venv/Scripts/python.exe scripts/evidence004_generate.py --json | head -4
./.venv/Scripts/python.exe scripts/evidence004_verify.py            # esperado: 36 PASS / 0 FAIL
./.venv/Scripts/python.exe scripts/evidence004_verify.py --mutations
./.venv/Scripts/python.exe scripts/ai_bots_rea_verify.py | tail -2  # esperado: 73 PASS / 0 FAIL
```

**Siguiente WP**: `AI-BOTS-003` (issue #12): causalidad de `bar.ts_ms`, latencia de respuesta y MTM
neto. EVIDENCE-004 no lo bloquea; garantiza que sus cifras no puedan contradecirse.

---

## WP-TAP-AI-BOTS-003B — motor de ejecución paper causal (2026-10-18)

**Rama:** `agent/ai-bots/RFC-TAP-AI-BOTS-003` · **Baseline:** `2921f6d` · **Motor:** `96957a2` · **Evidencia:** `e6707f9` (publicado; fast-forward sobre `2921f6d`)

**Objetivo.** Cerrar la consecuencia que el bloque A dejó escrita: con el reloj correcto,
cualquier latencia real descartaba el fill, porque el carril pedía la apertura de una vela
que ya había abierto antes de la respuesta. Un proveedor real producía `NO_TRADE` eterno.

**Hecho (verificado).**

- `src/trading_bot/vision/execution.py`: `Quote`/`quote_at`/`schedule`. Sólo una apertura de
  vela es cotización; cualquier instante dentro de una vela lanza `InsufficientResolution`
  en vez de interpolar. Ventana de la opinión declarada (`max_opinion_age_ms`, una vela por
  defecto) y registrada en la fila `RUN`.
- `lane.py`: entradas primero (la cotización es la primera apertura `>= received_at_ms`),
  después el rango de la vela para los stops, después marcas y decisiones. Cada `FILL` y
  cada `CLOSE` declaran su procedencia y su ventana.
- `paper/broker.py`: `check_positions_ohlc(..., gap_policy="open_on_gap")`; el valor por
  defecto no cambia para el resto de llamantes.
- `summary.reconciliation` con cinco identidades y `summary.execution` con la espera medida.
- `scripts/ai_bots_003b_verify.py`: verificador **independiente** (sin importar `trading_bot`)
  con 21 comprobaciones y 10 mutaciones.

```text
pytest tests/unit/vision/test_causal_execution.py   9 failed / 1 passed  ->  10 passed
pytest vision+paper+reports+intelligence            293 passed            exit 0
ruff / mypy                                         limpio                exit 0
ai_bots_003b_verify.py  VIS / CTX                   21 PASS / 0 FAIL c/u  exit 0
ai_bots_003b_verify.py --mutations  VIS / CTX       10 / 10 detectadas    exit 0
ai_bots_rea_verify.py                               73 PASS / 0 FAIL      exit 0
ai_bots_run.py --mode live (sin clave)              BLOCKED               exit 2
git archive HEAD -> raíces LF y CRLF                economía idéntica; verificación byte-idéntica
```

**Paper con 900 ms declarados:** 14 rellenos por bot (antes: 0), espera 1 h − 900 ms,
8 stops / 6 objetivos, bruto +6.70, costes −22.38, neto −15.68. `MOCK_TEST`.

**Sustituido, dicho en voz alta:** `test_a_latency_below_the_timeframe_...` afirmaba
`fills == 0` con 60 s y el test del hueco afirmaba `STALE_EXECUTION`; ambas eran la
consecuencia de B-01, no propiedades. Ahora comprueban lo que importa: ningún relleno paga
un precio anterior a la respuesta.

**Pendiente / bloqueado**

- `REAL_MODEL_CALLED = false`; el bloqueo de la llamada real multimodal sigue en `BLOCKED_MODEL_API`.
- Los dos bots dan el mismo resultado porque el guion mock ignora el prompt: fontanería, no paridad.
- El ledger no es byte-idéntico entre runs: cada línea sella `recorded_at_utc`. Se compara
  por contenido económico y por cadena recalculada.
- Suite completa del repositorio no ejecutada (171 ficheros ajenos en vuelo).

**Reanudación verificable**

```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --format='%H %s'
./.venv/Scripts/python.exe -m pytest tests/unit/vision/test_causal_execution.py -q   # esperado: 10 passed
./.venv/Scripts/python.exe scripts/ai_bots_003b_verify.py \
  --ledger reports/ai-bots/RFC-AI-BOTS-003/BLOCK-B/runs/bot-vis-01/BOT-VIS-01_DECISIONS.jsonl \
  --summary reports/ai-bots/RFC-AI-BOTS-003/BLOCK-B/runs/bot-vis-01/SUMMARY.json --root .   # esperado: 21 PASS / 0 FAIL
./.venv/Scripts/python.exe scripts/ai_bots_003b_verify.py \
  --ledger reports/ai-bots/RFC-AI-BOTS-003/BLOCK-B/runs/bot-vis-01/BOT-VIS-01_DECISIONS.jsonl \
  --summary reports/ai-bots/RFC-AI-BOTS-003/BLOCK-B/runs/bot-vis-01/SUMMARY.json --mutations   # esperado: 10/10
```

**Siguiente WP**: `AI-BOTS-003C/D` — proveedor offline listo (`NO_KEY => BLOCKED`) y colector
prospectivo con hash. La llamada real multimodal sigue necesitando clave y aprobación de coste.
