# Isolation contract — WP-003-02

This is **not** a preregistration sealed before the work: it was written with the
implementation, and saying otherwise would be a false claim about chronology. What it does
is fix, per scenario, what counts as success *before the battery is run against the
evidence commit*, and it names what the policy cannot do.

## Oracles

| ID | Attempt | PASS means | Not PASS means |
|---|---|---|---|
| ISO-00 | Run `scripts/ai_bots_run.py --mode mock` under the policy | exit 0, report `EXECUTED`, policy strict, zero audited attempts | the runtime cannot run isolated, or it tried to reach out |
| ISO-01 | `CCXTExchangeConnector.create_order` and `cancel_order` on a fake venue | both raise `ISO_ORDER_ROUTE`, the fake venue is never called | any call reaches the venue object |
| ISO-02 | `BitunixFuturesClient.place_order` and `BitunixFuturesConnector.create_order` | refused with `ISO_ORDER_ROUTE`, zero HTTP requests | a request is attempted |
| ISO-03 | `BitunixSpotConnector.create_order` / `cancel_order` | refused with `ISO_ORDER_ROUTE`, client untouched | the unsupported-operation error is reached first (the gate must come before it) |
| ISO-04 | `app._cmd_place_order`, with and without `--confirm-live`, in a paper process | exit 2 in both cases, the gate refuses when reached directly, no audited attempt | an order is constructed, or a socket is opened |
| ISO-05 | external connect, loopback connect, external DNS, loopback DNS | all four denied by the hook, `api.binance.com` recorded in the log | any attempt is allowed, or the host is not recorded |
| ISO-06 | `urllib.request.urlopen` and `http.client.HTTPSConnection` | both denied by the same hook | either one connects |
| ISO-07 | construct `ccxt.binance` and call it | construction with no I/O, first call denied — or the constructor itself denied | any call completes |
| ISO-08 | flip `TRADING_BOT_MODE`, set disarm flags, reinstall a permissive policy | traffic still denied; reinstall refused with `ISO_POLICY_REDEFINED` | the policy can be weakened at runtime |
| ISO-09 | start a child interpreter that connects | **LIMITATION by construction**: parent denied, child attempted | declared PASS (that would be a false success) |

## Invariants

1. A refusal happens before the venue object is used: the fake venue counters must be 0.
2. No scenario uses a credential. The only key material in the tree is the literal
   `not-a-key`/`not-a-secret` passed to the ccxt constructor in ISO-07.
3. No external host is contacted: every audited external event is denied and nothing uses
   loopback-only exceptions in the strict policy.
4. `OS_SANDBOX = NOT_AVAILABLE` is a measured value, not a placeholder: ISO-09 shows the
   child leaving the barrier.
5. A scenario that cannot run is `FAILED`, never skipped silently.

## Assumptions that would invalidate the result

- The runtime is started through one of the two entry points that install the policy. A
  process that imports an adapter without starting the runtime is outside the claim and is
  named as such in `runtime_authority_map.md`.
- `sys.addaudithook` fires for the socket and urllib paths on this CPython. ISO-05..ISO-07
  measure that rather than assuming it.
- The gate's decision is based on the policy and `TRADING_BOT_MODE`; a caller that clears
  both and constructs an adapter directly is outside the claim, and the OS sandbox that
  would cover it is not available here.
