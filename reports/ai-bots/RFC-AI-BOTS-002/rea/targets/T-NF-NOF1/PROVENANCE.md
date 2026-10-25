# T-NF-NOF1 · procedencia y refutación de la atribución anterior

**Commit medido:** `5d27641dfa47cc942aa0709ffb3f5237de876373` · árbol `b3ae235a0ff6555ff7a77c5c76c93cad2b1f5463` · 2026-05-15.
**Licencia:** AGPL-3.0 (`LICENSE` sha256 `e0eedba615d5cd1b…`, API de GitHub HTTP 200).
**Artefacto analizado con REA:** `public/` de ese commit, digest `9bef5c9b…`.

## P0 que resuelve este documento

La RFC v3 presentó los 12 chunks servidos en `https://nof1.ai/` como artefacto de
`195440/nof1.ai @5d27641`. Nunca se estableció el vínculo. Medido el commit, el vínculo
**no existe** y además es incompatible.

### Medición 1 — el bundle público es Next.js/Turbopack

Sobre los 12 chunks (digest `5fbc183a1c15b1ffe993669699205a944dc72237d241c7db5a55c54681ff44b9`):

| literal | ficheros con ocurrencias |
| --- | --- |
| `__NEXT` | 9 / 12 |
| `turbopack` | 7 / 12 |
| `_next/static` | 3 / 12 |
| `open-nof1` | 0 |
| `voltagent` | 0 |
| `gate-api` | 0 |
| `195440` | 0 |
| `vt_` | 0 |

### Medición 2 — el repositorio no tiene Next.js

- `package.json` (commit exacto): `name: open-nof1.ai`, `build: tsdown`, `type: module`.
  Dependencias: `@voltagent/*`, `ai`, `ccxt`, `gate-api`, `chart.js`, `pino`, `zod`.
  **No hay `next`, no hay `next.config.*`, no hay `app/` ni `pages/`.**
- `grep -ril '"next"|next\.config|turbopack|__NEXT_DATA__'` sobre todo el árbol:
  **cero ficheros**.
- Todo el JavaScript del commit son dos ficheros del dashboard estático:
  `public/app.js` (16.833 B) y `public/monitor-script.js` (39.159 B).
- El dashboard del proyecto se publica en `https://open-nof1.195440.com/`
  (`canonical` y `hreflang` en `public/index.html`), no en `www.nof1.ai`.

### Conclusión

Un árbol sin Next.js no genera chunks de Turbopack con nombres tipo `0cz1d0mv5g_q7.js`.
Por tanto:

1. `www.nof1.ai` **no** es este proyecto en este commit.
2. La evidencia de la v3 se conserva íntegra en `../T-NF-PUBLIC/`, reetiquetada como
   **deployment no atribuido**, sin cambiar ni un hash.
3. Ninguna afirmación de este dossier usa el bundle público como si fuera del repositorio.

## Lo que sí se puede decir de este repositorio (medido en fuente)

- Es un agente Node/TypeScript sobre Voltagent con backend propio (Hono), base libSQL,
  ejecución vía `gate-api`/`ccxt` y **sin ruta paper**: sólo el header
  `x-simulated-trading: 1` de OKX testnet.
- El análisis es **texto, no imagen**: `src/services/multiTimeframeAnalysis.ts` calcula
  EMA/RSI/ATR y estructura por timeframe; no hay render de gráfico ni payload multimodal
  en todo `src/` (ni `image_url`, ni `base64` de imagen, ni `savefig`).
- El modelo **elige tamaño y apalancamiento**: la herramienta `execute` acepta
  `leverage` (1..`MAX_LEVERAGE`, 15 por defecto) y `amountUsdt` desde el LLM.
- Las protecciones de drawdown están **desactivadas en el código**
  (`ACCOUNT_DRAWDOWN_NO_NEW_POSITION_PERCENT` y `..._FORCE_CLOSE_PERCENT` marcados
  "ya desactivado - comprobaciones comentadas").

Nada de esto es evidencia REA: es auditoría de fuente. La separación se mantiene
explícita porque `NO_REA_EVIDENCE = NO_EXTERNAL_PATTERN_CERTIFICATION`.
