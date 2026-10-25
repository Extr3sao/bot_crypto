# G-6 — Run report

**Run:** `run-20261025T141859Z-G-6`  
**Fecha:** 2026-10-25  
**Implementación:** `66e96e1685226508e4c03a1ea2771aecf878f5b5`  
**Rama:** `audit/mt0004-negative-controls`  
**Plataforma:** Windows-10-10.0.26200-SP0, Python 3.11  
**Veredicto:** `G6_VERIFIED` · 17/17 · `FALSE_SUCCESS=0`

## 1. Comandos y exit codes

| Comando | Exit | Resultado |
|---|---:|---|
| `python scripts/audit/g6_crash_e2e.py --out docs/audit/runs/run-20261025T141859Z-G-6` | 0 | 9 escenarios, 4 kills reales, `evidence.json` |
| `python scripts/audit/verify_g6.py --rev 66e96e16 --out .../verification.json` | 0 | `G6_VERIFIED`, 17/17 |
| `python -m pytest tests/unit/paper/test_paper_recovery.py -q` | 0 | 16 passed |
| `python -m pytest tests/unit/paper tests/integration/test_paper_e2e_001.py ... tests/unit/autonomous tests/unit/test_app_cli_contract.py -q` | 0 | 521 passed |
| `python -m pytest tests/integration/test_g5_paper_end_to_end.py tests/unit/test_live_gate_enforcement.py tests/unit/test_live_hot_stop_coverage.py -q` | 0 | 79 passed |
| Regresión amplia (paper, autonomía, riesgo, scanner, app, E2E paper, G-5) | 1 | **840 passed, 2 failed** (preexistentes) |
| `pytest tests/unit/risk/test_futures_independent_verifier.py` en export `0bc8a926` | 1 | 2 failed, 6 passed (misma baseline) |
| `pytest tests/unit/observability/test_vision_panel.py` en `HEAD` y `0bc8a926` | 2 | Error de colección: módulo ausente |
| `ruff check` sobre ficheros G-6 | 0 | PASS |
| `mypy` sobre módulos G-6 | 0 | PASS |
| `sha256sum src/trading_bot/autonomous/hot_stop.py` | 0 | `76cfca23…` (sin cambios) |

La regresión amplia se ejecutó con:

```text
tests/unit/paper tests/unit/autonomous tests/unit/risk tests/unit/scanner
tests/unit/test_app_demo.py tests/unit/test_app_cli_contract.py
tests/integration/test_paper_e2e_001.py
tests/integration/test_paper_e2e_002.py
tests/integration/test_paper_e2e_003.py
tests/integration/test_g5_paper_end_to_end.py
```

Resultado: `2 failed, 840 passed in 87.45s`.

## 2. Evidencia de crash

Cada escenario `before_intent`, `after_intent`, `after_order` y
`after_accounting` tiene:

- PID del wrapper (`Popen`) y PID real del worker (marker);
- comando de kill (`taskkill /F /T /PID …`), exit code del kill y exit code del
  worker;
- marker con punto, PID y timestamp;
- hash y tamaño del estado durable justo después del kill;
- log completo del worker;
- reinicio en un proceso distinto con su propio PID, comando y resultado.

Los detalles están en `evidence.json` y en `CRASH_MATRIX.md`.

## 3. Verificación independiente

`scripts/audit/verify_g6.py`:

1. exporta el commit con `git archive`;
2. ejecuta `g6_crash_e2e.py` dos veces desde el export;
3. compara una proyección sin PIDs/timestamps/hashes;
4. re-deriva 17 checks desde el JSON;
5. comprueba `hot_stop.py`, `LIVE_NO_GO` y los commits de G-5.

Resultado: `G6_VERIFIED`, 17/17, `false_success=0`, dos ejecuciones
deterministas (26,06 s y 25,22 s en la verificación inicial; 58,91 s total).

## 4. Defectos y límites

### 4.1 Fallos preexistentes

`tests/unit/risk/test_futures_independent_verifier.py`:

- `test_verifier_reproduces_a_real_approval`
- `test_executed_artifacts_verify_when_present`

Ambos fallan igual en el export limpio de `0bc8a926`: 2 failed, 6 passed. El
detalle es `bracket_provenance` contra el fixture de `data/rfc048`; no toca el
runtime PAPER ni G-6. No se han corregido ni declarado resueltos.

`tests/unit/observability/test_vision_panel.py` no colecta porque
`trading_bot.observability.vision_panel` no existe; se reproduce igual en
`0bc8a926`. Se reporta como bloqueo de colección, no como PASS.

### 4.2 Límites de G-6

- Datos sintéticos y ledger `CONTROLLED_TEST_FIXTURE`: recorrido y seguridad,
  no edge.
- El kill es real, pero el reinicio usa el mismo disco.
- No se implementa LIVE, no se usan credenciales, no se construye ningún
  cliente de exchange.
- `paper_cycle` y `autonomous.decision` siguen separados.
- El launcher autónomo `scripts/autonomous_paper.py` conserva su persistencia
  por sesión; G-6 mide el runtime canónico de `PaperSessionRunner`.
- Verificación `PROCEDURALLY_SEPARATED`, no segunda persona.

## 5. G-5: commit definitivo

- Código G-5: `05b361f7bd26a4fb9d470d9ba5c68d7f967846c9`.
- Evidencia G-5 definitiva: `12267039`.
- `180e02b3` fue sustituido por un amend tras corregir una frase de
  `PAPER_END_TO_END.md` y regenerar `EVIDENCE.sha256`; el código no cambió.
- El verificador comprueba que `05b361f7` y `12267039` existen, son ancestros de
  `HEAD` y que el manifiesto de G-5 tiene 33 entradas.

## 6. Estado final

`LIVE_NO_GO` y `PRODUCTION_READY = false`. G-6 queda cerrado en alcance PAPER.
El siguiente objetivo es activar estrategias elegibles en el runtime PAPER con
datos de mercado reales y trazables.
