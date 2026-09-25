# DEFECTS_BURN_IN_V2 — registro consolidado

Clasificación por defecto: RUNTIME / OBSERVABILITY / TEST_HARNESS /
BURNIN_TOOLING / DOCUMENTATION. Detalles crudos en el directorio del run.

## DEF-201 — BURNIN_TOOLING · P1-sesión · FIXED

Doble instancia del launcher → colisión WinError 32 en el state file.
El store atómico (tmp+fsync+rename) protegió el estado: 0 pérdida, 0
corrupción. Fix: loop v3 (flock + freshness guard). LAUNCHER_SINGLETON=PASS:
75+ restarts sin colisión desde 15:09. No es defecto del trading runtime.

## DEF-202 — OBSERVABILITY · P3 · DEFERRED (V3)

`orders_created` cuenta execution requests (risk-approved, incluidos
same-side skips) ≠ fills durables (23 vs 22 en el snapshot). 0 duplicación
económica. Semántica renombrada EXECUTION_REQUESTS en RUN_SUMMARY.json.

## DEF-203 — BURNIN_TOOLING · P3 · FIXED (higiene)

Residuos de loops v1/v2 en el directorio del run. Limpieza al cierre,
preservando evidencia de la colisión.

## DEF-204 — RUNTIME (efficiency) · P2 · DEFERRED (V3)

Churn residual por vela nueva con posición abierta same-side (≤3 llamadas
risk+broker por vela). El bar-close gate eliminó el churn intra-vela (95%);
éste es el residual por-vela-nueva. Observación pura en V2; candidato a
pre-check en V3. Vetos raw 385 vs únicos 166 (2.32×).

## DEF-205 — RUNTIME · P1 · FIXED + VALIDACIÓN EN CURSO

**Síntoma**: posición BTC cerrada a exit_price=0.0 (−500.50, −100% del
notional) a las 19:15:58; daily_pnl −500 triplicó el límite diario →
lockout + cooldown el resto del día.

**Causa raíz**: el scanner emite snapshots inactivos con `last_price=0.0`;
`reconcile_session` los copiaba al price map (solo validaba `is not None`)
y `check_exit(0.0)` dispara stop_loss → cierre a precio 0.

**Fix** (commit `51957e4`): guard fail-closed precio≤0 en
`PaperBroker.check_positions` — un precio no válido se trata como precio
ausente (skip), nunca como mark price. Nunca suprime salidas legítimas
(precio bajo válido sigue cerrando; testeado).

**Tests**: 2 regresiones nuevas (zero/negative skip + reconcile end-to-end
con snapshot muerto). Suite: 610 passed.

**Validación runtime**: el runner post-fix arrancó 20:15 (> commit 19:57).
El trade con exit=0 es historia inmutable; 0 cierres a precio 0 desde el
fix. Validación completa de trading post-fix pendiente del reset diario UTC
(02:00 local) que libera el lockout — dentro de la ventana del run.
