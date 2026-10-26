# RUN_REPORT — WP-ECONOMIC-BLOCKER-001

Registro de ejecución. Los números viven en
[`RUN_REPORT.json`](RUN_REPORT.json); esta página es su lectura humana.

- Commit medido: `e67194e79a42` (`audit/economic-blocker-001`), Python 3.11.15.
- `src/`, `tests/`, `config/` **sin modificar**: el WP es auditoría, no cambio de
  comportamiento (verificado en `INDEPENDENT_VERIFICATION.json`, check
  `E1_no_runtime_config_or_code_was_modified`).

## Comandos y resultados

| comando | exit | resultado observado |
| --- | ---: | --- |
| `uv run python scripts/wp_eco001_admission_audit.py` | 0 | 24 entradas clasificadas; el builder reproduce el ledger |
| `uv run python scripts/wp_eco001_cost_audit.py` | 0 | 24/24 bloques de coste recomputados (Δ ≤ 5,0e-09 bps); V4 re-derivado |
| `uv run python scripts/wp_eco001_economics.py` | 0 | matriz de 24 filas; 0 netas positivas |
| `… --phase working` | 0 | pytest del árbol: 89 failed / 1845 passed / 14 errors (exit 1 capturado dentro) |
| `… --phase clean` | 0 | checkout limpio (`git archive HEAD`): 110 failed / 1824 passed / 14 errors; import propio verificado |
| `… --phase healthy` | 0 | 447 passed, exit 0 |
| `… --phase assemble` | 0 | fallos del árbol ⊆ fallos del checkout limpio; 21 fallos sólo en limpio |
| `uv run python scripts/wp_eco001_verify.py` | 0 | 27 PASS · 0 FAIL · 1 defecto declarado |
| `uv run ruff check scripts/wp_eco001_*.py` | 0 | All checks passed |
| `uv run python scripts/build_strategy_admission.py --check` | **1** | `ADMISSION_LEDGER_STALE` — el defecto declarado, reproducido |

El baseline se ejecutó por fases (`--phase working|clean|healthy|assemble`) porque
las tres corridas de pytest juntas superan el límite de tiempo de una sola
llamada. Partir el trabajo **no** cambia lo medido: cada fase es el mismo pytest
con la misma selección, y las salidas crudas quedan en
[`baseline_parts/`](baseline_parts).

## Artefactos

| fichero | bytes | sha256 (prefijo) |
| --- | ---: | --- |
| `STRATEGY_ADMISSION_AUDIT.json` | 30337 | `167ac5a6ded6` |
| `STRATEGY_ADMISSION_AUDIT.md` | 10331 | `324ab6a3f3bd` |
| `COST_MODEL_AUDIT.json` | 21947 | `8f6c5b3ecdcc` |
| `COST_MODEL_AUDIT.md` | 7306 | `c94a037a2822` |
| `COST_OBSERVED.json` | 44496 | `8e2409275fe3` |
| `STRATEGY_ECONOMICS_MATRIX.csv` | 7946 | `fff39cfb4a51` |
| `STRATEGY_ECONOMICS.json` | 7216 | `8c3234936652` |
| `TEST_BASELINE_COMPARISON.json` | 48709 | `004a5b9651ef` |
| `TEST_BASELINE_COMPARISON.md` | 4571 | `086cdc8d2aff` |
| `FINAL_REPORT.md` | 10295 | `06f5672512bd` |

Los hashes son los del fichero en el momento de refrescar el manifiesto
(`uv run python scripts/wp_eco001_manifest.py`); cualquier regeneración los
invalida, y ese es el punto. Tres artefactos no llevan hash aquí, por
construcción: `RUN_REPORT.json` (el manifiesto, que estaría hasheándose a sí
mismo), `RUN_REPORT.md` (esta misma tabla) e `INDEPENDENT_VERIFICATION.json` (lo
escribe el verificador *después* del manifiesto). Los tres se hashean desde el
propio fichero.

## Resultado en cinco líneas

1. `paper_candidates = []` en la matriz de admisión: el builder **no puede**
   emitir `PAPER_CANDIDATE`. No es un fallo de evaluación, es el estado del artefacto.
2. 18 de 24 entradas declaran `sample_trades = 0`.
3. Coste real 22,79 bps (BTC) a 23,79 bps (SOL); **20 bps son comisiones KNOWN**.
4. Mejor bruto medido: **+8,91 bps** (`volatility@30m`, sin muestra publicada) →
   neto **−13,88 bps**; ignorando slippage e impacto, **−11,09 bps**.
5. Fallos de tests: 103 nodos preexistentes (todos fallan también en checkout
   limpio) y 21 que **sólo** fallan en limpio por depender de artefactos no
   versionados. Ninguno es regresión de este WP.## Defectos declarados

1. `PROVENANCE_ANCHOR_STALE` — el SHA-256 que el ledger registra para
   `docs/STRATEGY_ADMISSION_MATRIX.json` no coincide con el fichero ni con ninguna
   revisión commiteada; `build_strategy_admission.py --check` sale 1. Impacto:
   cadena de auditoría, no comportamiento (el runtime lee estados, no hashes). No se
   repara aquí porque el remedio toca `config/`, el artefacto bajo auditoría.
2. `TEST_SUITE_WRITES_TRACKED_DATA` — `tests/unit/research/test_rfc047_windows_evidence.py`
   y `test_st6_scheduler.py` reescriben el fichero **versionado**
   `data/st6/RFC047_RUNTIME_VERIFICATION.json` al ejecutarse (92 líneas cambiadas al
   correr la suite). Restaurado a `HEAD` tras la medición, para que el WP no deje
   efectos laterales. Es parte de por qué un verde local no es evidencia reproducible.

## No evaluado (declarado, nunca PASS)

Rentabilidad futura · ejecución real desde señales · `PAPER_RUNTIME_VALIDATED` ·
coste como distribución por régimen · fills reales.
