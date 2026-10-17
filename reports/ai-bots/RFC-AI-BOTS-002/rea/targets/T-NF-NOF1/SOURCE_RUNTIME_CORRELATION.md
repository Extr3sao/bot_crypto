# T-NF-NOF1 · Correlación fuente ↔ artefacto observado ↔ nuestro runtime

## Qué es cada plano (no se mezclan)

| Plano | Qué hay | Cómo se obtuvo |
| --- | --- | --- |
| Fuente upstream | `195440/nof1.ai`, AGPL-3.0, TypeScript (no clonado: 2,9 GB libres) | metadato + licencia por API de GitHub |
| Artefacto observado | 12 chunks JS compilados servidos por `https://nof1.ai/`, digest de directorio `5fbc183a…744b9` | descarga directa + `analyze-javascript-application` |
| Runtime observado | página pública renderizada en Chrome 155 bajo CDP loopback, perfil vacío | `capture-web-screenshot` + `analyze-web-bundle` |
| Nuestro runtime | `src/trading_bot/vision/lane.py`, `compare.py`, `paper/`, `risk/` | tests de este repositorio |

## Correlación que se puede sostener

1. **El proyecto existe y sirve una aplicación Next.js** con 12 chunks independientes y 43
   scripts en la captura completa (0 fallos de parseo). Eso es un hecho observado, no una
   descripción de su README.
2. **El bundle no expone nombres**: 7 nodos `endpoint` con valores `dpl`, `a`, `b`, `cookie`,
   `/_next/image`. La minificación borra exactamente la información que permitiría
   correlacionar su flujo con el nuestro.
3. **La cobertura es parcial por recursos**, no por decisión: 2 ficheros agotaron el heap del
   worker (`1ht6x9rgxdzh-.js`, `2-93uiwpd3jjk.js`) y 4 excedieron el presupuesto de resultado
   del proceso padre. Sus hechos semánticos no están y no se pueden inventar.

## Correlación que NO se puede sostener (y no se hace)

* No hay correlación **gráfico → llamada multimodal → parser → decisión**: REA no ejecuta el
  JS y el artefacto no contiene esa traza legible.
* No hay correlación con `RiskManager`, `PaperBroker` ni con el ledger propio: en el
  original no se observó ninguna de esas capas.
* Por tanto la fila de nuestra tabla comparativa es `NOT_COMPARABLE`, no `EQUIVALENT` ni
  `DIVERGENT`.

## Nuestra parte, que sí está probada

| Defecto/garantía | Implementación | Test |
| --- | --- | --- |
| Imagen ajena al gráfico | `lane._decide` ⇒ `INTEGRITY_FAILURE` + `return None` | `test_integrity_and_latency.py::test_a_mismatched_image_hash_aborts_the_decision_and_every_fill` |
| Respuesta tardía | `lane._execute` ⇒ `LATE_RESPONSE`, sin fill | `test_an_answer_that_arrives_after_the_fill_bar_opened_is_dropped` |
| Veredicto con insumos distintos | `compare.comparison` ⇒ `NOT_COMPARABLE` | `test_compare.py::test_a_cadence_difference_is_not_comparable_without_being_told` |
| Defensas de mercado y semana | `paper_cycle._defensive_verdict`, `RiskManager.roll_week` | `tests/unit/risk/test_edge17_defensive_blocks.py`, matriz de riesgo |
