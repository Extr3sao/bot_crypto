# FINAL_REPORT — RFC-TAP-AI-BOTS-002 v3 (REA-FIRST)

**Fecha:** 2026-10-18 · **Rama:** `agent/ai-vision/RFC-AI-VISION-001` · **HEAD al empezar:** `6f637a7`

## Veredicto en una línea

`REA_FOUNDATION_READY` con **un target realmente observado** (`T-NF-NOF1`, 4 `evidence_id`
reales) y **cinco targets bloqueados con motivo medido**; los tres P0 propios que podían
producir una operación falsa están cerrados con tests RED→GREEN. Ninguna adopción externa
se certifica: `EXTERNAL_PATTERN_ADOPTION_VERIFIED = false`. `FALSE_SUCCESS = 0`.

## Por target

| Target | `REA_EXECUTED` | Operación / capacidad | `REA_EVIDENCE_ID` | Observado | Divergencias | Decisión |
| --- | --- | --- | --- | --- | --- | --- |
| `T-NF-NOF1` | **YES** | `analyze-javascript-application`, `list-browser-targets`, `capture-web-screenshot`, `analyze-web-bundle` | `ev_aee35b0f…5617fc`, `ev_f7020db1…1bb00`, `ev_47c01acc…faf1`, `ev_82d99570…1d56c` | 12 chunks, 231.769 nodos AST, 15 hallazgos; bundle de 43 scripts; página pública capturada | sin traza de cadena gráfico→modelo→decisión | **DEFER** (código `REJECT`) |
| `T-QR-SIGNAL` | NO | CDP sobre panel Streamlit local | — | ninguno | — | `DEFER` (UI de framework; 2,9 GB libres) |
| `T-FE-FENIX` | NO | CDP sobre servicio local | — | ninguno | — | `DEFER` (sin superficie JS/Electron propia) |
| `T-TA-CRITIC` | NO | superficie HTML/web | — | ninguno | — | `EXPERIMENT` (HTML no prueba el grafo) |
| `T-FM-DEMO` | NO | ninguna | — | ninguno | — | **`REJECT`** (sin licencia: NO_COPY) |
| `T-TAP-OWN` | NO aplica | dashboard propio | — | no hay `.js`/`.html` de aplicación | — | `NOT_APPLICABLE_TECHNICALLY` |

Los `evidence_id` están completos en `REA_FINDINGS_V2.json`, `REA_TARGET_MATRIX.csv` y
`rea/targets/T-NF-NOF1/REA_EVIDENCE.json`; aquí van abreviados sólo por legibilidad.

## Defectos propios (P0) — cerrados con evidencia

| Defecto | Test | RED (HEAD) | GREEN |
| --- | --- | --- | --- |
| Hash de imagen distinto no abortaba | `test_a_mismatched_image_hash_aborts_the_decision_and_every_fill` | fallaba | pasa |
| Respuesta tardía podía rellenar a precio pasado | `test_an_answer_that_arrives_after_the_fill_bar_opened_is_dropped` | fallaba | pasa |
| Comparador podía dar veredicto con entradas distintas | `test_a_cadence_difference_is_not_comparable_without_being_told` | fallaba | pasa |
| Control: latencia 0 sigue operando | `test_an_on_time_answer_still_fills` | — | pasa |

Medición: contra `HEAD` **6 failed, 9 passed**; con los arreglos **15 passed**.
Suite focalizada (`vision`, `intelligence`, `paper`, `risk`): **372 passed**. `ruff` y `mypy`
limpios sobre los ficheros tocados.

Bloques defensivos y `roll_week`: **verificados en el código canónico** —
`paper_cycle._defensive_verdict` falla cerrado si faltan condiciones y
`RiskManager.check_signal` llama `roll_week()` en cada decisión; cobertura existente en
`tests/unit/risk/test_edge17_defensive_blocks.py`.

## Correcciones a la auditoría previa

1. **FenixAI es Apache-2.0** (API de GitHub), no MIT.
2. **AGPL no impide estudiar nof1.ai**; impide copiar/derivar sin cumplir obligaciones. No se copió código.
3. **El `doctor` global en rojo no bloquea JS/CDP**: cuatro operaciones REA corrieron con exit 0.

## Lo que queda bloqueado, dicho como bloqueo

* **Llamada multimodal real**: `BLOCKED_MODEL_API` (sin credencial ni autorización de gasto). Cero llamadas reales, cero `REAL_MODEL_CALLED`.
* **Comparación económica VIS vs CTX vs CURRENT vs NO_TRADE**: `NOT_EVIDENCE`; el único run existente usa guion mock y su −34,448805 USDT es del guion.
* **Certificación de patrones externos**: `NO_REA_EVIDENCE = NO_CERTIFICATION`. Sólo nof1 tiene evidencia y no alcanza la cadena que importa.

## Siguiente paso con más valor

Conseguir **un** artefacto local autorizado de uno de los targets Python (por ejemplo el
servidor de pruebas de Semantic Signal) y ejecutar REA CDP sobre su UI real para comparar
el ciclo de decisión, o ampliar el análisis de nof1 con `--fetch-source-maps` para recuperar
nombres legibles. Ambas cosas necesitan espacio en disco: hoy hay 2,9 GB libres.
