# Command 07 — Evaluate

## Objetivo
Ejecutar la **evaluación completa** del cambio: tests, lint, tipos,
revisión de riesgo y de seguridad, revisión de documentación.

## Agente(s) responsable(s)
- Cualquier agente técnico + `risk-manager` + `security-reviewer` + CI.

## Entradas
- PR / commit a evaluar.
- Cambios en `src/`, `config/`, `docs/`, `tests/`, `bdd/`, `.ai/`.

## Salidas
- Reporte de evaluación en `reports/ci/<commit>.md` con:
  - `ruff` status.
  - `mypy` status.
  - `pytest` (unit, integration, regression).
  - Cobertura.
  - BDD escenarios que pasan.
  - Findings de riesgo y seguridad.

## Pasos
1. `ruff check .` y `ruff format --check .`.
2. `mypy src/trading_bot`.
3. `pytest -m unit` y `pytest -m integration` si los tests no son lentos.
4. Cobertura (`pytest --cov`).
5. Risk-manager verifica tamaño de cambios en `risk/*` y `config/risk.yaml`.
6. Security-reviewer verifica secretos y dependencias.
7. BDD: ejecutar los features afectados (cuando estén implementados).

## Criterio de finalización
- Todos los checks verdes.
- Coverage ≥ 70% (`pyproject.toml`).
- Cualquier fallo bloquea merge.

## NO
- No fusionar con checks en rojo.
- No saltarse la cobertura con "lo arreglo en el siguiente PR".
