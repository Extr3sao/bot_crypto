# WP-ECONOMIC-RECOVERY-003 — Run report

**Estado:** completo. **Ningún resultado económico publicado ha cambiado.** El
verificador independiente da **14/14 PASS**.

| campo | valor |
| --- | --- |
| rama | `repro/economic-recovery-002` |
| commit bajo auditoría | `2bd6e346348ee7fc039f8ada31a390387a4c30c2` |
| fecha de medición | 2026-10-25 |
| Python | 3.11.15 (CPython, vía `uv`) |
| host | Windows 10 (10.0.26200), `core.autocrlf` activo por defecto |
| scripts añadidos | [`scripts/wp_eco003_audit.py`](../../../../scripts/wp_eco003_audit.py), [`scripts/wp_eco003_verify.py`](../../../../scripts/wp_eco003_verify.py) |
| artefactos | `DEPENDENCY_GRAPH.md`, `EVIDENCE_IMPACT_MATRIX.json`, `SOURCE_RECOVERY_ASSESSMENT.md`, `RECERTIFICATION_PLAN.md`, `INDEPENDENT_VERIFICATION.json`, `RUN_REPORT.*`, `FINAL_REPORT.md`, `evidence/` |

---

## 1. Comandos ejecutados y su resultado

| # | comando | salida | exit |
| - | ------- | ------ | ---- |
| 1 | `uv run python scripts/wp_eco003_audit.py` | `chain nodes: 18; pins: 21; drifting: 3`, `dependencies classified: 19` | 0 |
| 2 | `uv run python scripts/cost_barrier_gate.py --check` | `INTEGRITY_FAILURE (check mode)`, `checks 10/11 PASS`, `controls 6/6` | **5** |
| 3 | `uv run python -m pytest <4 suites de cost-barrier> -q --tb=line` | `19 failed, 74 passed` | 1 |
| 4 | `git worktree add --detach <tmp> 2bd6e346` + `cost_barrier_evidence.py --materialize` | `target_sha256 2437f446…` (= pin) | 0 |
| 5 | la misma suite de #3 en ese worktree | `9 failed, 84 passed` | 1 |
| 6 | `uv run python -m pytest tests -q` (suite completa, árbol) | `90 failed, 3270 passed, 31 skipped, 14 errors` → **104 nodos rojos** | 1 |
| 7 | `uv run python scripts/wp_eco003_verify.py` | `14/14 PASS` | 0 |
| 8 | `uv run ruff check` + `ruff format` sobre ambos scripts | `All checks passed!` | 0 |

Los comandos 3, 5, 6 se ejecutaron con `-p no:cacheprovider` para no dejar caché en el
árbol. Ninguno escribe en `src/`, `config/`, `data/` ni en evidencia publicada; el
verificador lo comprueba (`no_economic_or_runtime_file_changed`, `porcelain=''`).

### 1.1 La diferencia que importa (`#3` vs `#5`)

Diez de los 19 nodos rojos **no** son deriva de pines: son el input declarado ausente
(`reports/strategy-baseline/COST_BARRIER.json`, gitignoreado). Materializarlo desde la
copia de evidencia —bytes idénticos, `2437f446…`— cierra exactamente esos diez. Los 9 que
quedan son los pines caducados y el artefacto de checkout que codifican.

Esto reconcilia el número de WP-002 con el medido aquí: WP-002 midió el efecto *de su
reparación* sobre un árbol con el input materializado (donde sólo el nodo de precedencia
cambia de color), no el total de rojos de un checkout limpio.

---

## 2. Qué se midió, en una frase por tarea

1. **Grafo de dependencias** — 18 nodos, 21 pines, 3 desviaciones, 2 patologías de pin;
   cada nodo con productor, entradas, digests (bytes y LF) y consumidores derivados.
2. **Origen de los seis `MULTI_FAMILY_RESULTS_*.json`** — `git log --all` no devuelve ni
   un commit para `reports/strategy-baseline`; `.gitignore:55` los excluye. Sobrevive la
   matriz derivada (`3271a975`) y el baseline de `ema_crossover` (`21f78880`).
3. **Reconstruibilidad exacta** — **no** para las cinco familias sin baseline
   versionado: faltan corpus, digests, revisión del productor y entorno. Sí para
   `ema_crossover`, cuya fila se recomputa desde un fichero versionado.
4. **Qué cambiaría una recertificación** — 4 bundles/actas reescritos, 4 reconstruidos
   con payload idéntico (`4383d812…`), 9 fuera de alcance. Cero métricas económicas.
5. **Integridad vs economía** — la deriva es de procedencia: el único cambio de bytes en
   `config/` es el ancla reparada en WP-002 y su contenido semántico es idéntico.
6. **19 dependencias + 2 entregables** — 16 recuperables por re-ejecución, 1 exacta, 1 de
   host, 1 irrecuperable.
7. **El test de precedencia** — `test_a_missing_required_input_blocks_rather_than_fails`
   falla porque el gate evalúa integridad antes que bloqueo y la deriva del ledger es real.
   El mecanismo de bloqueo sigue intacto: se repara la deriva, no el test.
8. **Procedimiento mínimo** — 3 commits, 6 pasos, rollback por `git revert`, firma de
   éxito doble (93/93 verde **y** payload sin cambios).

---

## 3. Desviaciones y correcciones respecto de WP-002

| # | WP-002 dijo | medido en WP-003 | consecuencia |
| - | ----------- | ---------------- | ------------- |
| 1 | "un nodo preexistente cambia de verde a rojo" | 19 rojos en la suite de contrato sobre un checkout limpio; 10 son el input ausente, 9 la deriva | el diagnóstico de WP-002 era correcto **en su escenario** (input materializado) pero se leyó como si fuera el total |
| 2 | "dos entregables que nunca se commitearon" | 1: `reports/rfc046/IMPACT_ASSESSMENT.md` **sí** tiene productor (`scripts/rfc046_audit.py:732`) | cambia su clase a recuperable por re-ejecución |
| 3 | pin del ledger = "el del ledger con el ancla caducada" | el pin es el **render CRLF** de `ddaf14d1`; ningún blob tiene esos bytes | la recertificación debe fijar contenido, no bytes de una máquina (recomendación a WP-004) |
| 4 | el input del cost-barrier "no existe aquí" | no existe en su ruta, pero su copia es byte-idéntica y el materializador la restaura | el bundle **sí** es recertificable sin el corpus congelado |

Ninguna de estas correcciones revoca una conclusión de WP-002; ajustan alcance y causa.

---

## 4. Límites declarados

1. **No se regeneró nada publicado.** La simulación de recertificación se hizo en un
   clon temporal; de ella quedan las transcripciones en [`evidence/`](evidence/) y el
   registro de certificación simulado (`status CERTIFIED`, `exit 0`,
   `satisfies_full_certification true`).
2. **Las dos corridas completas no son comparables en total**: el árbol recolecta ~3405
   pruebas y el clon ~1982 (entorno distinto). Por eso la comparación es **por identidad
   de nodo**: 104 rojos antes, 85 después, `closed = 19`, `introduced = []`
   (`EVIDENCE_IMPACT_MATRIX.json` → `simulation.full_suite.set_difference`).
3. **85 nodos rojos preexistentes siguen ahí** y este WP no los arregla: 15 en
   `test_rfc035s3_strategy_closure.py`, 22 entre fallos y errores de
   `test_profitability_gate035.py`, 7 en `test_sprint024_stats.py`, etc. Ninguno es de
   cost-barrier.
4. **`reports/strategy-baseline/data/` no existe** (0 ficheros) y `data/raw/` está vacío:
   cualquier reconstrucción de la capa multi-familia es un experimento nuevo, prohibido
   aquí.
5. **No se ha habilitado nada**: `promotion_ready`, `rentable`, `certified` y
   `production_ready` siguen en `false` en el explorer publicado, y el gate lo comprueba
   en cada corrida (`artifact:explorer_governance_flags_unchanged`).

---

## 5. Reproducir este WP

```bash
uv run python scripts/wp_eco003_audit.py          # ~10 s, escribe EVIDENCE_IMPACT_MATRIX.json
uv run python scripts/cost_barrier_gate.py --check # exit 5 esperado
uv run python scripts/wp_eco003_verify.py         # 14/14 PASS, exit 0
```

Las transcripciones de test en `evidence/` se generaron con:

```bash
uv run python -m pytest tests/unit/research/test_cost_barrier_explorer.py \
  tests/unit/research/test_cost_barrier_gate.py \
  tests/unit/research/test_cost_barrier_adversarial.py \
  tests/unit/research/test_cost_barrier_ci_parity.py -q --tb=line -p no:cacheprovider
uv run python -m pytest tests -q --tb=no -rfE -p no:cacheprovider
```
