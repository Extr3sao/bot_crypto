# Transcripción de la verificación original de 003G (preservación)

**Qué es.** El contenido de `reports/ai-bots/RFC-AI-BOTS-003G/session/VERIFICATION.md` **tal como
estaba antes** de que este WP lo sobrescribiera con una re-ejecución del verificador de 003G.
Se transcribe desde la lectura hecha a las 08:15Z del 2026-10-19, antes de la re-ejecución.

**Qué no es.** No es un artefacto restaurado: el fichero original se perdió y éste es un
**transcrito**. La diferencia importa y por eso se declara (ver `STATE_AUDIT.md` §7, incidente
003H-D6). El `VERIFICATION.json|md` que hoy vive en el directorio de 003G es la
**re-verificación** (24 PASS / 1 FAIL) que refleja el drift de runtime provocado por 003H.

```text
# Independent verification — RFC-TAP-AI-BOTS-003G

**Session:** `reports\ai-bots\RFC-AI-BOTS-003G\session`
**Checks:** 25 PASS / 0 FAIL (25 total)

> Verifier: `scripts/ai_bots_003g_verify.py`. It imports no `trading_bot` module and
> recomputes every claim from the raw JSONL. It is written by the builder, so it is
> not a substitute for a second independent agent (`BUILDER != VERIFIER`).

| # | check | result | detail |
| --- | --- | --- | --- |
| 1 | `stream_chain_intact` | PASS | 11 chained rows |
| 2 | `session_is_paper` | PASS | mode=PAPER live_enabled=False |
| 3 | `subbar_enabled_for_paper_only` | PASS | subbar_entries=PAPER_ONLY |
| 4 | `tested_runtime_equals_used_runtime` | PASS | all runtime hashes match |
| 5 | `no_live_order_route_in_runtime` | PASS | no order endpoint or order call in the runtime set |
| 6 | `every_stored_minute_is_closed` | PASS | no forming bar was stored |
| 7 | `minutes_strictly_increasing` | PASS | no duplicate or out-of-order minute in any store |
| 8 | `a_cycle_was_executed` | PASS | 8 executed cycles |
| 9 | `data_time_le_decision_time` | PASS | ok |
| 10 | `declared_delay_is_inside_the_wait` | PASS | declared delivery delay respected |
| 11 | `published_series_rebuilds_from_minutes` | PASS | per-cycle series digests match |
| 12 | `cycle_ledgers_are_chained` | PASS | chains intact |
| 13 | `subbar_fills_are_observed_prices` | PASS | fill price = 1m open at or after the answer |
| 14 | `entry_bar_range_is_post_fill` | PASS | range rebuilt minute by minute |
| 15 | `at_least_one_subbar_fill` | PASS | 6 sub-bar fill rows across the session, 1 in the last ledger |
| 16 | `fills_have_an_approved_risk_gate` | PASS | every fill joins an approved decision |
| 17 | `close_pnl_identity_holds` | PASS | net = gross - commissions - execution cost |
| 18 | `no_past_decision_changed` | PASS | prefix determinism checked |
| 19 | `summary_net_matches_ledger` | PASS | summary=0 ledger=0 |
| 20 | `summary_fills_match_ledger` | PASS | summary=1 ledger=1 |
| 21 | `summary_closed_match_ledger` | PASS | summary=0 ledger=0 |
| 22 | `no_live_orders_recorded` | PASS | every stream row records live_orders=0 |
| 23 | `no_live_mode_in_any_artifact` | PASS | no artefact claims LIVE |
| 24 | `receipt_is_never_before_the_close` | PASS | 552 minutes with a positive delivery latency |
| 25 | `manifest_matches_the_minute_bytes` | PASS | each store's sha256 matches the manifest |
```

**Qué se conserva y qué cambió**

- Los **bytes de la sesión** (minutos, stream, ledgers, resúmenes, comparaciones) están intactos:
  la re-verificación de hoy recomputa los checks 1-3 y 5-25 desde ellos y vuelven a pasar.
- Lo que cambió es el check 4: `tested_runtime_equals_used_runtime` compara los hashes que la
  sesión guardó con los ficheros del árbol, y 003H cambió `lane.py` y `prospective.py` después.
  El detalle está en `STATE_AUDIT.md` §6.1.
