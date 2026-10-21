# RUN REPORT — WP-PAPER-QUOTE-GAP-002

- Generado: `2026-10-21T09:02:37Z`
- Rama: `wp/paper-resume-001` · base `fefb0771036c`
- Modo: **PAPER** · `live_orders = 0` · modelo real llamado: `False`
- `false_success = 0`

## Checks (ejecutados, con su exit code)

| # | comando | resultados | exit | s |
| --- | --- | --- | --- | --- |
| 1 | `python.exe -m pytest tests/unit/vision/test_gap_recovery.py tests/unit/vision/test_gap_recovery_venue.py tests/unit/vision/test_durable_book.py tests/unit/vision/test_session_recovery.py tests/unit/vision/test_prospective_session.py tests/unit/vision/test_session_durable.py -q -p no:warnings` | 90 passed | 0 | 93.9 |
| 2 | `python -m pytest tests/unit/vision tests/unit/paper tests/unit/risk tests/unit/market_data -q -p no:warnings` | 694 passed | 0 | None |
| 3 | `python.exe -m pytest tests/unit/vision/test_minute_quote_feed.py tests/unit/vision/test_subbar_execution.py -q -p no:warnings` | 22 passed | 0 | 50.5 |
| 4 | `python.exe -m ruff check src/trading_bot/vision/gap_recovery.py src/trading_bot/vision/durable.py src/trading_bot/vision/lane.py src/trading_bot/vision/quotes.py src/trading_bot/vision/prospective.py src/trading_bot/paper/broker.py src/trading_bot/risk/manager.py scripts/quote_gap_lab.py scripts/verify_quote_gap.py scripts/quote_feed_source.py scripts/make_quote_gap_evidence.py tests/unit/vision/test_gap_recovery.py tests/unit/vision/test_gap_recovery_venue.py tests/unit/vision/test_durable_book.py tests/unit/vision/test_session_recovery.py tests/unit/vision/test_prospective_session.py tests/unit/vision/test_session_durable.py` | — | 0 | 0.1 |
| 5 | `python.exe -m mypy src/trading_bot/vision/gap_recovery.py src/trading_bot/vision/durable.py src/trading_bot/vision/lane.py src/trading_bot/vision/quotes.py src/trading_bot/vision/prospective.py src/trading_bot/paper/broker.py src/trading_bot/risk/manager.py` | — | 0 | 0.7 |
| 6 | `python.exe scripts/quote_feed_source.py verify` | — | 0 | 0.7 |
| 7 | `python.exe scripts/verify_quote_gap.py --lab C:\Users\GVLLFR0035\Downloads\bot-freebuff-resume\reports\ai-bots\WP-PAPER-QUOTE-GAP-002\lab\GAP_LAB.json --negative-controls --json C:\Users\GVLLFR0035\Downloads\bot-freebuff-resume\reports\ai-bots\WP-PAPER-QUOTE-GAP-002\VERIFICATION.json` | — | 0 | 0.2 |

## Artefactos

- Laboratorio: `reports\ai-bots\WP-PAPER-QUOTE-GAP-002\lab\GAP_LAB.json` (`9970d07d9b0cc593…`), ok=`True`
  - **both**: A=RAN · B=BLOCKED (GAP_EXIT_AMBIGUOUS) · economía=None · cuerpo=None
  - **partial**: A=RAN · B=BLOCKED (GAP_NOT_COVERED) · economía=None · cuerpo=None
  - **quiet**: A=RAN · B=RAN · economía=True · cuerpo=True
  - **split**: A=RAN · B=RAN · economía=True · cuerpo=True
  - **stop**: A=RAN · B=RAN · economía=True · cuerpo=True
  - **take**: A=RAN · B=RAN · economía=True · cuerpo=True
- Verificación independiente: `reports\ai-bots\WP-PAPER-QUOTE-GAP-002\VERIFICATION.json` (`55f3381ad1406aa1…`), 83 checks, 10 controles negativos
- Drill sobre minutos reales: `reports\ai-bots\WP-PAPER-QUOTE-GAP-002\drill\DRILL.json` (`5fbd50b393c04c8e…`), veredicto `PASS`, digests iguales=True

## Runtime hasheado

- `src/trading_bot/vision/gap_recovery.py` · `f813d7f5d9072a0c43aa2a4e6449a880d426775104e57f951039d81b9844c5d2`
- `src/trading_bot/vision/durable.py` · `3e023540ba3fd08d19dd0b81b2a9b458384a23731d50e53b74773ce996dd50a9`
- `src/trading_bot/vision/lane.py` · `7928ce5b7599ae148af5ab66b18f23edf6f2144e54349a85c63ae40b827ade51`
- `src/trading_bot/vision/quotes.py` · `62c59ec1a4f1e8d6eba131b292d81b59a70809e91f7c31c569d52fd70dd7b1ca`
- `src/trading_bot/vision/prospective.py` · `2e4c026db6e20a83e8819da85b5acbfa04096928046c286bbe4a967e0a7ef41b`
- `src/trading_bot/paper/broker.py` · `3cb099fa72bd052ddb1e2340d0c02ee3799aa4dd8eb4395faed9a49f86814e1f`
- `src/trading_bot/risk/manager.py` · `ee8e84c38a00be80ccafbd4168e6d0a8180a2829b288e7345140d0b33b41473a`
