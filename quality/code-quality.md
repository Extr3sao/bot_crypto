# Code Quality Gates

> Estándares que toda PR debe cumplir para fusionarse.

---

## 1. Estilo y formato

- **Ruff**: `ruff check .` debe pasar sin warnings.
- **Ruff format**: `ruff format --check .` debe pasar.
- Línea máxima: 100 (`pyproject.toml`).
- Imports ordenados automáticamente por Ruff.

## 2. Tipos

- **Mypy strict**: `mypy src/trading_bot`.
- Prohibido `Any` salvo en bordes explícitamente documentados.
- `disallow_untyped_defs = true`.
- Tests también tipados.

## 3. Tests

- `pytest -m "not slow" -q` en verde.
- Coverage ≥ 70% global; ≥ 90% en `risk`, ≥ 85% en `indicators`
  y `execution`.
- Property tests con `hypothesis` para módulos cuantitativos.

## 4. Archivos prohibidos

- No commits de `.env`, `*.pem`, `*.key`.
- No commits con secretos en código.
- No commits con código comentado largo (> 10 líneas).

## 5. Documentación

- Funciones públicas: docstring (estilo Google o NumPy — definir ADR).
- Cualquier cambio de comportamiento externo actualiza:
  - BDD (`bdd/features/`).
  - spec (`docs/architecture.md` o doc dedicado).
- Cualquier nueva dependencia actualiza:
  - `pyproject.toml`.
  - `context/dependency-map.md`.
  - ADR.

## 6. Mensajes de commit

- Formato: `[TSK-NNN] <descripción corta>` cuando aplique.
- Mensajes en imperativo.
- Footer: cuando aplique, referencia al ticket (`Refs TSK-NNN`).

## 7. CI

- Pipeline mínimo:
  1. Setup.
  2. `ruff check .`
  3. `ruff format --check .`
  4. `mypy src/trading_bot`
  5. `pytest -m "not slow"`
  6. `safety check`
  7. `pip-audit` (opcional)

- Cualquier fallo bloquea merge.
- Reportes se guardan en `reports/ci/<commit>.md`.
