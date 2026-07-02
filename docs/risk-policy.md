# Risk Policy

> Cómo el sistema limita pérdidas operativas. **Este documento es
> normativo: cualquier desviación requiere ADR firmado.**

---

## 1. Principios

1. **Pérdida limitada, no ganancias limitadas.** Las estrategias compiten
   por expectativas positivas, no por tamaño.
2. **El sistema se protege a sí mismo.** Nadie debe poder saltarse el
   risk-manager desde código.
3. **Las pérdidas se cortan rápido.** Drawdowns se cierran vía kill switch
   antes de que escalen.
4. **Lo conservador por defecto.** `live` está bloqueado por defecto.

## 2. Sizing

- Tamaño basado en `% del capital total` (no `quantity` fija).
- Reglas por defecto: `max_risk_per_trade_pct = 0.25%`.
- Stop-loss siempre obligatorio; sin stop la orden no sale.

## 3. Límites diarios y semanales

- **Pérdida diaria**: `max_daily_loss_pct = 1.0%` → cooldown hasta el día siguiente.
- **Pérdida semanal**: `max_weekly_loss_pct = 3.0%` → paper mode pausa por 1 día.
- **Drawdown total**: `max_total_drawdown_pct = 5.0%` → kill switch manual + revisión.

## 4. Exposición

- **Por activo**: `max_asset_exposure_pct = 10%` del capital.
- **Total**: `max_total_exposure_pct = 25%` del capital.
- **Posiciones abiertas**: `max_open_positions = 3`.

## 5. Racha de pérdidas

`max_consecutive_losses = 3` → cooldown de `consecutive_loss_cooldown_minutes = 60`.
Esto reduce el efecto sobre-martingala y obliga a revisar la estrategia.

## 6. Bloqueos defensivos

| Bloqueo           | Trigger                                              | Acción                                  |
| ----------------- | ---------------------------------------------------- | --------------------------------------- |
| Spread excesivo   | `spread > excessive_spread_bps`                       | Cancelar cualquier señal de ese par.    |
| Volatilidad extrema | `ATR% > extreme_atr_pct`                             | Pausar todas las estrategias ese día.   |
| Latencia alta     | `latencia > high_latency_ms`                          | Stop todos los envíos nuevos.           |
| Weekend           | `weekend_trading=false` y fin de semana              | Pausar (`shadow-live` salvo override).  |

## 7. Kill switch

`kill_switch_enabled = true` por defecto.

Disparado por:
- Drawdown total ≥ `max_total_drawdown_pct`.
- Tres o más `execution_error_definitive` consecutivos.
- Comando manual desde CLI/API.

Acciones del kill switch:
- Cancela señales pendientes.
- NO cierra posiciones abiertas automáticamente (decisión humana).
- Bloquea nuevos envíos hasta `kill_switch_off` explícito.

## 8. Live trading

`live_trading_enabled = false` por defecto. Para desbloquear:

```
LIVE_TRADING_ENABLED=true
I_UNDERSTAND_THE_RISKS=true
```

…y TODOS los gates de `docs/live-trading-checklist.md` cumplidos.

## 9. Auditoría

- Cada decisión de riesgo (`APPROVED | REJECTED | MODIFIED`) se registra en
  `logs/risk-decisions.log`.
- Cada kill-switch ON/OFF se registra con timestamp y motivo.
- Cada cambio en `config/risk.yaml` se firma en `tasks/decisions.md`.

## 10. Lo que NO se considera "control de riesgo"

- Rezar.
- "Edge" cualitativo sin métricas.
- Esperar a que el drawdown se recupere solo.
- Cambiar límites para que la estrategia "entre".
