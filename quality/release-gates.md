# Release Gates

> Gates de release (paper y live). Si una sola caja no está verde,
> el release NO procede.

---

## Bloque 1 — Calidad de código

- [ ] Code quality gates: `quality/code-quality.md`.
- [ ] Risk quality gates: `quality/risk-quality-gates.md`.
- [ ] `pytest` en verde.
- [ ] `mypy` en verde.
- [ ] `ruff` en verde.

## Bloque 2 — Estrategia / backtest / paper

- [ ] Estrategia en estado correcto (paper o live_candidate).
- [ ] Backtest firmado por `backtest-engineer` y `quant-researcher`.
- [ ] Walk-forward con métricas mínimas.
- [ ] Paper con métricas mínimas (si promoción a live).

## Bloque 3 — Riesgo y seguridad

- [ ] `risk-manager` y `security-reviewer` firmaron.
- [ ] Sin secretos en el repo.
- [ ] `safety` y `pip-audit` limpios.

## Bloque 4 — Operación

- [ ] Logs estructurados funcionando.
- [ ] Health checks activos.
- [ ] Runbook de incidentes disponible.

## Bloque 5 — Promoción a LIVE

> Bloque adicional si el release promueve a `live`.

- [ ] `docs/live-trading-checklist.md` completo y firmado.
- [ ] `LIVE_TRADING_ENABLED=true` y `I_UNDERSTAND_THE_RISKS=true` confirmados.
- [ ] Operador principal + peer firmaron.
- [ ] ADR firmado y publicado.

## Procedimiento

1. Copiar este checklist al inicio del PR/release.
2. Marcar cada ítem con `[x]`, `[ ]` o `NO_APLICA` con justificación.
3. Adjuntar evidencias (enlaces a informes, logs, ADR).
4. Firmar cada bloque.
5. Sin firmas NO hay release.

## Política de excepción

No hay excepción. Si un ítem falla, se documenta en `tasks/decisions.md`
con:
- Justificación escrita.
- Mitigación propuesta.
- Plan de remediación con fecha.
- Firma humana.
