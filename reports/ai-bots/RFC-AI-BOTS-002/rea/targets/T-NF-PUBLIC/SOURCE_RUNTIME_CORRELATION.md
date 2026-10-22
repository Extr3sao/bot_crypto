# T-NF-PUBLIC · correlación fuente ↔ artefacto observado ↔ nuestro runtime

**Evidencia en la que se apoya este documento**

| operación | `evidence_id` |
| --- | --- |
| `analyze_javascript_application` (12 chunks) | `ev_aee35b0f11df7a73b082c5cbc72e10c97f27b22917da003998d93eaa455617fc` |
| `list_browser_targets` (Chrome perfil vacío, CDP loopback) | `ev_f7020db13e2de339e89e64231dd55522fe97ab8d17447644e8dfb5ef0961bb00` |
| `capture_web_screenshot` | `ev_47c01accd3491fd6e10e893f8a045e5fee226fa520f648f4460396a619efbaf1` |
| `analyze_web_bundle` (43 scripts) | `ev_82d99570975285bde3570fb1b4002ea6b323fefed4308ce5c39ac23d0621d56c` |

## Qué es cada plano (no se mezclan)

| Plano | Qué hay | Cómo se obtuvo |
| --- | --- | --- |
| Fuente upstream | **ninguna**: no hay repositorio atribuido | no se puede atribuir sin recibo de build |
| Artefacto observado | 12 chunks JS servidos por `https://nof1.ai/`, digest de directorio `5fbc183a…544b9` | descarga directa + `analyze-javascript-application` |
| Conducta observada | carga de página en perfil vacío, captura de viewport, 43 scripts inventariados | CDP loopback |
| Conducta no observada | todo lo que ocurre tras un clic autenticado o una petición al modelo | `UNKNOWN` |

## Lo que el artefacto dice de sí mismo

- Es un build **Next.js App Router** empaquetado con **Turbopack**: `__NEXT` en 9 de 12
  chunks, `turbopack` en 7, rutas `_next/static` en 3.
- Los chunks están minificados y **sin source maps accesibles**: no hay nombres de módulo.
- Cero ocurrencias de identificadores del proyecto `195440/nof1.ai` (`open-nof1`, `voltagent`,
  `gate-api`, `195440`, `vt_`).

## Por qué este dossier ya no cruza con ninguna fuente

La v3 cruzaba estos chunks con el árbol TypeScript de `195440/nof1.ai`. Ese cruce se midió y
se refutó (`../T-NF-NOF1/PROVENANCE.md`): un repositorio cuyo build es `tsdown` y que no
contiene Next.js en ningún fichero no puede producir chunks de Turbopack.

Por tanto aquí no hay una fila "fuente" que correlacionar. Escribir una sería inventarla.

## Lo que sí se puede correlacionar: estructura observada ↔ nuestro runtime

| rasgo observado | nuestro runtime | veredicto |
| --- | --- | --- |
| frontend Next.js con chunks separados y sin source maps | no aplica: no tenemos frontend de aplicación | `NOT_COMPARABLE` |
| bundle minificado servido por CDN | no aplica | `NOT_COMPARABLE` |
| cadena gráfico→modelo→decisión | no observable desde fuera: REA no ejecuta el JS | `UNKNOWN` |

## Conclusión

`NO_ADOPTION`. No por sospecha, sino por imposibilidad de atribución: sin saber de qué
código sale un artefacto, ni se adopta su patrón ni se rechaza su diseño. Y, sobre todo, no se
etiqueta con el nombre de un repositorio que no lo produjo.
