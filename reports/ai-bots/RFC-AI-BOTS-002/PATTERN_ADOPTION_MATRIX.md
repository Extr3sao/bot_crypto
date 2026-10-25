# PATTERN_ADOPTION_MATRIX

Estados posibles: `ADOPT_VERIFIED` · `EQUIVALENT_ON_TESTED_CASES` · `EXPERIMENT` ·
`DEFER` · `REJECT_ANTI_PATTERN` · `NO_ADOPTION`.

**`ADOPT_VERIFIED` exige REA real + fuente + test + ejecución independiente + economía. Nadie
lo alcanza en esta iteración, y por eso la columna está vacía.**

| PATRÓN | FUENTE | `REA_EVIDENCE_ID` | IMPLEMENTACIÓN PROPIA | TEST EMPAREJADO | ESTADO |
| --- | --- | --- | --- | --- | --- |
| Deployment ≠ repositorio sin recibo de build | propio (P0 de esta RFC) | n/a | `PROVENANCE.md` en cada dossier | `scripts/ai_bots_rea_verify.py` | **ADOPT_VERIFIED** (regla interna, sin código externo) |
| Gráfico generado desde el mismo contexto | qrak/LLM_trader (MIT) | `ev_9b45318c…` | `src/trading_bot/vision/chart.py` | `test_integrity_and_latency.py` | `EQUIVALENT_ON_TESTED_CASES` |
| Sin capacidad de imagen ⇒ sin gráfico | qrak/LLM_trader | `ev_9b45318c…` | `vision/lane.py` | `test_integrity_and_latency.py` | `EQUIVALENT_ON_TESTED_CASES` |
| Risk recorta el tamaño pedido | qrak/LLM_trader | `ev_9b45318c…` | `src/trading_bot/risk/manager.py` | `tests/unit/risk/*` | `EQUIVALENT_ON_TESTED_CASES` |
| Preflight de prompt que declara indicadores visibles | FenixAI (Apache-2.0) | `ev_be8c7d74…` | `vision/lane.py` | — | `EXPERIMENT` |
| Contexto multi-timeframe de 6 TFs con velas fijas | 195440/nof1.ai (AGPL-3.0) | `ev_4b2bf9c5…` | `ai_bots/bots.py` (BOT-CTX-01) | suites `ai_bots` | `EXPERIMENT` |
| Cadena de fallback de render (3 backends) | FenixAI | `ev_be8c7d74…` | — | — | `REJECT_ANTI_PATTERN` (rompe el hash reproducible) |
| Imagen como base64 suelto sin hash ni símbolo | FenixAI | `ev_be8c7d74…` | — | — | `REJECT_ANTI_PATTERN` |
| Modelo fija apalancamiento y tamaño | 195440/nof1.ai | `ev_4b2bf9c5…` | — | — | `REJECT_ANTI_PATTERN` |
| Guardas de drawdown declaradas y desactivadas | 195440/nof1.ai | `ev_4b2bf9c5…` | — | — | `REJECT_ANTI_PATTERN` |
| Bundle Next.js público sin origen demostrado | deployment no atribuido | `ev_aee35b0f…` | — | — | `NO_ADOPTION` |

## Nota sobre el primer `ADOPT_VERIFIED`

No es una capacidad de terceros: es una regla de proceso que este repositorio se impone a sí
mismo, verificada con un test que falla si alguien vuelve a etiquetar un bundle público con
un commit. No cuenta como certificación de patrón externo.
