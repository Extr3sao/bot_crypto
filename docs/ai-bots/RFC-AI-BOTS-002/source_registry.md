# SOURCE_REGISTRY — fuentes externas, licencia verificada y evidencia REA

**Regla:** `PROJECT != PATTERN != IMPLEMENTATION`. Ni una fila afirma que un proyecto
externo funcione, sólo lo que se ejecutó contra él.

Licencias verificadas contra la API de licencias de GitHub el 2026-10-18
(`GET /repos/<repo>/license`, HTTP 200 salvo donde se indica).

| SOURCE_ID | Proyecto | Licencia real (SPDX) | REA ejecutado | Evidencia | Adopción |
| --- | --- | --- | --- | --- | --- |
| SRC-NOF1 | 195440/nof1.ai | **AGPL-3.0** | **SÍ** — 4 operaciones, 4 `evidence_id` | `rea/targets/T-NF-NOF1/` (bundle público, captura CDP, análisis estático) | Código: **REJECT**. Patrón: `DEFER` |
| SRC-FENIX | Ganador1/FenixAI_tradingBot | **Apache-2.0** *(corregido: antes figuraba MIT)* | NO | `TARGET_BASELINE` + motivo medido | `DEFER` |
| SRC-SEMSIG | qrak/LLM_trader | **MIT** | NO | ídem | `DEFER` |
| SRC-TRADAGENTS | TauricResearch/TradingAgents | **Apache-2.0** | NO | ídem | `EXPERIMENT` |
| SRC-FORTUNE | FortuneMal/AI-trading | **sin licencia** (API 404) | NO | ídem | `REJECT` (NO_COPY) |
| SRC-TAP-OWN | este repositorio | licencia del repo | NO aplica | no hay `.js`/`.html` de aplicación (medido) | `NOT_APPLICABLE_TECHNICALLY` |

## Correcciones respecto al registro anterior

1. **FenixAI es Apache-2.0, no MIT.** La API de GitHub devuelve `spdx_id: Apache-2.0`.
   Apache-2.0 permite uso y modificación con obligaciones de aviso; aun así no se copia código.
2. **AGPL-3.0 no prohíbe estudiar nof1.ai.** Permite descargar, ejecutar y estudiar; las
   obligaciones nacen al copiar, modificar o redistribuir. En esta sesión se analizó el
   bundle público y **no se copió ni tradujo código**.
3. **Un `doctor` global en rojo no deshabilita JS/CDP.** Las cuatro operaciones REA de este
   informe se ejecutaron con exit 0 en este host sin Ghidra/Hopper/IDA.

## Qué es nuestro y está probado en este repositorio

| Componente | Prueba |
| --- | --- |
| PNG causal, ventana fija, sin barra futura | `tests/unit/vision/test_chart.py`, `test_visual_defects.py` |
| Imagen alterada ⇒ 0 decisiones, 0 fills | `tests/unit/vision/test_integrity_and_latency.py` (nuevo) |
| Respuesta tardía ⇒ no se rellena a precio pasado | `tests/unit/vision/test_integrity_and_latency.py` (nuevo) |
| Comparador con entradas distintas ⇒ `NOT_COMPARABLE` | `tests/unit/vision/test_compare.py` (endurecido) |
| Guards PIT/esquema, ledger, registro de capacidades | `test_guards_and_controls.py`, `test_ledger.py`, `test_registry_contracts_runner.py` |

## Gaps que siguen abiertos

1. Ningún target salvo nof1 tiene evidencia REA; su bloqueo es **de almacenamiento y de
   superficie**, no una conclusión sobre su funcionamiento.
2. De nof1 sólo hay estructura estática y captura de página: **no hay traza de la cadena
   gráfico→modelo→decisión**, así que ningún patrón suyo puede certificarse.
3. La llamada multimodal real sigue `BLOCKED` por credencial/presupuesto.
