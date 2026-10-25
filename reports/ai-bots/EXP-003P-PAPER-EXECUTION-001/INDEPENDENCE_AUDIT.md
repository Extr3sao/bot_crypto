# INDEPENDENCE AUDIT — EXP-003P

- `program_independence`: **True**
- `organizational_independence`: **False**
- verifier: `scripts/exp_003p_verify.py` (`395c21d830126703…`)

## Why program independence holds

The verifier imports the standard library and the frozen contract only. The
hash chain, the accounting and the state machine are re-implemented inside it
from the published format; it does not call the producer's store, engine, ledger
or reconciliation.

```text
imports_producer_modules: []
```

## Why organisational independence does not

one agent wrote the producer, the verifier and the controls; the separation is between programs, not between people, and is reported as such

## Producer programs

| program | sha256 |
| --- | --- |
| `src/trading_bot/paper/lifecycle/contracts.py` | `32a4720e85b24669…` |
| `src/trading_bot/paper/lifecycle/store.py` | `46eb1ce9adc42066…` |
| `src/trading_bot/paper/lifecycle/engine.py` | `0015e82fe302c0c6…` |
| `src/trading_bot/paper/lifecycle/venue.py` | `6e615bd6aaf5b1c6…` |
| `src/trading_bot/paper/lifecycle/reconcile.py` | `ecb32c4f38fea9f5…` |
| `src/trading_bot/paper/lifecycle/recorder.py` | `33192f6e7e642ce2…` |
| `scripts/exp_003p_rehearsal.py` | `9ff5deb966d941fe…` |

## Shared surface

- src/trading_bot/paper/lifecycle/contracts.py (producer only; verifier transcribes the tables)
- scripts/exp_003p_contract.py (frozen data: paths, windows, scenarios)
- the documented canonical-JSON and chain formats
