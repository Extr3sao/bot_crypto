# WP-PAPER-008C — IA read-only: contrato verificado, proveedor real bloqueado

**Fecha:** 2026-10-26 · **Host:** Windows 11 · **Ventana de referencia:** `paper-lab-rfc008-live-02`
**Estado:** `AI_REAL_BLOCKED_NOT_CONFIGURED` · **Contrato HTTP:** `VERIFIED` (stub local, no modelo)

---

## 1. Qué se ha demostrado

| Comprobación | Resultado | Evidencia |
| --- | --- | --- |
| Sin clave, el sidecar no inventa análisis | 18/18 filas `NOT_CONFIGURED`; `analysed=0` | `reports/autonomous-paper/paper-lab-rfc008-live-02/analysis.jsonl` |
| Sin clave, el stream no se queda sin cobertura | 100 % de las señales tienen fila; las nuevas se cubren | `/api/analysis` → `coverage 12/12 (100 %)` durante la ventana |
| El camino HTTP real funciona (endpoint compatible) | 5 → 9 `ANALYZED` con `claim`, `supporting_evidence`, `counter_evidence`, `uncertainties`, `model`, `prompt_version`, `latency_ms`, `cost_usd` | `evidence/paper008/ai_contract/analysis.jsonl` |
| Coste calculado con precios declarados | `0.000768 USD` para 5 análisis (`640 in / 96 out` tokens por llamada) | `evidence/paper008/ai_contract/CONTRACT_SUMMARY.json` |
| El panel muestra el estado de IA | `coverage 9/9`, `analysed=9`, `latency p95=30 ms`, `authority over orders=no` | `evidence/paper008/ai_contract/analysis_http.json` |
| Proveedor caído no detiene nada | 4 filas `FAILED` (`WinError 10061`), exit 0, sin órdenes | `analysis.jsonl` (mismas señales) |
| Endpoint que responde 405 | 2 filas `FAILED` (`provider returned HTTP 405`), exit 0 | `analysis.jsonl` |
| Timeout | 1 fila `FAILED` (`urlopen error timed out`), exit 0 | `analysis.jsonl` |
| Presupuesto agotado | 5 filas `PENDING` (`BUDGET_EXHAUSTED`), 0 llamadas, coste 0 | `evidence/paper008/ai_contract/analysis_budget_failure.jsonl` |
| Recuperación sin borrar historia | las 4 `FAILED` se superponen con `ANALYZED`; las filas fallidas se conservan | `CONTRACT_SUMMARY.json` → `final_statuses=ANALYZED` |
| El sidecar no puede ordenar | `read_only=true`, `authority_over_orders=false` en cada pasada | salida JSON del sidecar |

El stub es un servidor local que responde un objeto JSON válido en el formato que
exige `analysis.py`. **No es un modelo**: no se usó ninguna API de pago, no se
afirma calidad de análisis y estos datos **no** deben citarse como `AI_LIVE_PASS`.

## 2. Qué NO se ha demostrado (y por qué)

- **`AI_REAL_PASS`**: no hay `SIGNAL_ANALYST_API_KEY` en el host ni autorización de
  gasto. Sin una respuesta de proveedor real, el RFC prohíbe certificar la IA.
- **Coste real**: el coste del stub usa precios declarados a mano; el coste de un
  proveedor real depende de su tarifa y de los tokens facturados.
- **Calidad/edge del análisis**: fuera de alcance. La IA es read-only y no tiene
  autoridad sobre riesgo, sizing, admisión ni órdenes.

## 3. Cómo habilitar la IA real (cuando exista clave y gasto autorizado)

```bash
export SIGNAL_ANALYST_API_KEY=...        # nunca en el repositorio
export SIGNAL_ANALYST_MODEL=gpt-4o-mini  # o el modelo autorizado
export SIGNAL_ANALYST_BASE_URL=https://api.openai.com/v1
export SIGNAL_ANALYST_INPUT_USD_PER_MTOK=...
export SIGNAL_ANALYST_OUTPUT_USD_PER_MTOK=...
uv run python scripts/ai_signal_analyst.py --run-root reports/autonomous-paper \
  --run-id paper-lab-rfc008-live-02 --once --limit-per-pass 3 --json
```

Después: `uv run python scripts/wp_signal_verify.py --run-id <id> --dashboard-url http://127.0.0.1:8981`
y comprobar que las filas nuevas son `ANALYZED` con `claim` no nulo. Solo entonces
se puede cambiar el estado a `AI_REAL_VERIFIED`.

## 4. Defecto corregido en este WP

`NOT_CONFIGURED` no era terminal: con `--limit-per-pass 5`, las cinco señales más
antiguas se re-examinaban en cada pasada y las nuevas nunca se cubrían (observado
`8/12`). Ahora es terminal mientras no haya proveedor y vuelve a ser elegible en
cuanto aparece la clave; hay test de no-inanición (`test_not_configured_rows_do_not_starve_newer_signals`).
