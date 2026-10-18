# FINAL_REPORT — RFC-TAP-AI-BOTS-004 · BOT-CRI-01

**Fecha:** 2026-10-18
**Rama:** `agent/ai-critic/RFC-TAP-AI-BOTS-004`
**Base:** `b7e100a` (EVIDENCE-004F) · **Worktree:** `bot_crypto_004`
**Issue:** [#14](https://github.com/Extr3sao/bot_crypto/issues/14)
**Upstream:** `TauricResearch/TradingAgents` @ `e8f5503e9b86d5c2710b0c76b1f686703968c9df` (Apache-2.0)

---

## 1. Phase

| Fase | Estado | Nota |
| --- | --- | --- |
| 004-00 preflight / fuente | `DONE` | worktree aislado, 4.1 GB libres, fuente pinneada |
| 004-01 REA | `DONE` | `REA_UI_OBSERVED` sobre la página renderizada |
| 004-02 Python upstream | `DONE` | nodos originales, stub, red a 0 |
| 004-03 contratos + registro | `DONE` | BOT-CRI-01 por defecto OFF |
| 004-04 SHADOW | `DONE` | economía idéntica al baseline |
| 004-05 GATED_PAPER | `BLOCKED` | falta AI-BOTS-003C |
| 004-06 verificador + mutaciones | `DONE` (límite declarado) | 59/59 checks, 7/7 mutaciones |
| 004-07 valor prospectivo | `BLOCKED` | sin proveedor real ni muestra OOS |

## 2. Commits

- `C1` `fb059432fb47b70c730cf5c4795de8c2b56878a9` — implementación, tests, harness upstream, dossier REA, ablación, informes.
- `C2` `6871a2b6c398f4d221200418ea57f7718a615b39` — bytes de auditoría pinneados; tests (45 passed) y verificador (59/59, 7/7) ejecutados en extracción limpia `git archive` de este commit.
- `C3` — solo `reports/` (receipts y actualización de este informe/checkpoint); no modifica `src/` ni `tests/`.

Antes de `C1` no se tocó ningún fichero del árbol de AI-BOTS-003C: se trabajó en un worktree
separado creado desde `b7e100a` con `git worktree add`.

## 3. Implemented

| Componente | Fichero |
| --- | --- |
| Contratos `FrozenTradeProposal`, `EvidenceLedger`, `CriticReview`, `AgentMessage`, `ReviewDecisionTrace` | `src/trading_bot/intelligence/ai_critic/contracts.py` |
| Prompt versionado `TAP-PROMPT-CRI-001/v1` + detección de inyección | `src/trading_bot/intelligence/ai_critic/prompt.py` |
| Proveedor con receipts `REAL`/`MOCK`/`REPLAY`/`NONE` | `src/trading_bot/intelligence/ai_critic/provider.py` |
| Servicio de revisión: presupuesto, deadline, parseo estricto, fail-closed | `src/trading_bot/intelligence/ai_critic/critic.py` |
| Política `OFF` / `SHADOW_ONLY` / `GATED_PAPER` | `src/trading_bot/intelligence/ai_critic/policy.py` |
| Trazas `CRITIC_REVIEWS`, `DECISION_TRACE`, `MODEL_INVOCATIONS`, `AGENT_MESSAGES` | `src/trading_bot/intelligence/ai_critic/trace.py` |
| Registro `BOT-CRI-01` (OFF, sin herramientas de ejecución) | `src/trading_bot/intelligence/ai_bots/registry.py` |

Garantías estructurales:

- `extra="forbid"` en todos los contratos; un campo de tamaño, leverage, stop u orden es un
  fallo de esquema, no un permiso.
- El crítico no importa `PaperBroker`, `RiskManager` ni adaptadores de exchange.
- La única acción del gate es `SUPPRESS_NEW_ENTRY`; `CLOSE`, `REDUCE`, `STOP` y
  `TAKE_PROFIT` se permiten antes de consultar la revisión.
- Respuesta tardía → `ABSTAIN LATE_RESPONSE` y, en un gate autorizado, `NO_TRADE`.
- Presupuesto comprobado **antes** de llamar; una llamada como máximo.

## 4. Tests

`RED → GREEN` medido: en `b7e100a` el paquete no existe y la suite falla en colección
(exit 2); en este árbol pasa (exit 0, 17 items). `TEST_TARGET == RUNTIME_TARGET` =
`trading_bot.intelligence.ai_critic` (ruta importada registrada en `TEST_RED_GREEN.json`).

| Suite | Resultado |
| --- | --- |
| `tests/unit/intelligence/ai_critic` | 17 passed |
| `tests/unit/intelligence/ai_bots` | 28 passed |
| `tests/unit/intelligence` + `tests/unit/vision` | 169 passed |
| Upstream focal (`debate_opening`, `structured_agents`, `report_html`) | 64 passed |
| `ruff` / `mypy` sobre el paquete nuevo | exit 0 |

ACC-CRI-01..16 cubiertos: contrato, hash congelado, vocabulario, evidencia/counter-evidencia,
alucinación, evidencia ausente, contradicción, JSON inválido, esquema, prompt injection,
error de proveedor, presupuesto, latencia, política shadow/gated, registro/replay.

**Limitación:** el fichero `RFC_TAP_AI_BOTS_004_REA_INDEPENDENT_CRITIC.md` no estaba entre
los adjuntos de la sesión. La lista ACC-CRI-01..16 se reconstruyó desde el prompt de
ejecución y el roadmap, y se documenta aquí para que pueda contrastarse con el RFC canónico.

## 5. Runtime validation

| Comprobación | Resultado |
| --- | --- |
| Harness sobre fuente pinneada | 21/21 checks, `network_calls=0`, `orders=0`, `MODEL_STATUS=STUB` |
| Secuencia Bull → router → Bear → router → Manager | cadena de hashes verificada |
| Fallback y rechazo de esquema upstream | ejecutados y registrados |
| HTML generado por el renderizador original | `7949425a…` (29 375 bytes, sin `<script>`, sin assets remotos) |
| REA | `list_browser_targets`, `inspect_web_page`, `capture_web_screenshot` con evidence ids nativos; `scripts.total=0`; headings Bull/Bear/Manager presentes |
| Captura | PNG 1262×1904, SHA `a155d92e…`, base64 decodificado idéntico al fichero |

Lo que **no** se valida: que REA haya auditado el debate. El HTML es estático y no ejecuta
JavaScript; la conducta Python se prueba con el harness, etiquetada
`UPSTREAM_PYTHON_INSTRUMENTED_NOT_REA`.

## 6. Paper validation

| Brazo | Ejecutado | Resultado |
| --- | --- | --- |
| `NO_CRITIC` | sí | 2 fills, 2 cierres, neto `+5.258942` USDT |
| `SHADOW` | sí | misma economía; 8 revisiones; 3 ACCEPT, 5 CHALLENGE |
| `NO_TRADE` | sí | 0 fills, 0 PnL |
| `GATED_PAPER` | **no** | `BLOCKED_GATED_PAPER_NOT_AUTHORIZED` |

- Misma secuencia de 10 puntos de decisión, mismos activos, capital, fees y slippage.
- `economics_affected=false` en las 8 trazas; 4 revisiones protectoras, **0 bloqueadas**.
- Un crítico que vetara todo habría sido marcado degenerado; la tasa de challenge fue 0.25.
- El único «valor» medido es coste/latencia: 0 USD (mock) y latencia de revisión de milisegundos.

`ECONOMIC_VALUE = UNMEASURED` · `REAL_CRITIC_MODEL_CALLED = false` ·
`PROSPECTIVE_EDGE_VERIFIED = false` · Recomendación: **`DO_NOT_ADOPT_PENDING_PROSPECTIVE`**.

## 7. False success

`FALSE_SUCCESS = 0`.

- El verificador no importa módulos del builder y recalcula hashes, economía y reglas.
- 7 mutaciones re-selladas son rechazadas por **regla**, no por hash: evidence id falso,
  commit ajeno autoconsistente, `exit 0 + NOT_EXECUTED`, REA auditando razonamiento,
  `ADOPT_VERIFIED` sin edge, bytes de screenshot distintos con id correcto, y una review
  re-sellada que cita contra-evidencia como ACCEPT.
- `all()` sobre colecciones vacías está bloqueado por `EMPTY-01` (count > 0).

## 8. Defects

1. **Verificador del mismo autor.** La independencia es estructural, no institucional. Un
   segundo agente debe re-ejecutar `verify_rfc004.py` antes de cualquier promoción.
2. **RFC canónico ausente.** ACC-CRI-01..16 reconstruido (ver §4); puede no coincidir
   literalmente con el documento del issue.
3. **Informes de analistas fixture.** El `final_state` usa informes de analistas declarados
   como fixture; solo las secciones de debate son salida del harness.
4. **`doctor` de REA no saludable** por falta de Ghidra/Hopper. No afecta a la observación
   web y queda registrado con exit 1.
5. **Ablación sintética.** 4 propuestas accionables no permiten ninguna inferencia económica.

## 9. Blockers

- `MODEL_API_UNAVAILABLE` — sin credencial ni autorización de gasto explícita.
- `GATED_PAPER_NOT_AUTHORIZED` — AI-BOTS-003C no certificado en esta rama; no se activó el flag.
- `INCONCLUSIVE_VALUE` — sin muestra prospectiva ni coste real medido.
- `REA_TARGET_LIMITED` — la superficie observada es visual; el razonamiento no es observable por REA.

## 10. Evidence

| Artefacto | Contenido |
| --- | --- |
| `SOURCE_MANIFEST.json` | commit, licencia y SHA de 15 ficheros; artefactos promovidos |
| `UPSTREAM_PYTHON_TRACE.jsonl` | 9 filas con hashes de prompt/estado/salida, red 0, órdenes 0 |
| `UPSTREAM_TESTS.json` | 3 ejecuciones upstream con stdout/stderr/exit |
| `REA_OPERATION_LOG.jsonl` / `REA_TARGET_EVIDENCE.json` | operaciones, evidence ids nativos, target, screenshot |
| `SOURCE_RUNTIME_CORRELATION.md` | fuente → nodos → estado → HTML → REA, con límites |
| `RECONSTRUCTION_OBLIGATIONS.json` | 10 obligaciones patrón→TAP con estado |
| `BOT_CAPABILITY_REGISTRY.json` | BOT-CRI-01 OFF, política de gate |
| `CRITIC_REVIEWS.jsonl` / `DECISION_TRACE.jsonl` / `MODEL_INVOCATIONS.jsonl` / `AGENT_MESSAGES.jsonl` | revisiones selladas, decisión, receipts, turnos |
| `ABLATION_REPORT.json/md` | brazos, métricas, veredicto |
| `INDEPENDENT_VERIFICATION.json` / `MUTATION_REPORT.json` | 59/59 checks, 7/7 mutaciones |
| `TEST_RED_GREEN.json` | RED en base, GREEN en HEAD, mismo target |
| `CLEAN_CHECKOUT_REHEARSAL.json` | tests y verificador sobre una extracción limpia de `git archive` (45 passed; 59/59; 7/7) |

## 11. Architecture status

`IMPLEMENTED / SHADOW_ONLY`. BOT-CRI-01 es un plugin de opinión: no hay segundo
`RiskManager`, no hay segundo broker, no se modificó `config/risk.yaml` ni ningún adaptador
de exchange. `AI_BOTS_ENABLED` y el flag del bot siguen siendo necesarios para ejecutarlo.

## 12. RFC status

| Gate | Estado |
| --- | --- |
| Fuente pinneada | `PASS` |
| REA real sobre superficie compatible | `PASS` (solo representación) |
| Python upstream instrumentado | `PASS` (stub, sin red) |
| Contratos + registro OFF | `PASS` |
| SHADOW sin impacto económico | `PASS` |
| GATED_PAPER | `BLOCKED` |
| Modelo real | `BLOCKED` |
| Valor prospectivo | `INCONCLUSIVE` |

**`RFC_STATUS = INCONCLUSIVE_VALUE`** — nunca `PASS`: dos gates obligatorios faltan y el
valor económico no está medido.

## 13. Next phase

1. Certificar AI-BOTS-003C y sólo entonces habilitar `GATED_PAPER` con el token
   `AI_BOTS_003C_VALIDATED`, midiendo supresión de aperturas y PnL incremental.
2. Con autorización de gasto, sustituir el proveedor scripted por uno real y registrar
   receipts `REAL` (mismo prompt, mismo esquema, mismo presupuesto).
3. Ablación prospectiva con la misma secuencia de oportunidades y muestra OOS suficiente;
   mantener `DO_NOT_ADOPT` si no hay mejora neta.
4. Revisión por un segundo agente del verificador y de los 7 rechazos de mutación.
5. Alinear ACC-CRI-01..16 con el RFC canónico cuando el documento esté disponible.
