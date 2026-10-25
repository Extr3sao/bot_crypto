# INTEGRATION PLAN — rebanada de 47 rutas, no la lane

## 1. Alternativas evaluadas

### A · fusionar `codepaper/supervisor-001` en `main`

- `git merge-tree --write-tree main codepaper/supervisor-001` → **exit 0, 0 conflictos**,
  árbol `1053827…`, **1 804 ficheros, +1 660 730/−172** (`evidence/MERGE_TREE_lane.txt`).
- Con el RFC: árbol `1a2f60b…`, 2 012 ficheros, también 0 conflictos.
- **Descartada.** No por conflicto, por contenido: 1 248 rutas de informes, 450 `.py` de
  investigación y un test heredado roto entran sin que nada obligue a mirarlos. Un merge que no
  discute nada es el que hay que temer.

### B · integrar por componentes funcionales

- Requiere que la lane esté particionada por componentes. **No lo está**: 69 % de sus rutas son
  informes y los scripts de investigación comparten `src/trading_bot/research/` con el runtime.
- **Descartada por falta de frontera**, no por coste: no hay corte que se pueda defender.

### C · migrar el runtime mínimo ← **elegida**

- 42 ficheros de código + 2 de config + `matplotlib` en `pyproject.toml` y `uv.lock`, aplicados
  sobre `main` desde `3b758e22` (o `fda95664` para incluir el arreglo de lock del RFC).
- Medido en worktree desechable: `uv sync --frozen` 0 · imports OK · **5 entry points `--help`
  exit 0** · **sesión PAPER real completa** (`STOP_COMPLETED`, 1 ciclo, `live_orders 0`) ·
  `tests/unit/paper tests/unit/risk`: **6 failed / 170 passed**, de los cuales **4 son tests
  que la lane actualizó** y **2 son una regresión heredada** que también falla en la lane.
- Coste: **una sesión de trabajo** para las 47 rutas, más las tres puertas de §3.

## 2. Orden de integración

Cada paso en su rama, con su commit; nada se aplica dos veces.

| # | Paso | Contenido | Por qué en este orden |
| --- | --- | --- | --- |
| 1 | **Contrato de riesgo** | decisión sobre `test_futures_independent_verifier.py` ×2 (`risk/manager.py`, `defensive_blocks.py`) | es lo único que hoy está en rojo y lo único que exige firma ajena; bloquea la aceptación |
| 2 | Dependencia | `matplotlib>=3.8,<4.0` en `pyproject.toml` + `uv.lock` regenerado (el del RFC ya lo tiene) | sin esto el import falla antes de cualquier otra cosa |
| 3 | `ops/` (5) | `ops/{__init__,paper_supervisor,session_status,single_writer,windowless}.py` | paquete nuevo, sin consumidores previos: riesgo nulo |
| 4 | `vision/` (14) + `minute_collector` | cadena de decisión y fuente de datos | también nuevos en `main` |
| 5 | `research/economic_recovery/*` (6) + `equity_drawdown` | economía del ciclo | nuevos; `costs.py` es el que el grafo omitía |
| 6 | 7 modificados | `paper/*`, `risk/manager.py`, `autonomous/contracts.py`, `start_paper_trading.py` | el riesgo real; va después de que todo lo nuevo exista, y con el paso 1 ya decidido |
| 7 | Scripts (7) + config (2) | entry points y `vision.yaml`, `strategy_candidates_edge15.json` | último: nada los importa hasta aquí |
| 7-bis | `.gitignore` | excepciones para `reports/ai-bots/TAP-SUPERVISOR-INTEGRATION-001/` (y el resto que se quiera versionar) | sin regla, `reports/*` sigue excluido y la evidencia no entra: el commit sale «verde» y sin informes |
| 8 | Tests | los 4 tests que la lane actualizó + tests de `ops`/`vision`/campaña | viajan con el código que prueban, en el mismo commit |
| 9 | (opcional) RFC `REPRO-001` | `repro/paper-admission-001` sobre la rebanada | ya no depende de una lane ajena |

## 3. Las tres puertas (sin ellas no hay `READY`)

1. **G1 · Contrato de riesgo** — el risk-manager decide si los 28 checks nuevos por decisión son
   el contrato. Si sí: el test heredado se actualiza en el mismo commit, con su justificación.
   Si no: se corrige `manager.py`. *Nadie más puede cerrar esta puerta.*
2. **G2 · Verificador de campaña real** — hoy ningún verificador juzga una campaña producida por
   el propio productor: el de lock la rechaza por esquema
   (`UNSUPPORTED_CAMPAIGN_SCHEMA`) y el de supervisor la rompe buscando
   `scenarios/SCENARIOS.json`, que solo tiene el fixture. Sin esto, "campaña PAPER real
   verificada" no existe y B4 sigue abierto.
3. **G3 · B1 con reproducción determinista** — 8 corridas hoy sin fallo no son un arreglo. O se
   reproduce la carrera, o se documenta el contrato del lock y se prueba con un punto de
   intercepción.

## 4. Tests necesarios

- **De la rebanada**: `tests/unit/paper`, `tests/unit/risk`, `tests/unit/ops` (nuevo),
  `tests/unit/vision` (nuevo), `tests/unit/research/test_rfc035_strategy_admission.py`.
- **De regresión de `main`**: los 6 que hoy fallan; 4 se actualizan con el paso 1/8, 2 con G1.
- **De comportamiento, no de unidad**: una sesión PAPER real acotada (`duration-s 60`,
  `max-cycles 1`, `--window-bars 20` mínimo, `warmup-minutes 25`) que debe terminar
  `STOP_COMPLETED` con ≥1 ciclo y `live_orders 0`; y una campaña con `--crashes 1` que debe
  terminar `RECOVERED` con cadena `INTACT`.
- **De la puerta G2**: el verificador debe aceptar la campaña real y seguir detectando las 12
  mutaciones del fixture (no se cambia el fixture para que pase).

## 5. Criterios de aceptación

| Criterio | Comando | Umbral |
| --- | --- | --- |
| Build reproducible | `uv sync --frozen` en clon nuevo | exit 0, `matplotlib` importable |
| Lock consistente | `uv lock --check` | exit 0 |
| Sin regresión | `pytest tests/unit/paper tests/unit/risk` | **0 failed** |
| Runtime alcanzable | `--help` de los 5 entry points | exit 0 los 5 |
| Sesión real | `paper_supervisor.py … --max-cycles 1` | `STOP_COMPLETED`, ≥1 ciclo, `live_orders 0` |
| Campaña real | `paper_supervisor_campaign.py run --crashes 1` | `RECOVERED`, cadena `INTACT`, `locks []` |
| Campaña verificable | verificador sobre la campaña real | PASS con 0 `false_success` (G2) |
| Alcance | `git diff --name-only main` | solo las 47 rutas + tests |
| Admisión | ledger byte-idéntico | sigue `NO_GO` |

## 6. Rollback

- La migración entra como **un merge commit** (o una serie de commits por paso) sobre `main`;
  revertir es `git revert -m 1 <merge>` — sin migraciones de datos, sin cambios de ledger, sin
  estado externo.
- Los 2 ficheros de config son **aditivos**; los 7 modificados se revierten con el mismo commit
  que los introdujo.
- Criterio de abortar: si `pytest tests/unit/paper tests/unit/risk` no llega a **0 failed**
  después de G1, o si la sesión real no completa un ciclo, se revierte el paso 6–7 y se queda la
  parte nueva (pasos 3–5), que no tiene consumidores y por tanto no puede romper nada.

## 7. Primer work package (una sola finalidad)

> **WP-01 — Decidir el contrato de riesgo y dejar en verde `test_futures_independent_verifier`.**

Por qué este y no el código: es lo único que hoy está roto, es lo único que no puedo decidir yo,
y sin él cualquier migración nace con dos tests en rojo — que es exactamente la forma de
`FALSE_SUCCESS` que este proyecto ya pagó una vez.

Entregable: un commit con (a) la decisión escrita, (b) el test y/o el `manager.py` coherentes,
(c) la salida de `pytest tests/unit/risk` en verde, (d) la evidencia de que el patrón de checks
nuevo es intencionado y no un efecto colateral de otro cambio.

## 8. Estado de los bloqueos B1–B4 (sin falsear)

| Bloqueo | Estado tras esta auditoría | Evidencia |
| --- | --- | --- |
| **B1** `LOCK_UNATTRIBUTED` | **no reproducido** (8 corridas, 0 fallos); sigue abierto | `evidence/PYTEST_b1_isolated.log`, `evidence/PYTEST_lane_ops_run1.log` |
| **B2** `verify_claims.py` no portable | sin cambios, no reauditado | — |
| **B3** `uv sync --frozen` | **descripción corregida**: detecta dependencias *añadidas* (exit 1), pero **no** las que el lock omite: instala el lock y desinstala lo declarado (exit 0, medido). Sigue abierto | `evidence/BASELINE_uv_sync_frozen` del RFC: `- matplotlib==3.11.2`, `EXIT=0` |
| **B4** sin campaña real | **parcialmente cerrado**: existe una campaña real reproducible (`RECOVERED`, 5 ciclos, `live_orders 0`); sigue abierto porque **ningún verificador la juzga** (G2) | `evidence/REAL_CAMPAIGN_*.json` |
