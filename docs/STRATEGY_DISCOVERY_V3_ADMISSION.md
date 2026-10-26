# STRATEGY-DISCOVERY-V3 — admission matrix (§25/§29/§30)

> Aplicación mecánica de docs/STRATEGY_ADMISSION_CRITERIA.md (pre-registrados
> en `c1ffbaa`, ANTES de cualquier resultado; sin cambios post-hoc).
> Cadena: HYPOTHESIS → GROSS EDGE → COST SURVIVAL → VALIDATION → OOS →
> ROBUSTNESS → ADMISSION → PAPER. Ninguna candidata alcanza OOS: los
> filtros 1-2 ya la matan (§22).

## 1. Matriz

| Candidate | Asset | TF | Trades | Gross Exp | Net Exp | OOS PF | DD | Cost stress | Robustness | Admission |
|---|---|---|---:|---:|---:|---:|---:|---|---|---|
| D-01 trend@30m | BTC+ETH+SOL | 30m | 1575 | +2.21 bps | −469 bps eq | — | — | fails by construction | DEV/VAL sign flip | REJECT (Filter 2) |
| D-01 mean_rev@30m | BTC+ETH+SOL | 30m | 935 | +5.47 bps | −274.77 $ | — | — | fails by construction | DEV/VAL sign flip | REJECT (Filter 2) |
| D-01 volatility@30m | BTC+ETH+SOL | 30m | 196 | +8.91 bps | −24.62 $ | — | — | fails by construction | DEV/VAL sign flip | REJECT (Filter 2) |
| D-02_vol_z_rev | BTC+ETH+SOL | 15m | 31 | −13.16 $ | −28.66 $ | — | — | n/a | n/a | REJECT (Filter 1) |
| D-03_squeeze_breakout | BTC+ETH+SOL | 30m | 0 | n/a | n/a | — | — | n/a | n/a | INTESTABLE (0 señales; no re-tuning) |
| D-04_rel_momo | BTC+ETH+SOL (long líder) | 1h | 186 | −28.74 $ | −121.73 $ | — | — | n/a | n/a | REJECT (Filter 1) |
| D-05 celdas régimen (12) | per celda | 15m/30m | 100-4026 | ≤+25.5 bps DEV | sign flip en VAL | — | — | n/a | REGIME_FRAGILE 12/12 | REJECT (gate 0/12) |
| (referencia) mean_reversion 5m | BTC+ETH+SOL | 5m | 3190 | +1.49 bps | −619.04 $ | 0.67* | — | PF<1 (2X) | — | REJECT (Filter 2) — COST_KILLED |
| (referencia) trend 5m | BTC+ETH+SOL | 5m | 1288 | −232.76 $ | −876.83 $ | 0.94* | 5.3%* | PF 0.56 (2X) | NEGATIVE_ROBUST | REJECT (Filter 1) |

*Referencia del baseline V1 (3271a97); no es candidata V3.

## 2. Veredicto por candidata (§30)

- D-01: **REJECT** — la única línea con gross>0; muere en COST SURVIVAL
  (techo +8.91 bps < 12 bps BASE; con 2X/STRESSED la brecha es mayor).
- D-02: **REJECT** — sin gross edge (Filter 1).
- D-03: **INTESTABLE** — 0 señales con la spec pre-registrada. No se
  re-especifica post-hoc (§23); quedaría para una futura fase con spec
  nueva pre-registrada y justificada.
- D-04: **REJECT** — sin gross edge (Filter 1).
- D-05: **REJECT** — 0/12 celdas superan el gate DEV∧VAL; inestabilidad
  de signo entre splits (REGIME_FRAGILE).
- D-06: **NO APLICADO** — gate MFE≫realizado no se activó en ninguna línea.
- mean_reversion@5m (referencia V1, re-clasificada con diagnóstico V3):
  **REJECT COST_KILLED** — único edge bruto real del universo evaluado
  (+1.49 bps/trade), 8× bajo la barrera. NO es PAPER_CANDIDATE: los
  criterios exigen net>0 BASE, que no cumple (−619$).

## 3. ZERO_COST

Usado exclusivamente como diagnóstico de separación señal/coste (§17).
Ninguna decisión de admission se apoyó en él.

## 4. Múltiples comparaciones (§24)

Experimentos registrados: 24 (6 familiares-diagnóstico, 12 celdas D-05,
4 candidatas, audit D-01, barrera). Ningún resultado marginal (p.ej. PF
1.01) fue promocionado; el único gross>0 exige +8.9 bps frente a una
barrera de 12 bps — no es marginal, es insuficiente.
