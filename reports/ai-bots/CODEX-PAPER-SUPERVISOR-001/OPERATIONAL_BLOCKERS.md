# OPERATIONAL BLOCKERS — CODEX-PAPER-SUPERVISOR-001

Estado a 2026-10-23. Sólo se enumeran bloqueos con evidencia adjunta; los que este trabajo
cierra se marcan como cerrados **para su alcance**, no para live.

| # | Bloqueo | Estado | Evidencia / efecto |
| --- | --- | --- | --- |
| S-1 | El checkout compartido estaba en `main`, que no contiene el runtime PAPER | **Resuelto para este trabajo** | Worktree `wt-sup001` sobre `codepaper/supervisor-001` @ `60455b46`. `main` no se tocó. |
| S-2 | `reports/*` está gitignored: las evidencias de `CODEX-PAPER-LOCK-CAMPAIGN-001` no están en ningún commit | **Abierto (proceso)** | `.gitignore:55`; `git ls-tree -r` de todo el repo no encuentra `CODEX-PAPER-LOCK-CAMPAIGN-001`. El mecanismo sigue en código y tests; la evidencia antigua no es citable. |
| S-3 | `uv sync --frozen` no reproduce el entorno: `uv.lock` no tiene `matplotlib` y `pyproject.toml` sí lo exige | **Abierto (entorno)** | Colección falla con `ModuleNotFoundError: matplotlib`. Workaround local en el venv del worktree; `uv.lock` sin cambios. Quien reconstruya desde el lock verá el mismo fallo. |
| S-4 | `tests/unit/ops/test_windowless.py::test_no_controlled_launcher_can_start_an_unhidden_child` falla | **Abierto, preexistente** | Denuncia `POPEN_WITHOUT_WINDOWLESS` en `scripts/exp004a_verify.py:1216` y `tests/unit/ops/test_session_status.py:65`. Ajeno a este encargo; no se silenció. |
| B-1 | Bloqueo económico declarado en `CODEX-PAPER-LOCK-CAMPAIGN-001` | **No resuelto (fuera de alcance)** | El encargo prohíbe resolverlo aquí. Nada de este informe lo mitiga. |
| B-2 | Segundo bloqueo económico del mismo informe | **No resuelto (fuera de alcance)** | Ídem. |
| P-1 | `PAPER_ADMISSION` | **NO_GO** | No se ha tocado. Recuperar una sesión no es admitirla: no hay métricas de estrategia, ni walk-forward, ni OOS en este trabajo. |
| P-2 | Fills simulados | **Limitación de evidencia** | Los `FILL` de estas sesiones son PAPER. No son operaciones reales ni prueba de rentabilidad. |
| S-5 | Recuperación limitada a un host | **Abierto (diseño)** | `diagnose_lock` sólo puede probar la muerte de un pid de este host. Un dueño remoto queda `UNATTRIBUTED`, el supervisor se detiene en `STOP_AMBIGUOUS` y no borra el lock. Correcto, pero no hay recuperación multi-host. |
| S-6 | Una parada por presupuesto deja locks abandonados | **Por diseño** | El escenario `budget` termina en `RETRY_BUDGET_EXHAUSTED` con 4 locks `ABANDONED`. Un supervisor posterior con presupuesto disponible los reclamaría; borrarlos para "quedar limpio" sería el fallo, no la cura. |
| S-7 | El corte del proceso es `taskkill /F /T`, no pérdida de energía | **Limitación del método** | Prueba terminación forzada del árbol; no prueba corrupción de disco ni cortes del sistema operativo. |
| S-8 | El supervisor sólo actúa sobre PAPER | **Por diseño** | `entrypoint_argv` rechaza cualquier `mode` distinto de `PAPER`; el entrypoint no tiene ruta live. No existe un supervisor live y este trabajo no lo autoriza. |
