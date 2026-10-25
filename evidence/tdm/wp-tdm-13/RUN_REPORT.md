# RUN_REPORT — RFC-TDM-013 (verificación independiente y reproducibilidad de TDM-12)

**Run id:** `tdm13-a96e9c80` · **Commit auditado:** `a96e9c80` · **Baseline:** `504256ec` · **Rama:** `evidence/tdm13`

## Estado de cada fase

| Fase | Estado | Detalle |
| --- | --- | --- |
| WP-13A integridad Git | **PASS** | 16/16 digests, 14/14 entregables, 17/17 campos |
| WP-13A claims | **PASS** | 16/16 re-derivados |
| WP-13B inputs | **AVAILABLE** | 26 archivos, 10310475 bytes sellados |
| WP-13B replay | **PASS** | clon `ds\tdm13-clean` durante 1.7 s |
| WP-13C controles negativos | **PASS** | 6/6 demostrados |
| Dictamen | **VERIFIED_REPRODUCIBLE** | ver `verification_result.json` |

## Comandos ejecutados

| # | Comando | Exit | Duración (s) |
| --- | --- | --- | --- |
| 1 | `-m ruff check scripts/tdm13_independent_verify.py scripts/tdm13_inputs.py scripts/tdm13_replay.py scripts/tdm13_negative_controls.py scripts/tdm13_report.py tests/unit/research/test_tdm13_independent_verify.py` | 0 | 0.2 |
| 2 | `-m ruff format --check scripts/tdm13_independent_verify.py scripts/tdm13_inputs.py scripts/tdm13_replay.py scripts/tdm13_negative_controls.py scripts/tdm13_report.py tests/unit/research/test_tdm13_independent_verify.py` | 0 | 0.2 |
| 3 | `-m pytest tests/unit/research/test_tdm13_independent_verify.py -q` | 0 | 1.5 |
| 4 | `scripts/tdm13_inputs.py verify` | 0 | 3.0 |
| 5 | `scripts/tdm13_independent_verify.py audit-git` | 0 | 2.6 |
| 6 | `scripts/tdm13_independent_verify.py audit-claims` | 0 | 0.6 |
| 7 | `scripts/tdm13_negative_controls.py` | 0 | 31.9 |
| 8 | `scripts/tdm13_independent_verify.py verify` | 0 | 0.2 |

## Replay: qué se comparó

| Artefacto | Campo | Publicado | Reproducido | ¿Igual? |
| --- | --- | --- | --- | --- |
| `review.json` | `trades` | `115` | `115` | sí |
| `review.json` | `gross_mean` | `-12.577` | `-12.577` | sí |
| `review.json` | `net_mean` | `-36.3676` | `-36.3676` | sí |
| `review.json` | `day_clustered_ci95_gross` | `{'lo': -23.2174, 'hi': -3.101, 'se': 5.2335, 'day_clusters': 26}` | `{'lo': -23.2174, 'hi': -3.101, 'se': 5.2335, 'day_clusters': 26}` | sí |
| `review.json` | `net_upper_bound_by_method` | `{'1d': -26.8916, '2d': -26.695, '5d': -29.4407, '10d': -31.5307}` | `{'1d': -26.8916, '2d': -26.695, '5d': -29.4407, '10d': -31.5307}` | sí |
| `review.json` | `per_asset` | `{'BTC': {'trades': 36, 'gross_mean': -8.1873, 'share': 0.313}, 'ETH': {'trades': 35, 'gross_mean': -19.2816, 'share': 0.304}, 'SOL': {'trades': 44, 'gross_mean': -10.8353, 'share': 0.383}}` | `{'BTC': {'trades': 36, 'gross_mean': -8.1873, 'share': 0.313}, 'ETH': {'trades': 35, 'gross_mean': -19.2816, 'share': 0.304}, 'SOL': {'trades': 44, 'gross_mean': -10.8353, 'share': 0.383}}` | sí |
| `review.json` | `lookahead_advantage_bps` | `29.6308` | `29.6308` | sí |
| `review.json` | `independence_status` | `INDEPENDENCE_NOT_DEMONSTRATED` | `INDEPENDENCE_NOT_DEMONSTRATED` | sí |
| `CANDIDATE_REGISTRY.json` | `<whole document, ephemeral keys removed>` | `None` | `None` | sí |
| `DATA_WINDOW_REGISTRY.json` | `<whole document, ephemeral keys removed>` | `None` | `None` | sí |

## Controles negativos

| ID | Inyección | Exit | Control esperado | Estado |
| --- | --- | --- | --- | --- |
| NC-01 | mutated dataset byte | 1 | `FAIL` | **PROVEN** |
| NC-02 | required dataset removed | 1 | `missing` | **PROVEN** |
| NC-03 | altered claim in RUN_REPORT.json | 1 | `net_mean_matches_manifest` | **PROVEN** |
| NC-04 | non-ancestor baseline commit | 1 | `target_parent_is_baseline` | **PROVEN** |
| NC-05 | altered evidence blob | 1 | `BASELINE_AND_SCOPE.md` | **PROVEN** |
| NC-06 | inventory/review timeout | 1 | `TIMEOUT` | **PROVEN** |

## Límites de este informe

- **Independencia de identidad:** `NOT_DEMONSTRATED`. La ruta de código del verificador es
  propia (no importa ni ejecuta `tdm12_publish.py --verify`), pero la escribió el mismo
  operador que construyó TDM-12. No se declara un segundo autor que no existe.
- **Alcance de la reproducibilidad:** demuestra que los números publicados vuelven a salir
  de los inputs sellados con el código sin modificar. **No** demuestra que el pipeline sea
  correcto, ni que la estrategia tenga alpha.
- **Datos:** licencia y endpoint de captura `UNKNOWN`; re-descargar hoy no garantiza los
  mismos bytes que la copia sellada.
- **Autorreferencia:** este informe no contiene el SHA del commit que lo contiene; el cierre
  se prueba con `python scripts/tdm13_independent_verify.py audit-closure`.

`paper_orders = 0` · `live_orders = 0` · `FALSE_SUCCESS = 0` dentro del alcance comprobado.
