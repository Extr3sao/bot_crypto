# INDEPENDENCE AUDIT — EXP-003O

`BUILDER != VERIFIER` is enforced as three mechanical facts, not as a promise:

1. **Imports.** `scripts/exp_003o_rebuilder.py` imports:

```text
__future__
argparse
collections
exp_003o_contract
gzip
hashlib
json
math
numpy
numpy.typing
pathlib
sys
typing
```

- forbidden imports found: `none`
- forbidden literals found: `none`
- shared contract module(s): `['exp_003o_contract']` — cell ids, states, writers, a bar dataclass and a digest helper; no rule, threshold or indicator.

2. **Audit hook.** The rebuilder was executed under `sys.addaudithook` with any `open` of a
published signal file, screening, validation or `*evaluations*` path turned into a hard
error. Result: `True`.

3. **The hook can fail.** A deliberately cheating script that opens
`analysis/SIGNALS.jsonl.gz` of EXP-003N was run under the same hook and was stopped:
`True`.

## What this does not prove

- Two implementations written by the same author can share a misconception. Parity shows
  agreement, not truth; the PIT audit and the hand-computed fixtures are what push against
  that, and they are bounded by the same author.
- The verifier is a program written after both builders. It shares no code with them, but
  it is not an external reviewer.

the verifier is a program written after the builders; BUILDER != VERIFIER holds as two programs, not as two people
