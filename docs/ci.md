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

### Gate adicional (no required): cost-barrier drift

- **Workflow**: `.github/workflows/cost-barrier-gate.yml` (no forma parte
  de los 4 status-checks required de Bloque 6; aparece como job independiente).
- **Disparadores**: `push`/`pull_request` a `main` que toquen cualquiera de las
  dependencias que declara el gate -el ledger de admision, el modelo de coste y
  su documento, la auditoria WP-3 y su productor, el explorador, su verificador,
  el gate, el bundle de evidencia, los tests de contrato- o el propio workflow;
  tambien `workflow_dispatch`. El contrato de activacion lo comprueba el propio
  gate (`ci:activation_contract_covers_every_declared_input`): si una dependencia
  se mueve a una ruta que el filtro no cubre, el gate lo nombra.
- **Materializacion**: el input generado
  `reports/strategy-baseline/COST_BARRIER.json` es gitignored por diseno (sus
  propios datos de barras tampoco viajan en el repo), asi que el checkout lo
  materializa desde la copia de evidencia
  `data/recovery/wp7/evidence/COST_BARRIER.json`, que debe reproducir el sha256
  que el artefacto publicado registro en su `sources[]`. Si no coincide, el paso
  falla visiblemente y el gate queda en `BLOCKED_MISSING_INPUT` -nunca en PASS-.
  Un ensayo sobre un `git worktree` limpio descubrio que el bundle era
  inverificable fuera de la maquina que lo escribio: los productores estaban
  pinados por los bytes de ese arbol, cuyos finales de linea reescribe el checkout,
  asi que el manifiesto pina ahora las formas de contenido LF y CRLF
  (`sha256_lf` / `sha256_crlf`) y `sha256` queda como informacion.
- **Comandos**: `uv run python scripts/cost_barrier_evidence.py --materialize
  --json` -> `uv run python scripts/cost_barrier_gate.py --json --report ...` ->
  `uv run python scripts/cost_barrier_adversarial.py --out ... --report ...` ->
  `uv run python scripts/cost_barrier_certify.py --json --out ...`; la evidencia
  se conserva como artifact (`if: always()`, `if-no-files-found: error`) y ningun
  paso lleva `continue-on-error`.
- **Estados y exit codes**: `FULL_REPRODUCTION_PASS` (0), `CHECK_ONLY_PASS` y
  `CHECK_ONLY_WITH_ADVISORIES` (2, parcial), `BLOCKED_MISSING_INPUT` (3),
  `FULL_REPRODUCTION_FAIL` (4), `INTEGRITY_FAILURE` (5). Solo el primero satisface
  un requisito de certificacion completa: una comprobacion parcial no puede
  promover estrategias ni certificar resultados economicos.
- **Fail-criterion**: cualquier numero publicado que deje de reproducirse
  (`<path>: <publicado> -> <fresco>`), un self-hash que no recomputa, una
  atestacion rota, una bandera de gobernanza que cambie, un input citado cuyo
  contenido derive (obliga a regenerar y re-verificar), un productor fuera del
  manifiesto, un input requerido sin materializar, un ataque adversario que
  escape o controles propios fallidos. Una diferencia LF/CRLF no es drift -se
  informa como advisory con el fichero y la convencion-; un input generado ausente
  es advisory en `--check` (falla con `--strict`) y bloqueo en modo completo.
  Un sweep adversario sin su sustrato materializado se declara `NOT_EVALUABLE`
  (exit no cero) y no cuenta como evidencia de deteccion: sin el input, todo
  ataque que exige un fallo de reproduccion degenera en "el gate ya estaba
  bloqueado" y un 17/17 obtenido asi no significaria nada.

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

# Gate de drift del cost-barrier (WP-6/WP-7): reproduccion completa local
uv run python scripts/cost_barrier_evidence.py --materialize --json
uv run python scripts/cost_barrier_gate.py --json
uv run python scripts/cost_barrier_adversarial.py --out .ci/ADVERSARIAL.json
uv run python scripts/cost_barrier_certify.py --json

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
