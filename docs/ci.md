# Integración Continua (CI Baseline)

> Runbook rápido de los quality gates que CI aplica en cada PR y en cada
> push a `main`. Salida del comando SDD `03-specify.md` para
> **TSK-008 (Baseline de calidad, sprint-002 Pri 1)**. Aplica a todo el
> repo hasta que la metodología introduzca gates adicionales.

---

## 1. Propósito

Garantizar la inmutabilidad de los quality gates del proyecto (lint,
formato, tipos, tests, auditoría de CVEs, cobertura mínima). Detener
regresiones tempranas antes de merge.

## 2. Herramientas y triggers

- **Runner**: GitHub Actions sobre `ubuntu-latest`.
- **Triggers**: `on: push: branches: ["main"]` y
  `on: pull_request: branches: ["main"]`.
- **Gestor de dependencias**: `uv` (ADR-0002).
- **Versión de Python**: anclada vía `.python-version` (3.11),
  alineada con `requires-python = ">=3.11"` y `target-version = "py311"`
  en `[tool.ruff]`.
- **Action principal**: `astral-sh/setup-uv@v3` con cache nativo sobre
  `uv.lock` (evita usar la lenta cache de pip en Ubuntu).

## 3. Jobs & gates

| Job                       | Comando                                                              | Fail-criterion                                |
| ------------------------- | -------------------------------------------------------------------- | --------------------------------------------- |
| Format check              | `uv run ruff format --check .`                                       | Cualquier drift de formato.                   |
| Lint                      | `uv run ruff check .`                                                | Hallazgos E/F/W/I/B/UP/SIM/RUF.               |
| Type check                | `uv run mypy .`                                                      | Cualquier error de tipo en strict mode.       |
| Security audit            | `uv export --all-extras --no-hashes > reqs.txt` + `uv run pip-audit -r reqs.txt` | Cualquier CVE crítico/alto.           |
| Tests + coverage          | `uv run pytest -m "not slow and not market" --cov --cov-fail-under=90` | Failures o cobertura por debajo del 90%. |

Los markers `slow` y `market` se excluyen de la validación rápida de PRs
para mantener el feedback < 5 minutos. Nightly CI (pendiente) correrá
la suite completa con esos markers incluidos.

## 4. Cómo debuggear fallos de CI en local

Replicar localmente al 100% el pipeline:

```bash
# Setup (asume uv instalado y `.python-version` presente)
uv sync --all-extras --dev

# Format + lint
uv run ruff format --check .
uv run ruff check .

# Type check
uv run mypy .

# Auditoria
uv export --all-extras --dev --no-hashes > reqs.txt
uv run pip-audit -r reqs.txt

# Tests + cobertura
uv run pytest -m "not slow and not market" --cov --cov-fail-under=90
```

Si algún comando falla en local, CI fallará idénticamente. Antes de
empujar un PR, asegúrate de que los 5 jobs pasan en tu shell.

## 5. Caveats y razones

- **Cobertura subida de 70 a 90**: pinear la calidad desde el primer
  PR. Si necesitas una excepción (código de infra con baja cobertura
  justificada), abrir ADR firmada en `tasks/decisions.md`.
- **Markers excluidos**: `slow` y `market` excluidos por latencia. Las
  estrategias live deben tener unit tests rápidos que SI entren al
  pipeline; cualquier gate adicional de aceptación queda en nightly.
- **`uv` como gestor (ADR-0002)**: el cache nativo de
  `astral-sh/setup-uv@v3` evita usar la lenta cache de pip.
- **Pin de Python 3.11**: corresponde a `requires-python = ">=3.11"`
  del `pyproject.toml`. Cualquier bump de Python requiere ADR.

## 6. Trampas detectadas y fixes anticipados

- **`mypy python_version` en `pyproject.toml` está fijado a "3.14"**.
  Python 3.14 NO existe como estable (a fecha de cierre de sprint-001)
  así que mypy strict no podría correr. El spec lo baja a "3.11" para
  alinear con `requires-python`. Cambio en bloque con TSK-008.
- **`coverage fail_under = 70` está flojo**: el repo cerró TSK-099 con
  95% real. Pinear 90% desde el inicio es razonable y baja el coste
  futuro de subir la barra.
- **Falta `.python-version`**: sin este archivo, ruff + mypy + GHA
  pueden divergir sobre qué versión exacta de Python interpretan. El
  spec introduce el archivo (single line `3.11`).

## 7. Pendiente post-TSK-008 (no objetivo de este ticket)

- **TSK-009 candidate**: CODEOWNERS + PR template + branch-protection
  admin rules.
- **Nightly CI suite completa** con markers `slow` y `market`.
- **PR template** que referencie este spec directamente.
- **Security-reviewer** firma el secret-audit antes de aprobar el
  primer PR disparado por este CI.

## 8. Salidas esperadas del comando SDD `03-specify.md`

- Este documento (`docs/ci.md`) como spec/runbook principal.
- Diagrama de la pipeline en `docs/architecture.md` (en sección
  dedicada a Fase 0/Fase 1).
- Cuando se implemente el workflow: `.github/workflows/ci.yml` que
  encaje con la sección 3 de este documento.
