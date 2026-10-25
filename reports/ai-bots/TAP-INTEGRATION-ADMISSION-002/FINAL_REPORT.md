# FINAL REPORT — TAP-INTEGRATION-ADMISSION-002

**Worktree:** `C:/Users/GVLLFR0035/Downloads/ff-wt-adm002`
**Branch:** `admission/integration-002` @ `55f991b7` — 10 commits ahead of `main`, 0 behind, 0 merges
**Base audited:** `main` = `e67194e7` (untouched; verified before and after by the independent verifier)
**Date (UTC):** 2026-10-25

## 0. The six verdicts

| Pregunta | Estado | Base |
| --- | --- | --- |
| Gate de integración | **PASS** | `GATE_REPORT.json` `verdict PASS` en `9a420ff1`, 15/15 pasos; re-verificado por el verificador independiente (9/9 claims) |
| GitHub Actions | **NOT_EXECUTED** | el workflow no existe en `origin/main` y no está registrado en la API de Actions (`/runs` → 404; 3 workflows registrados, ninguno es éste) |
| Required check | **NOT_ENFORCED** | el propio workflow se declara voluntario; `GET .../branches/main/protection` → **401** sin credenciales ⇒ `GOVERNANCE_BLOCKED` |
| G1 (veto semanal de pérdida) | **OPEN** | firma del risk-manager pendiente; el gate se niega a firmar política de riesgo |
| Paper admission | **NO_GO** | 0 estrategias admitidas de 24 (A5); sesión PAPER real ejecutada y juzgada, sin fills |
| Bloqueos automáticos resueltos | **2 de 6** | B5 (evidencia invisible para git) y B6 (verificador que no miraba `cycles_blocked`) cerrados en esta entrega; B1–B4 necesitan firma, admin, push o investigación |

`FALSE_SUCCESS = 0` · `BUILDER != VERIFIER` (el verificador es un script separado, `evidence/ADMISSION_VERIFICATION.json`, `false_success: 0`).

## 1. Commits y ramas auditados

| Ref | Commit | Rol |
| --- | --- | --- |
| `admission/integration-002` (HEAD) | `55f991b7` | esta auditoría; 10 commits sobre `main` |
| `gate/integration-001` | `55f991b7` | misma punta: la rama del gate es la base de esta entrega |
| delivery del gate | `680c34df` | commit de la entrega (report, review, baseline) |
| árbol certificado por las campañas | `9a420ff1` | commit sobre el que corrieron las dos campañas |
| `main` / `origin/main` | `e67194e7` / `5e6f9632` | `origin/main` es **ancestro**: 263 commits por detrás del `main` local |
| lane auditada | `audit/supervisor-integration-001` = `3b758e22` | origen del slice migrado |

**Conflictos con la rama de integración prevista (`main`):** `git merge-tree --write-tree main HEAD` sale **0 con lista de conflictos vacía** y 524 ficheros de diferencia (mayoría `reports/`). Fusionar no produce conflictos; **no se fusionó ni se tocó `main`** (§ regla de encargo).

**Estabilidad de la certificación:** `9a420ff1..HEAD` toca **sólo** `reports/ai-bots/TAP-INTEGRATION-GATE-001/**`. Ningún fichero de `src/`, `scripts/` o `tests/` cambió después de que las campañas corrieran, de modo que la evidencia de `9a420ff1` describe el árbol ejecutable que hay hoy; el verificador comprueba el commit y el manifiesto (A3), no sólo el exit code.

## 2. Qué parte de la lane de 301 commits hace falta

`ROUTE_MANIFEST.json` (TAP-SUPERVISOR-INTEGRATION-002) resolvió la lane por **clausura de imports**, no por ancestría: de las 301 commits se tomaron **84 rutas** — 67 ficheros `MISSING`, 13 `DIFFERS`, 4 `IDENTICAL` — agrupadas en 47 rutas de código/configuración y 37 tests. El runtime de esta rama importa **338 módulos** con **2.435 imports de `trading_bot`** y **0 sin resolver** (A7). Conclusión: los 301 commits no son un requisito; el requisito es esa clausura, ya migrada, y lo que falta de la lane no entra en el runtime actual.

## 3. Gate de integración — PASS

- `reports/ai-bots/TAP-INTEGRATION-GATE-001/evidence/GATE_REPORT.json`: `verdict PASS`, `commit 9a420ff1`, **15 pasos**, ninguno en `continue-on-error`.
- `REVIEW.json`: `verdict PASS`, **8 controles negativos**, `control_failures: []`, `false_success: 0`.
- Re-verificación independiente de esta entrega sobre esa evidencia: `verify` sale **0** y `review_gate.py` sale **0** (claim A6).
- A2 recalcula **525 hashes** del manifiesto de evidencia; ninguno discrepa.

## 4. GitHub Actions — NOT_EXECUTED, y por qué no es un fallo del gate

| Comprobación | Resultado |
| --- | --- |
| `.github/workflows/integration-gate.yml` en `origin/main` | **ABSENT** (`git cat-file -e origin/main:.github/workflows/...` falla) |
| Workflows registrados en el repo | 3; `integration-gate` no está entre ellos |
| `GET /actions/workflows/integration-gate.yml/runs` | **404** |
| Pasos del workflow ejecutados en local (verbatim) | `preflight` → **PASS**, `certifies: false` |
| Control negativo: árbol sucio | **FAIL**, `P1_TREE: dirty: ['?? ...']`, exit 1 |
| Control negativo: `--out` dentro del repo | **FAIL**, `P5_OUTSIDE_TREE`, exit 1 |
| Control negativo: evidencia manipulada | `verify` exit **1**, `review_gate.py` exit **1** (A6) |

Correspondencia workflow ↔ comando real: el workflow invoca `scripts/tap_integration_gate.py run --out … --label …` y `reports/ai-bots/TAP-INTEGRATION-GATE-001/tools/review_gate.py --evidence …`; ambos existen, aceptan exactamente esos flags (`--out`, `--label`; `--evidence`, `--out`) y son los mismos binarios que produjeron la evidencia PASS. La polaridad pedida queda demostrada en los tres controles negativos (falla ante evidencia o árbol inválidos, pasa ante los válidos).

**Por qué `NOT_EXECUTED`:** el fichero del workflow vive sólo en ramas locales; `origin/main` está 263 commits atrás y no lo contiene, así que GitHub no puede ni registrarlo. No es un workflow roto: es un workflow que nunca llegó al remoto.

## 5. Required check — NOT_ENFORCED / `GOVERNANCE_BLOCKED`

- La API de protección responde **401 `Requires authentication`** sin token; `gh` no está instalado. No se leyó ni se cambió el estado de branch protection, y no se simula.
- Nada en el repositorio impone el check: el encabezado del propio workflow declara *"this workflow is not a required status check today"* y el gate reporta `required_check: false` en lugar de reclamar cumplimiento.

**Acción mínima (administrador del repo, no ingeniería):** Settings → Branches → Branch protection en `main` → *Require status checks* → añadir `Integration gate (campaigns on this commit)`. Verificación posterior, con token de admin:

```
gh api repos/Extr3sao/bot_crypto/branches/main/protection --jq '.required_status_checks.contexts'
```

## 6. G1 — OPEN

G1 no es un test: es la **firma del cambio de política de riesgo** que hace rodar el veto de pérdida semanal a lunes 00:00 UTC. El gate lo deja en `OPEN_SIGNOFF` (`FINAL_REPORT.md:58`, `RUN_REPORT.md:129,146`) porque firmar una relajación de riesgo no es una tarea de verificación. Sigue abierto y es el bloqueo que mantiene a 002 en `NOT_READY`.

## 7. Paper admission — NO_GO (con ejecución real, no simulada)

**Entrypoint real:** `scripts/def_run_019_prospective_run.py` (schema `DEF_RUN_019_LIVE_META_V1`), ejecutado en `ff-paper-run-001` contra **market data público de Binance** (`server_time_ms` del exchange, `skew_ms = -322`, 29 barras 1m incorporadas, 0 duplicadas, 1 forming descartada), `mode: PAPER`, `live_enabled: false`, `symbols: [BTCUSDT]`, `strategy_id: ema_crossover`, `signal_source: legacy_parity`, `latency_ms: 30000`, `max_cycles: 2`.

Sesión copiada a `evidence/paper_session/` y juzgada por el verificador (claim A4):

| Hecho | Valor |
| --- | --- |
| commit registrado en la sesión | `55f991b7` (el HEAD auditado) |
| ciclos ejecutados / bloqueados | **2 / 0** |
| `data_delay_ms` | **6184**, fuente `MEASURED_AT_SESSION_START` |
| fills / trades / drawdown | **0 / 0 / 0.0 %** |
| órdenes live | **0** |
| locks dejados atrás | **0** (sólo `.lock.fence`, que no es propiedad) |
| cadena de hash del `STREAM.jsonl` | 6/6 filas válidas, `SESSION_START` y `SESSION_END` únicos |

Riesgo, ejecución y reconciliación responden (equity 10.000 → 10.000, sin bloqueos, sin excepciones), pero **no hubo fill ni trade cerrado**: con 2 barras de decisión y `warmup_minutes: 25` no se alcanzó señal. Eso acota lo probado: la *maquinaria* paper funciona de punta a punta; el *ciclo de trade* no se ejerció en esta sesión (sí en tests, no en mercado real).

**Por qué NO_GO, y no por la sesión:** el ledger de admisión tiene **24 estrategias y 0 admitidas** (estados `COST_KILLED`, `NO_GROSS_EDGE`; claim A5). El runtime no tiene ninguna estrategia con permiso para operar: ejecutar paper hoy es correr el motor sin candidato. `PAPER_READY` sería falso.

## 8. Bloqueos, responsables y acción mínima

| # | Bloqueo | Estado | Responsable técnico | Acción mínima |
| --- | --- | --- | --- | --- |
| B1 | G1 sin firma (veto semanal) | **OPEN** | risk-manager | firmar el cambio o revertir el roll; después, 002 pasa de `NOT_READY` a `READY` |
| B2 | Gate no es required check | **GOVERNANCE_BLOCKED** | administrador del repositorio | activar el status check en Settings (comando de verificación en §5) |
| B3 | Workflow nunca ejecutado en GitHub | **NOT_EXECUTED** | quien tenga autorización de push/PR | publicar la rama y abrir PR: es el único disparador que no necesita admin |
| B4 | 0 estrategias admitidas | **NO_GO** | quant-researcher / strategy-engineer | una estrategia que supere la barrera de costes; el gate no puede sustituirla |
| B5 | Evidencia de esta auditoría sin versionar | **cerrado** | — | `.gitignore` ahora versiona `reports/ai-bots/TAP-INTEGRATION-ADMISSION-002/**` (antes la carpeta entera estaba ignorada: `git status` decía "clean" con la evidencia invisible) |
| B6 | Verificador podía dar por bueno un ciclo bloqueado | **cerrado** | — | `A4` cruza `RUN_RESULT.exit_code`, `summary.cycles_blocked` y `closed_trades`; antes leía una clave inexistente y el chequeo nunca disparaba |

## 9. Siguiente paso operativo (comando exacto)

El único bloqueo que se desbloquea con una acción de ingeniería —sin administrador ni firma— es B3, y es el que convierte `NOT_EXECUTED` en evidencia de runner:

```
git push -u origin admission/integration-002 && gh pr create --base main --head admission/integration-002 --title "TAP-INTEGRATION-ADMISSION-002" --body "Gate evidence re-verified; review required"
```

Requiere: autorización de push/PR y `gh` instalado con token (hoy: `gh: command not found`, API de protección 401). Al abrirse el PR, GitHub ejecuta el workflow desde el fichero de la rama y el gate juzga el resultado del merge, no la punta. `main` no se modifica con esto.

Si se prefiere cerrar primero la gobernanza, el paso es el toggle de §5 y la verificación con `gh api`.

## 10. Evidencias y verificación independiente

| Artefacto | Qué prueba |
| --- | --- |
| `evidence/ADMISSION_VERIFICATION.json` | 9 claims (A1–A7 + S1, S2), `verdict PASS`, `false_success: 0` |
| `tools/admission_verify.py` | el verificador (no comparte código con el builder) |
| `evidence/paper_session/**` | la sesión PAPER real, con cadena de hashes y procedencia por fichero |
| `reports/ai-bots/TAP-INTEGRATION-GATE-001/evidence/**` | la evidencia del gate, 525 hashes recalculados |
| `reports/ai-bots/TAP-SUPERVISOR-INTEGRATION-002/ROUTE_MANIFEST.json` | las 84 rutas y por qué no hacen falta 301 commits |

Comando de reproducción (determinista, sin red para los claims de gate; la sesión PAPER es evidencia grabada, no se re-ejecuta):

```
.venv/Scripts/python.exe -m ruff check reports/ai-bots/TAP-INTEGRATION-ADMISSION-002/tools/admission_verify.py
.venv/Scripts/python.exe reports/ai-bots/TAP-INTEGRATION-ADMISSION-002/tools/admission_verify.py
```

`sha256` del verificador: `c1b98ebd…40e4a9a2` · `sha256` del resultado: `e1e62914…e5ea4bd180`

**Autocontroles del verificador (para que no sea ciego):** S1 reescribe una fila del stream en una copia temporal y exige que A4 la juzgue FAIL (lo hace: falla la cadena); S2 añade una fila `ADMITTED` al ledger y exige que A5 la juzgue FAIL (lo hace: `admitted=1`). Ambos dan PASS, es decir, el verificador *ve*.

## 11. Límites de este informe

1. No hubo ejecución en `ubuntu-latest`: las campañas corrieron en Windows. El matado de procesos del supervisor es la parte más sensible a plataforma.
2. La suite completa `pytest tests/unit` no se ejecutó aquí (subconjuntos ya tardan >27 min en esta máquina); se ejecutaron los tests que fijan el código migrado y los estáticos del gate.
3. El estado de branch protection no se leyó: sin `gh` y sin token, la API devuelve 401. Se declara bloqueado, no cumplido.
4. La sesión PAPER no produjo fills (§7): prueba mecánica, no ciclo de trade en mercado.
5. `origin/main` está 263 commits por detrás del `main` local; cualquier lectura de CI remoto describe un árbol antiguo, no esta entrega.
