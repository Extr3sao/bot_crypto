# PATTERN_ADOPTION_MATRIX

Cada fila separa **proyecto**, **patrón** e **implementación**. Una adopción sólo es
`ADOPT_*` si el patrón está implementado y con test en este repositorio.

| ID | Patrón | Proyecto de origen | Decisión | Implementación propia | Test | Motivo |
| --- | --- | --- | --- | --- | --- | --- |
| P-01 | PNG determinista con hash por ventana | qrak (patrón) | ADOPT_P0 | `vision/chart.py` (ya existía; corregido) | `test_chart.py`, `test_visual_defects.py` | Sin esto no se puede probar qué vio el modelo |
| P-02 | Contrato JSON estricto, sin campos de ejecución | qrak, FenixAI (patrón) | ADOPT_P0 | `vision/contract.py`, `ai_bots/contracts.py` | `test_contract.py`, `test_registry_contracts_runner.py` | Un texto libre no es una orden |
| P-03 | Ledger de decisiones append-only | nof1.ai (patrón descrito) | ADOPT_P0 | `vision/ledger.py` (cadena de hashes) | `test_ledger.py` + verificación independiente | Permite re-ejecutar la misma decisión |
| P-04 | Registro de capacidades/plugins con permisos | TradingAgents (patrón) | ADOPT_P0 | `ai_bots/registry.py` | `test_registry_contracts_runner.py` | Un bot no debe poder tocar el libro |
| P-05 | Un único `RiskManager`/`PaperBroker` por run | patrón del runtime | ADOPT_P0 | `ai_bots/runner.py` | `test_a_bot_run_trades_the_canonical_book_and_writes_both_traces` | Comparación honesta entre bots |
| P-06 | Control sin imagen para aislar el efecto multimodal | Semantic Signal (idea de ablación) | ADOPT_P1 | `ai_bots/bots.py` (`build_structured_prompt`) | `test_structured_prompt_never_claims_an_image` | Sin control no se sabe si el PNG aporta algo |
| P-07 | Crítico/adversario ortogonal | TradingAgents | EXPERIMENT | no implementado | — | Sólo si la ablación demuestra mejora neta |
| P-08 | Consenso de dos modelos | TradingAgents, nof1 | EXPERIMENT | no implementado | — | Duplica coste y latencia antes de saber si hay edge |
| P-09 | Decisión por substring de texto libre | FortuneMal | REJECT | — | — | Sin schema ni riesgo |
| P-10 | Grafo multiagente completo con roles fijos | TradingAgents | DEFER | — | — | Latencia y coste sin evidencia de mejora |
| P-11 | Operar sólo con series numéricas sin imagen | nof1.ai | REJECT como sustituto | — | — | No es visión; se conserva como control P-06 |
| P-12 | Importar código AGPL/sin licencia | nof1.ai, FortuneMal | REJECT | — | — | Obligaciones materiales no autorizadas |

## Notas de coste y compatibilidad

- P-01…P-06 son Python puro, funcionan en Windows y no añaden dependencias nuevas salvo
  `matplotlib` (ya introducida en AI-VISION-001).
- P-07/P-08 quedan fuera por coste marginal no demostrado, no por dificultad técnica.
- Ninguna adopción cambia límites de riesgo, sizing ni la política de venue.

## Evidencia de que la matriz no es retórica

```text
tests/unit/vision + tests/unit/intelligence     146 passed
scripts/ai_bots_verify.py                       34 checks, PASS
BOT-VIS-01 images_attached=40   BOT-CTX-01 images_attached=0
```
