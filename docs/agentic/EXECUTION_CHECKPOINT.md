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
