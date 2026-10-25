# T-NF-NOF1 · correlación fuente ↔ runtime

`REA_EVIDENCE_ID`: `ev_4b2bf9c5c313530cc7e1e399d4cde5c175ecdd0018a9f608ee12782522ea9ade` (artefacto `public/` del commit `5d27641dfa47cc942aa0709ffb3f5237de876373`).
El backend TypeScript **no** se ejecutó: se auditó por fuente. Esa asimetría se declara, no
se disimula.

| capa | fichero (commit exacto) | tipo de evidencia | estado |
| --- | --- | --- | --- |
| render de gráfico | — | no existe en `src/` | **AUSENTE** (medido: 0 `image_url`, 0 `savefig`, 0 payload multimodal) |
| datos de mercado | `src/services/okxWebSocket.ts`, `gateClient.ts` | fuente | leído |
| análisis | `src/services/multiTimeframeAnalysis.ts` | fuente | leído (EMA/RSI/ATR por timeframe) |
| payload al modelo | `src/agents/aggressiveTeamAgents.ts`, `analysisAgents.ts` | fuente | leído (texto) |
| decisión | `src/tools/trading/tradeExecution.ts` | fuente | leído (`execute` con leverage/amount) |
| riesgo | `src/config/riskParams.ts` | fuente | leído (drawdown desactivado) |
| ejecución | `src/services/gateClient.ts`, `okxClient.ts` | fuente | leído (órdenes reales, sin paper) |
| UI pública | `public/*` | **REA** (`ev_4b2bf9c5c313530cc7e1e399d4cde5c175ecdd0018a9f608ee12782522ea9ade`) | analizado: 2 JS, 0 módulos |
| comportamiento en vivo | — | — | `UNKNOWN` |

## Divergencias que importan

1. **No es un bot visual.** El RFC lo listaba como candidato de "gráfico → IA". Medido: no
   hay gráfico. Cualquier plan que asuma lo contrario está mal planteado.
2. **Autoridad invertida.** El modelo fija tamaño y apalancamiento; nuestro contrato lo
   prohíbe. No es una diferencia de grado, es de arquitectura.
3. **Guardas declaradas y no aplicadas.** Drawdown desactivado por comentario.
4. **Sin ruta paper.** Sólo testnet por header: no hay ledger comparable que medir.
