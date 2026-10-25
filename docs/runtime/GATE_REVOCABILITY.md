# Gate Revocability Principle

> Certificados en este proyecto son afirmaciones bajo la evidencia disponible,
> no propiedades permanentes. Se revocan cuando evidencia más fuerte los
> invalida.

## Regla

```
A CERTIFIED GATE MAY BE REVOKED
WHEN STRONGER EVIDENCE INVALIDATES IT
```

Ejemplo:

```
G1 PASS
  ↓
RFC-020 detecta look-ahead / una ventana in-sample
  ↓
G1 queda INVALIDATED (no se conserva un PASS históricamente incorrecto)
```

## Órdenes de autoridad

```
REAL_RUNTIME > EXECUTION_EVIDENCE > TESTS > SOURCE_CODE > ARCH/RFC > ASSUMPTION
```

Ninguna afirmación de una capa inferior puede mantener un gate frente a evidencia
de una capa superior.

## Obligaciones

- Un gate se emite con la evidencia que lo sostiene y el commit exacto.
- Toda revocación se documenta con: gate, evidencia nueva, impacto, fase que la
  detectó y decisión (REVOKED / DOWNGRADED / ANNOTATED).
- No se rebajan los criterios para obtener PASS; `FALSE_SUCCESS = 0`.
- Un gate revocado no se restaura sin evidencia nueva de la misma o superior
  autoridad.

## Revocaciones registradas

| gate | evidencia | decisión | fase |
| --- | --- | --- | --- |
| G1 | baseline es un diagnóstico **in-sample** respecto al prior (ledger W1–W7 ⊃ replay W1–W4) | **ANNOTATED** (no revocado: la afirmación "no hay edge suficiente para la config congelada" sigue siendo cierta como diagnóstico; no se reclama validez OOS) | RFC-020 |
