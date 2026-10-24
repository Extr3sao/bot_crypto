# RUN REPORT — CODEX-PAPER-SUPERVISOR-001

Ejecución real sobre `scripts/def_run_019_prospective_run.py` (PAPER, BTC/ETH/SOL, 1m).
Sin mocks, sin órdenes live, sin cambios en estrategia, riesgo, sizing ni ejecución.

| Dato | Valor |
| --- | --- |
| Base | `60455b46` (`CODEX-PAPER-LOCK-CAMPAIGN-001`) |
| Código de este trabajo | `0e2ba09d` (+ `cc4f15f6`: evidencia del episodio final) |
| Verificador | `3b758e22` (`BUILDER != VERIFIER`) |
| Host | `DESKTOP-4CHO695`, un solo host |
| Modo | `PAPER`; `live_orders = 0` en las 33 filas del stream |
| Duración de la sesión declarada | 240 s por proceso, `max_cycles = 50` |
| Supervisores | 2 lanzados a la vez; 1 adquirió, 1 rechazado (exit 4) |

## 1. Qué se ejecutó

```
python scripts/paper_supervisor_campaign.py run --out reports/.../campaign
python scripts/paper_supervisor_campaign.py scenarios --out reports/.../campaign/scenarios \
    --source-session reports/.../campaign/session
python scripts/paper_supervisor_verify.py --campaign reports/.../campaign
```

El supervisor arranca el entrypoint real, espera a que exista un ciclo, deja que el harness
mate el árbol de procesos con `taskkill /F /T`, detecta el estado `RECOVERING`, valida la
evidencia y reanuda con `--resume` leyendo la configuración fijada en `RUN_META.json`.

## 2. Cronología (5 caídas, 5 recuperaciones, 1 cierre limpio)

| Episodio | Filas antes | Ciclos antes | Locks abandonados | Recuperación | Ciclos después |
| --- | --- | --- | --- | --- | --- |
| 1 | 4 | `[1]` | 4 (`STREAM`, BTC, ETH, SOL) | automática | `[1, 2]` |
| 2 | 9 | `[1, 2]` | 4 | automática | `[1, 2, 3]` |
| 3 | 14 | `[1, 2, 3]` | 4 | automática | `[1, 2, 3, 4]` |
| 4 | 19 | `[1, 2, 3, 4]` | 4 | automática | `[1, 2, 3, 4, 5]` |
| 5 | 24 | `[1, 2, 3, 4, 5]` | 4 | automática, sin volver a matarla | `[1..9]` y `SESSION_END` |

Resultado persistido:

* **6 `SESSION_START`** en las secuencias `1, 5, 10, 15, 20, 25`: una fresca y cinco
  reanudadas (`resumed: true`), cada una exactamente en la fila siguiente al crash.
* **33 filas**, secuencia `1..33` continua, cadena de hashes intacta, head
  `dfd4f55cc095d3b4da72fd3b98962f6eb3c9193a4c01c11707124a8ccf109610`.
* **9 ciclos únicos** `1..9`, todos `EXECUTED`, sin huecos y sin repeticiones; cada
  `cycles/cycle-NNNN/ledger.jsonl` verifica.
* **5 filas `LOCK_RECLAIMED`**, cada una con los 4 locks del epoch y fences **2, 4, 6, 8, 10**
  por lock: estrictamente crecientes, es decir, cada reanudación desplazó al dueño anterior.
* **21 `FILL`** PAPER (0, 2, 2, 2, 3, 3, 3, 3, 3), 0 cierres, 0 órdenes live.
* Cierre: `SESSION_END`, estado `RECOVERED`, **0 locks**, supervisor `STOP_COMPLETED`,
  `restarts = 5`, exit 0.

## 3. Comprobaciones obligatorias (WP-03 / Fase 3)

| Comprobación | Resultado | Evidencia |
| --- | --- | --- |
| Un único escritor autorizado | PASS | `one_supervisor_acquired`, un solo `ACQUIRED`; 6 `SPAWNED` del mismo supervisor |
| Fencing actualizado y respetado | PASS | fences 2→4→6→8→10 en los 5 reclaims; `reclaim_fences_advance` |
| Sin reclamar locks de dueños vivos | PASS | 5 sondas `LOCK_HELD` con registro byte-idéntico (`record_unchanged: true`) |
| Dueño antiguo rechazado (`LOCK_LOST`) | PASS | cubierto por la suite (`test_a_real_old_owner_cannot_write_after_its_lock_is_taken_over`), no por esta campaña |
| Ledger íntegro y secuencial | PASS | `stream_chain_intact`, `seq_continuous`, `cycle_ledgers_intact` |
| Sin ciclos duplicados ni eventos omitidos | PASS | `cycle_numbers_unique`, `cycle_numbers_increasing` |
| Prefijos persistidos reproducidos | PASS | 5 reanudaciones sin `PREFIX_DIVERGENCE`; 9 ciclos ejecutados |
| Ningún lock al finalizar | PASS | `no_lock_remaining_now` |
| Cero órdenes live | PASS | `no_live_orders`; `RUN_META.live_enabled = false` |

No se declara PASS por exit 0: cada recuperación se comprueba contra la fila
`SESSION_START` de la secuencia esperada y contra el crecimiento de filas y ciclos
(`attempts_continue_the_stream`, `no_clean_exit_without_evidence`).

## 4. Carrera de supervisores

Dos procesos lanzados sobre el mismo directorio con milisegundos de diferencia:

* `ACQUIRED`: 1 (pid real 21420);
* rechazado: 1, `LOCK_HELD`, exit **4**, **0** `SPAWNED` con su pid;
* el ganador es el único que creó hijos (6 en total).

## 5. Escenarios negativos

| Escenario | Resultado | Detalle |
| --- | --- | --- |
| Evidencia corrupta (línea truncada + lock abandonado) | `STOP_FAILED`, exit 3 | `FAILED`, 0 procesos lanzados, 33 filas antes / ilegible después; no se escribió nada |
| Presupuesto agotado (`--max-restarts 1`) | `STOP_BUDGET`, exit 3 | 2 intentos, 1 reanudación, luego parada; deja 4 locks `ABANDONED` (correcto: parar no es limpiar) |

## 6. Verificación independiente

`scripts/paper_supervisor_verify.py` (no importa el productor) reconstruye cadena, secuencias,
ciclos, ledgers, fences, journal y límites de autoridad:

* **PASS 33/33 checks**, 0 fallos;
* **12/12 mutaciones detectadas**, **0 inválidas**, **`false_success = 0`**;
* artefactos hasheados en `VERIFICATION.json`.

## 7. Pruebas y regresión

```
.venv/Scripts/python.exe -m pytest tests/unit/ops -m "not slow and not market" -q
```

| | Antes | Después |
| --- | --- | --- |
| Resultado | 46 passed, 1 failed (47) | 82 passed, 1 failed (83) |

El fallo es el mismo y preexistente (`test_windowless` denuncia dos `Popen` sin
`windowless`, uno en `scripts/exp004a_verify.py`). `ruff` limpio en todos los ficheros
tocados. Se añadieron 36 tests (31 supervisor + 4 verificador + 1 diagnóstico).

## 8. Límites

* Corte forzado con `taskkill /F /T`, no pérdida de energía ni corrupción de disco.
* Un solo host: un dueño remoto queda `UNATTRIBUTED` y el supervisor se detiene.
* Fills simulados: no son operaciones reales ni evidencia de rentabilidad.
* La campaña usa 5 caídas; el presupuesto por defecto del supervisor es 3 y aquí se elevó a 8
  de forma explícita.
