# Baseline Debt — Configuration Expectation Mismatch

## Reproduction

Fresh detached checkout from MA-1 final commit:

```text
uv run pytest -q
609 passed, 1 failed
```

Failure:

```text
tests/unit/config/test_settings.py::test_load_settings_happy_path
assert settings.exchange.id == "binance"
actual: "bybit"
```

## Determination

The failure is independently reproducible from a clean checkout and is outside
MA-0/MA-1. No configuration file, settings loader, exchange default, risk path,
paper broker, strategy runtime, or live execution code was modified for this
checkpoint.

## Certification handling

- MA-0 focused and MA-1 communication gates remain PASS.
- The full regression is reported as `609 passed / 1 baseline failure`.
- The failure is not converted into a false PASS.
- Resolution belongs to a separate configuration baseline-debt ticket.
