# TAP-061 — fila lista para el Excel maestro

El libro maestro no está en este host (§7 del informe). Esta es la fila con los
campos del registro, para pegar tal cual cuando el `.xlsx` esté disponible.

| campo | valor |
| --- | --- |
| ID | `TAP-061` |
| WP | `WP-OPS-BACKGROUND-001` |
| Título | Ejecución sin ventanas de consola en Windows |
| Estado | `DONE_WITH_EXTERNAL_BLOCKER` |
| Prioridad | P1 |
| Fecha | 2026-10-18 |
| Rama | `agent/ai-bots/RFC-TAP-AI-BOTS-003` |
| Alcance | lanzadores, supervisor, tarea programada, capturas, tests |
| Resultado | `CREATE_NO_WINDOW` + `STARTUPINFO(SW_HIDE)` en una sola implementación; tarea programada vía `pythonw.exe scripts/windowless.py`; 0 HIGH en auditoría |
| Evidencia | `reports/ops/WP-OPS-BACKGROUND-001/` |
| Tests | 13 nuevos; 335 en ops+autonomous+campaign; 90 scheduler/runner/edge04r; 87 edge04 |
| Bloqueo externo | ventana de `bun.exe`/`bash.exe` abierta por Freebuff Desktop (Codebuff); falta `windowsHide` en el `Bun.spawn` del shell |
| Bloqueo interno | Excel maestro ausente en el host |
| No claims | ventana observada/suprimida visualmente; migración total de `subprocess.run` |

## JSON equivalente

```json
{
  "id": "TAP-061",
  "wp": "WP-OPS-BACKGROUND-001",
  "title": "Ejecución sin ventanas de consola en Windows",
  "status": "DONE_WITH_EXTERNAL_BLOCKER",
  "priority": "P1",
  "date": "2026-10-18",
  "branch": "agent/ai-bots/RFC-TAP-AI-BOTS-003",
  "result": "CREATE_NO_WINDOW + STARTUPINFO(SW_HIDE) centralizado; tarea programada vía pythonw.exe + scripts/windowless.py; auditoría 0 HIGH",
  "evidence": "reports/ops/WP-OPS-BACKGROUND-001/",
  "tests": "13 new / 335 ops+autonomous+campaign / 90 scheduler+runner+edge04r / 87 edge04",
  "external_blocker": "Freebuff Desktop (Codebuff) Bun.spawn without windowsHide for the shell path",
  "internal_blocker": "master workbook not present on this host",
  "not_claimed": [
    "a visible window was observed and suppressed on this host",
    "every subprocess.run site was migrated"
  ]
}
```
