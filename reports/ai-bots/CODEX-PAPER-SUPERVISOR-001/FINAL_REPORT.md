# FINAL REPORT — CODEX-PAPER-SUPERVISOR-001

**PASS para el alcance ejecutado**: recuperación automática de sesiones PAPER tras caídas
repetidas, con verificación independiente y controles negativos efectivos.
No es `CERTIFIED`, no es `PRODUCTION_READY`, no es una admisión. `PAPER_ADMISSION` sigue
`NO_GO`.

## 1. Qué funciona

* **El supervisor reanuda solo lo que puede probar.** `ops/paper_supervisor.py` decide por
  estados: `RUNNING` no se toca, `RECOVERING` sólo se reanuda si el lock está `ABANDONED`,
  la cadena y los ledgers verifican y hay identidad fijada; `FAILED`, `UNATTRIBUTED`,
  `BLOCKED` y el presupuesto agotado **no** se reinician. Un estado desconocido falla cerrado.
* **Cada recuperación se prueba contra el stream, no contra el exit code.** Se exige una
  `SESSION_START` en la secuencia siguiente con `resumed: true`, más filas que antes y cero
  locks. Un hijo que sale 0 sin escribir nada es `NO_PROGRESS`, no un éxito.
* **5 caídas, 5 recuperaciones automáticas, 6 procesos, una sola cadena.** 33 filas,
  secuencia 1..33, 9 ciclos únicos `1..9` sin duplicados ni huecos, 5 filas
  `LOCK_RECLAIMED` con fences 2/4/6/8/10 por lock, `live_orders = 0`.
* **Carrera de supervisores resuelta por el lock.** Un `ACQUIRED`, un rechazo `LOCK_HELD`
  con exit 4, cero hijos del perdedor.
* **Los casos que deben fallar fallan con nombre.** Evidencia corrupta → `STOP_FAILED`
  (exit 3, ningún proceso lanzado); presupuesto agotado → `STOP_BUDGET` tras 1 reanudación.
* **Verificación independiente.** `paper_supervisor_verify.py` da **PASS 33/33**, detecta
  **12/12** mutaciones, **0 inválidas**, `FALSE_SUCCESS = 0`.
* **El diagnóstico ya no se cae ante evidencia rota.** Una línea truncada se reporta
  `FAILED` (antes: excepción), y un stream ilegible ya no se confunde con "no hay sesión".

## 2. Qué sigue fallando

| Fallo | Naturaleza |
| --- | --- |
| `tests/unit/ops/test_windowless.py::test_no_controlled_launcher_can_start_an_unhidden_child` | **Preexistente**, ajeno: denuncia `Popen` sin `windowless` en `scripts/exp004a_verify.py:1216` y `test_session_status.py:65`. No se silenció. |
| `uv sync --frozen` no instala `matplotlib` | **Preexistente de entorno**: `uv.lock` no coincide con `pyproject.toml`. Workaround local, lock sin tocar. |
| Evidencias de `CODEX-PAPER-LOCK-CAMPAIGN-001` | **No están**: `reports/*` gitignored y ningún commit las contiene. El mecanismo se re-demostró aquí; las cifras antiguas no son citables. |
| Recuperación multi-host | **No soportada**: un dueño de otro host queda `UNATTRIBUTED` y el supervisor se detiene. |
| `PAPER_ADMISSION` | **NO_GO**, sin cambios. Ver §4. |

## 3. Defectos encontrados y corregidos

1. **`session_status` lanzaba excepción con una línea truncada.** Un corte entre `write` y
   `fsync` dejaba media línea y el diagnóstico —el que existe para reportar eso— moría con
   `JSONDecodeError`. Ahora devuelve `FAILED` con `CHAIN_BAD_JSON_AT_n`.
2. **Un stream presente pero ilegible se clasificaba `ABSENT`.** Al no poder leer filas, el
   estado decía "aquí no ha corrido nada" e invitaba a empezar de cero sobre una cadena que
   alguien podría estar escribiendo. Ahora `ABSENT` exige que el stream no exista.
3. **El harness mataba al descendiente, no al proceso supervisado.** El lock nombra el
   proceso real; `windowless.spawn` devuelve el lanzador. La primera pasada mató un hijo del
   entrypoint y el supervisor —correctamente— reanudó; el harness no lo reconoció y se
   descartó esa pasada. Corregido: se mata el pid que el supervisor registró como `SPAWNED`.

## 4. Siguiente bloqueo concreto para poner PAPER en marcha

El runtime **ya no es el bloqueo**: una sesión PAPER se recupera sola cinco veces seguidas
sin corromper la evidencia. Lo que impide la admisión es económico y está en el ledger de
admisión: `config/strategy_admission.json` no admite **ninguna** estrategia
(`NO_GROSS_EDGE`), y `data/recovery/wp9/WP9_ACTIVE_ECONOMIC_BLOCKERS.json` agrupa 17
estrategias en `NO_ECONOMIC_ADVANTAGE` más el bloqueo de `EXECUTION_COSTS`. Los bloqueos
**B-1** y **B-2** de `CODEX-PAPER-LOCK-CAMPAIGN-001` siguen abiertos y este trabajo no los
tocó, por encargo.

Por tanto, el siguiente paso concreto no es otro supervisor: es aportar evidencia económica
de una estrategia que sobreviva al coste de ida y vuelta y colocarla en
`paper_candidates`. Sin eso, `PAPER_ADMISSION` no puede pasar a `GO` aunque la operación sea
perfectamente recuperable.

## 5. Commits y comandos

| Commit | Papel |
| --- | --- |
| `60455b46` | Base del linaje PAPER |
| `0e2ba09d` | Supervisor, CLI, campaña, verificador y 36 tests |
| `cc4f15f6` | El episodio final escribe su propia evidencia |
| `3b758e22` | Precisión del CLI `--once`; commit del verificador |

```
pytest tests/unit/ops -m "not slow and not market" -q      # 82 passed, 1 failed (preexistente)
ruff check / ruff format --check                            # limpio
python scripts/paper_supervisor_campaign.py run --out …     # 5 caídas, 5 recuperaciones
python scripts/paper_supervisor_campaign.py scenarios --out …   # corrupto + presupuesto
python scripts/paper_supervisor_verify.py --campaign …      # PASS 33/33
```

## 6. Dónde está la evidencia

Todo bajo `reports/ai-bots/CODEX-PAPER-SUPERVISOR-001/`:

* `BASELINE.md` — estado del repo, runtime autoritativo y baseline de tests.
* `RUN_REPORT.md` / `RUN_REPORT.json` — cronología, tablas y cifras ligadas a artefactos.
* `VERIFICATION.json` — 33 checks, 12 mutaciones, hashes, commit del verificador.
* `OPERATIONAL_BLOCKERS.md` — bloqueos con estado y causa.
* `campaign/` — `CAMPAIGN.json`, `session/STREAM.jsonl`, `supervisor/SUPERVISOR.jsonl`,
  `episodes/`, `scenarios/SCENARIOS.json` y `campaign/VERIFICATION.json`.

## 7. Declaración de alcance

`PASS` significa: en un host, en PAPER, con cortes forzados del árbol de procesos, cinco
caídas consecutivas se recuperaron sin duplicar ciclos, sin aceptar escritores antiguos, sin
reclamar locks de dueños vivos, sin dejar locks al cerrar y sin una sola orden live,
verificado por un programa distinto del que produjo la evidencia.

No significa: estrategia rentable, admisión, multi-host, tolerancia a corrupción de disco ni
permiso para operar con dinero real.
