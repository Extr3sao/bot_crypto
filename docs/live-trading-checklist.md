# Live Trading Checklist

> **Obligatorio** antes de pasar a `live`. Cualquier ítem en `NO/Parcial`
> bloquea el paso. Firmar abajo.

---

## A. Documentación y diseño

- [ ] Backtest documentado en `reports/backtests/` con métricas completas.
- [ ] Walk-forward completo y aprobado por `quant-researcher`.
- [ ] Paper trading ≥ 20 días o 300 trades con métricas mínimas.
- [ ] Estrategia en estado `live_candidate` (no salto directo).
- [ ] ADR firmado en `tasks/decisions.md`.

## B. Riesgo

- [ ] `config/risk.yaml` revisado y firmado por `risk-manager`.
- [ ] Kill switch activo, probado y documentado.
- [ ] Pérdida diaria máxima definida.
- [ ] Pérdida total máxima definida.
- [ ] No hay overrides "temporales" activos.

## C. Seguridad

- [ ] API key sin permisos de retirada.
- [ ] IP whitelist configurada.
- [ ] IP whitelist confirmada por test.
- [ ] Permisos mínimos en el exchange.
- [ ] `.env` no commiteado. Sin secretos en logs.
- [ ] `safety check` y `pip-audit` limpios.
- [ ] `security-reviewer` firma.

## D. Operación

- [ ] Logs estructurados activos.
- [ ] Métricas/alertas activas (cuando aplique).
- [ ] `EXCHANGE_SANDBOX=false` solo después de todos los gates.
- [ ] Watchdog / health checks activos.
- [ ] Documento de runbook para incidentes.

## E. Variables de entorno

- [ ] `LIVE_TRADING_ENABLED=true` — explícito.
- [ ] `I_UNDERSTAND_THE_RISKS=true` — explícito.
- [ ] `TRADING_MODE=live` — explícito.
- [ ] Claves API presentes y validadas.

## F. Confirmación humana

- [ ] Dos personas firman el paso a live (dual control).
- [ ] Una de las firmas es del operador principal.
- [ ] La otra es del revisor de riesgo o un peer dev.

## Firmas

| Rol                          | Nombre | Fecha | Firma |
| ---------------------------- | ------ | ----- | ----- |
| Operador principal           |        |       |       |
| Revisor de riesgo / peer     |        |       |       |
| `risk-manager` (agente)      |        |       |       |
| `execution-engineer` (agente)|        |       |       |
| `backtest-engineer` (agente) |        |       |       |
| `security-reviewer` (agente) |        |       |       |

## Procedimiento de desactivación rápida

Si algo va mal en live:

1. Activar kill switch: `python -m trading_bot.app kill-switch on --reason "..."`.
2. Confirmar cancelación de señales pendientes.
3. NO cerrar posiciones abiertas automáticamente (decisión humana).
4. Abrir ticket post-mortem en `tasks/decisions.md` con timeline.

## Política de arrepentimiento

No hay política de arrepentimiento. Si se cumplen los gates y se opera,
se acepta la posibilidad de pérdida total. La metodología existe
justamente para reducir esa probabilidad.
