# SOURCE_REGISTRY — fuentes externas, licencia verificada y evidencia REA

**Regla:** `PROJECT != PATTERN != IMPLEMENTATION`. Ni una fila afirma que un proyecto
externo funcione, sólo lo que se ejecutó contra él.

Licencias verificadas contra la API de licencias de GitHub el 2026-10-18
(`GET /repos/<repo>/license`, HTTP 200 salvo donde se indica).

**v3.1:** la fila `SRC-NOF1` de la v3 mezclaba un despliegue con un repositorio. Ahora son
dos filas distintas y ninguna afirma un vínculo que no exista.

| SOURCE_ID | Proyecto | Licencia real (SPDX) | REA ejecutado | Evidencia | Adopción |
| --- | --- | --- | --- | --- | --- |
| SRC-NOF1 | 195440/nof1.ai @ `5d27641dfa47cc942aa0709ffb3f5237de876373` (proyecto real: `open-nof1.ai`) | **AGPL-3.0** | **SÍ** — `analyze_javascript_application` sobre `public/` del commit | `rea/targets/T-NF-NOF1/` · `ev_4b2bf9c5…` | Código: **REJECT**. Patrón multi-timeframe: `EXPERIMENT` |
| SRC-NOF1-PUBLIC | deployment no atribuido en `https://nof1.ai/` | **desconocida para ese artefacto** | **SÍ** — 4 operaciones (v3, conservadas) | `rea/targets/T-NF-PUBLIC/` · `ev_aee35b0f…`, `ev_f7020db1…`, `ev_47c01acc…`, `ev_82d99570…` | `NO_ADOPTION`: origen sin demostrar |
| SRC-FENIX | Ganador1/FenixAI_tradingBot @ `bd7373d5…` | **Apache-2.0** *(corregido: antes figuraba MIT)* | **SÍ** — 3 operaciones sobre el `dist` construido desde el commit | `rea/targets/T-FE-FENIX/` · `ev_be8c7d74…`, `ev_fc2b6552…`, `ev_b3b1e837…` | `DEFER`; transporte de imagen: `REJECT` |
| SRC-SEMSIG | qrak/LLM_trader @ `65e67dc2…` | **MIT** | **SÍ** — 3 operaciones sobre el dashboard del commit | `rea/targets/T-QR-SIGNAL/` · `ev_9b45318c…`, `ev_b954b8b0…`, `ev_ee6845ff…` | `DEFER`; invariante ya cubierto |
| SRC-TRADAGENTS | TauricResearch/TradingAgents @ `e8f5503` | **Apache-2.0** | NO | sin superficie JS propia; un informe HTML no prueba orquestación | `EXPERIMENT` |
| SRC-FORTUNE | FortuneMal/AI-trading @ `74ed1f3` | **sin licencia** (API 404) | NO | `NO_COPY` | `REJECT` |
| SRC-TAP-OWN | este repositorio | licencia del repo | NO aplica | no hay `.js`/`.html` de aplicación (medido) | `NOT_APPLICABLE_TECHNICALLY` |

## Correcciones respecto al registro anterior

1. **`www.nof1.ai` no es `195440/nof1.ai`.** El bundle público es Next.js/Turbopack
   (`__NEXT` en 9/12 chunks, `turbopack` en 7/12); el commit fijado no contiene Next.js en
   ningún fichero y su build es `tsdown`. Medición completa en
   `rea/targets/T-NF-NOF1/PROVENANCE.md`.
2. **FenixAI es Apache-2.0, no MIT.** La API de GitHub devuelve `spdx_id: Apache-2.0`.
3. **AGPL-3.0 no prohíbe estudiar nof1.ai.** Permite descargar, ejecutar y estudiar; las
   obligaciones nacen al copiar, modificar o redistribuir. En esta sesión se analizó el árbol
   del commit y **no se copió ni tradujo código**.
4. **Un `doctor` global en rojo no deshabilita JS/CDP.** Las 9 operaciones REA de esta
   iteración salieron con exit 0 sin Ghidra/Hopper/IDA.
5. **Hay un límite real del host, medido:** `import-reference-source` falla con
   `unsupported_host` en Windows, y con él `compare-source-to-bundle`. Está registrado como
   bloqueo, no como aprobado.

## Qué es nuestro y está probado en este repositorio

| Componente | Prueba |
| --- | --- |
| PNG causal, ventana fija, sin barra futura | `tests/unit/vision/test_chart.py`, `test_visual_defects.py` |
| Imagen alterada ⇒ 0 decisiones, 0 fills | `tests/unit/vision/test_integrity_and_latency.py` |
| Respuesta tardía ⇒ no se rellena a precio pasado | `tests/unit/vision/test_integrity_and_latency.py` |
| Comparador con entradas distintas ⇒ `NOT_COMPARABLE` | `tests/unit/vision/test_compare.py` |
| Guards PIT/esquema, ledger, registro de capacidades | `test_guards_and_controls.py`, `test_ledger.py`, `test_registry_contracts_runner.py` |

## Gaps que siguen abiertos

1. **`REAL_MODEL_CALLED = false`.** Cero llamadas, cero recibos, cero economía medida.
2. **Backends upstream no ejecutados.** Python (QRAK, FenixAI) y TypeScript (nof1) se
   auditaron por fuente: REA no los ejecuta y arrancarlos exige claves y servicios.
3. **Ningún patrón externo certificado.** `ADOPT_VERIFIED` de terceros = 0.
4. **TradingAgents y FortuneMal** sin REA: uno por falta de superficie, otro por falta de
   licencia. Ambos declarados, ninguno promocionado.
