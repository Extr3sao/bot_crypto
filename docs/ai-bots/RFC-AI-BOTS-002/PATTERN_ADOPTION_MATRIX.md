# PATTERN_ADOPTION_MATRIX — qué patrón, con qué evidencia, y en qué estado

Actualizado en la pasada REA-FIRST (2026-10-18). Regla vigente:
`NO_REA_EVIDENCE = NO_EXTERNAL_PATTERN_CERTIFICATION`.

| Patrón | Origen | Evidencia | Estado | Por qué |
| --- | --- | --- | --- | --- |
| PNG determinista + contrato estricto | propio (AI-VISION-001) + referencia de `SRC-QRAK` | tests de visión | **ADOPTED (propio)** | probado en este repo; de qrak no se copió código |
| Separación analista/ejecutor | `SRC-FENIX` (Apache-2.0) | ninguna REA | **DEFER** | sin superficie JS/Electron propia; sin clon por disco |
| Grafo bull/bear + crítico | `SRC-TRADAGENTS` (Apache-2.0) | ninguna REA | **EXPERIMENT** | un informe HTML no prueba la orquestación; ablación obligatoria antes de adoptar |
| Render Plotly → PNG | `SRC-SEMSIG` (MIT) | ninguna REA | **DEFER** | UI Streamlit = JS de framework; su lógica es Python y se audita con fuente/tests |
| Ledger de decisiones estilo nof1 | `SRC-NOF1` (AGPL-3.0) | 4 `evidence_id` reales, **estructura sólo** | **DEFER / REJECT código** | la cadena gráfico→modelo→decisión no fue observable; no se copia AGPL |
| Cualquier cosa de `SRC-FORTUNE` | sin licencia (API 404) | — | **REJECT** | `NO_COPY` sin licencia |

## Lo que sí está certificado (y no viene de fuera)

| Garantía | Test | Estado |
| --- | --- | --- |
| Imagen alterada ⇒ 0 propuestas, 0 fills | `test_integrity_and_latency.py` | **cerrado** |
| Respuesta tardía ⇒ sin fill retrospectivo | `test_integrity_and_latency.py` | **cerrado** |
| Insumos distintos ⇒ `NOT_COMPARABLE` | `test_compare.py` | **cerrado** |
| Defensas de mercado y veto semanal | `test_edge17_defensive_blocks.py`, matriz de riesgo | **verificado** |

## Hueco que queda abierto

Ningún patrón externo ha pasado de `DEFER`/`EXPERIMENT`: para ascender hace falta una
observación REA que muestre **comportamiento** (llamada, decisión, riesgo u orden), no
estructura. Hoy sólo nof1 tiene evidencia y no llega a ese punto.
