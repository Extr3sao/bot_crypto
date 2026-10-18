# RUN_REPORT — RFC-TAP-AI-BOTS-004 / BOT-CRI-01

**Fecha:** 2026-10-18 · **Rama:** `agent/ai-critic/RFC-TAP-AI-BOTS-004` · **Base:** `b7e100a`
**Worktree:** `bot_crypto_004` (aislado; el árbol de AI-BOTS-003C no se tocó)

## Resultado en una línea

`BOT-CRI-01` existe, está registrado **OFF**, revisa propuestas congeladas y evidencia
autenticada, y en `SHADOW_ONLY` no altera fills, PnL ni riesgo. El valor económico está
**UNMEASURED**: no hubo llamada real a modelo ni muestra prospectiva. `GATED_PAPER` sigue
**BLOQUEADO** hasta la validación de AI-BOTS-003C.

## Fases

| WP | Estado | Evidencia |
| --- | --- | --- |
| 004-00 fuente fijada | DONE | `SOURCE_MANIFEST.json` (commit `e8f5503…`, Apache-2.0, 15 ficheros con SHA) |
| 004-01 REA | DONE | `REA_TARGET_EVIDENCE.json` → `REA_UI_OBSERVED`, 3 evidence ids nativos |
| 004-02 Python upstream | DONE | `UPSTREAM_PYTHON_TRACE.jsonl` (9 filas), `UPSTREAM_TESTS.json` (64 passed) |
| 004-03 contratos y registro | DONE | `BOT_CAPABILITY_REGISTRY.json`, `trading_bot.intelligence.ai_critic` |
| 004-04 shadow | DONE | `ABLATION_REPORT.json` (economía idéntica, 8 revisiones) |
| 004-05 gated paper | **BLOQUEADO** | falta la validación de AI-BOTS-003C |
| 004-06 verificador + mutaciones | DONE (límite declarado) | `INDEPENDENT_VERIFICATION.json` 59/59, `MUTATION_REPORT.json` 7/7 |
| 004-07 ablación / valor | INCONCLUSIVE | `ECONOMIC_VALUE=UNMEASURED` |

## Comandos ejecutados (exit codes reales)

```text
pytest tests/unit/intelligence/ai_critic -q                      exit 0   17 passed
pytest tests/unit/intelligence/ai_bots -q                        exit 0   28 passed
pytest tests/unit/intelligence tests/unit/vision -q              exit 0   169 passed
pytest (upstream) test_debate_opening test_structured_agents
                  test_report_html -q                            exit 0   64 passed
ruff check src/.../ai_critic tests/.../ai_critic scripts/ai_critic exit 0
mypy src/trading_bot/intelligence/ai_critic                      exit 0
scripts/ai_critic/upstream_critic_harness.py                     exit 0   21/21 checks, 0 network
scripts/ai_critic/run_rea_target.py                              exit 0   REA_UI_OBSERVED
scripts/ai_critic/run_ablation.py                                exit 0   shadow idéntico
scripts/ai_critic/verify_rfc004.py --mutations                   exit 0   59/59, 7/7
```

## Separación de receipts

| Receipt | Qué prueba | Qué no prueba |
| --- | --- | --- |
| REA evidence ids | una operación real sobre la página renderizada | el razonamiento Python |
| `UPSTREAM_PYTHON_TRACE` | los nodos originales recorrieron la secuencia con un stub | que REA lo viera o que un modelo razonara |
| `ABLATION_REPORT` | SHADOW no cambia la economía | valor prospectivo |
| `INDEPENDENT_VERIFICATION` | los artefactos son internamente coherentes y las reglas se aplican | independencia institucional (mismo agente) |

## Bloqueos declarados

- `MODEL_API_UNAVAILABLE`: sin credencial ni autorización de gasto → `REAL_CRITIC_MODEL_CALLED=false`.
- `GATED_PAPER_NOT_AUTHORIZED`: AI-BOTS-003C no está certificado en esta rama.
- `INCONCLUSIVE_VALUE`: 10 oportunidades sintéticas, 4 propuestas accionables, 0 coste medido, 0 PnL atribuible al crítico.
- `REA_TARGET` limita la observación a la representación visual (HTML estático sin JavaScript).

`FALSE_SUCCESS = 0`.
