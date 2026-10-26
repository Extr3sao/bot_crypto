# REPLAY_REPORT — RFC-TDM-014A

**Commit de implementación:** `7a4593cb81ea659ce860215a4dbe17abbdad6a7e`
**Generado:** 2026-10-26T08:46:24Z

## Ejecuciones

| run_id | EOL | estado | duración | fases | outputs probados |
| --- | --- | --- | --- | --- | --- |
| `tdm14a-lf-20261025T181821Z` | `core.autocrlf=false` | PASS | 419.7 s | review PASS 106.5s / timeout 1800.0s, inventory PASS 312.8s / timeout 2400.0s | 5/5 |
| `tdm14a-crlf-20261025T182823Z` | `core.autocrlf=true` | PASS | 386.1 s | review PASS 124.0s / timeout 1800.0s, inventory PASS 261.5s / timeout 2400.0s | 5/5 |

Comandos exactos por fase (logs completos en `.replay-logs/<label>/` dentro de cada clon):

- `LF` · `python.exe scripts/tdm12_review.py` → exit 0
- `LF` · `python.exe scripts/tdm12_inventory.py --fingerprint-scheme v2 --source-commit 7a4593cb81ea659ce860215a4dbe17abbdad6a7e --out-dir C:\Users\GVLLFR0035\Downloads\tdm14a-run-lf\.replay-out\lf --run-id tdm14a-lf-20261025T181821Z` → exit 0
- `CRLF` · `python.exe scripts/tdm12_review.py` → exit 0
- `CRLF` · `python.exe scripts/tdm12_inventory.py --fingerprint-scheme v2 --source-commit 7a4593cb81ea659ce860215a4dbe17abbdad6a7e --out-dir C:\Users\GVLLFR0035\Downloads\tdm14a-run-crlf\.replay-out\crlf --run-id tdm14a-crlf-20261025T182823Z` → exit 0

## Aislamiento

| run | eliminado antes de ejecutar | estado inyectado previo |
| --- | --- | --- |
| `tdm14a-lf-20261025T181821Z` | [] | no |
| `tdm14a-crlf-20261025T182823Z` | ['.tdm12'] | sí: ['cell_metrics.json', 'review.json'] |

Ninguna fase se invocó con `--reuse`: `review.json` y `cell_metrics.json` estaban ausentes
antes de su ejecución y su `mtime` es posterior al inicio del run.

## Contratos comparados (ACC-07)

| contrato | publicado | run A | run B | A=B | A=publicado |
| --- | --- | --- | --- | --- | --- |
| `trades` | 115 | 115 | 115 | True | True |
| `gross_mean` | -12.577 | -12.577 | -12.577 | True | True |
| `net_mean` | -36.3676 | -36.3676 | -36.3676 | True | True |
| `day_clustered_ci95_gross` | {"lo": -23.2174, "hi": -3.101, "se": 5.2335, "day_clusters"… | {"lo": -23.2174, "hi": -3.101, "se": 5.2335, "day_clusters"… | {"lo": -23.2174, "hi": -3.101, "se": 5.2335, "day_clusters"… | True | True |
| `net_upper_bound_by_method` | {"1d": -26.8916, "2d": -26.695, "5d": -29.4407, "10d": -31.… | {"1d": -26.8916, "2d": -26.695, "5d": -29.4407, "10d": -31.… | {"1d": -26.8916, "2d": -26.695, "5d": -29.4407, "10d": -31.… | True | True |
| `per_asset` | {"BTC": {"trades": 36, "gross_mean": -8.1873, "share": 0.31… | {"BTC": {"trades": 36, "gross_mean": -8.1873, "share": 0.31… | {"BTC": {"trades": 36, "gross_mean": -8.1873, "share": 0.31… | True | True |
| `lookahead_advantage_bps` | 29.6308 | 29.6308 | 29.6308 | True | True |
| `independence_status` | INDEPENDENCE_NOT_DEMONSTRATED | INDEPENDENCE_NOT_DEMONSTRATED | INDEPENDENCE_NOT_DEMONSTRATED | True | True |
| `CANDIDATE_REGISTRY.json` | null | [] | null | True | n/a |
| `DATA_WINDOW_REGISTRY.json` | true | [] | null | True | True |

**Contratos que pasan: 10/10**
`metrics_by_cell` igual entre runs: True · igual al publicado: True

## Prueba cruzada EOL

- módulos comparados: 7
- con bytes físicos distintos: 7
- con el mismo blob de Git: 7
- con el mismo `source_fingerprint` v2: 7
- `parameter_hash` de registro iguales entre runs: True
- el digest publicado coincide con el recalculado por el verificador: True

**Estado del replay: PASS**
