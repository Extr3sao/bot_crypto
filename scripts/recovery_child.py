"""recovery_child — one paper session in one process, so a crash is a crash.

The runner (``scripts/recovery_lab.py``) starts this process, arms a failpoint through the
environment and reads what it wrote. Nothing here is a mock: the lane, the broker, the risk
manager, the ledger and the book are the production objects, reached through the same
constructor the regression suite uses.

Exit codes are part of the contract:

``0``   the session ran to the end
``2``   the runtime refused (blocked recovery, busy lock, corrupt book, operation conflict)
``86``  a failpoint ended the process (``os._exit``, no unwinding)
``3``   anything unforeseen — the evidence records the traceback rather than hiding it
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_bot.config.settings import load_settings  # noqa: E402
from trading_bot.research.economic_recovery.experiments import Bar  # noqa: E402
from trading_bot.vision.durable import (  # noqa: E402
    CorruptBook,
    LaneBookStore,
    RecoveryBlocked,
    SessionBusy,
    closed_digest,
    pid_alive,
)
from trading_bot.vision.lane import VisionLane  # noqa: E402
from trading_bot.vision.ledger import OperationConflict, read_entries, verify_chain  # noqa: E402
from trading_bot.vision.provider import ReplayProvider, VisionResponse  # noqa: E402
from trading_bot.vision.quotes import MINUTE_MS, MinuteBarQuoteFeed, MinuteSeries  # noqa: E402
from trading_bot.vision.settings import load_vision_config  # noqa: E402

HOUR_MS = 3_600_000
START_MS = int(datetime(2026, 10, 20, tzinfo=UTC).timestamp() * 1000)
SYMBOL = "BTC/USDT"
STOP_PCT = 0.5
TAKE_PCT = 0.75

FLAT = [(100.0, 100.0)] * 21
OPEN_AT_END = [*FLAT, (100.0, 100.3)]
EXTEND_STOP = [*OPEN_AT_END, (100.3, 99.0), (99.0, 99.0)]
EXTEND_FLAT = [*OPEN_AT_END, (100.3, 100.3)]


def _answer(symbol: str, action: str) -> str:
    stop = STOP_PCT if action not in {"NO_TRADE", "CLOSE"} else None
    take = TAKE_PCT if action not in {"NO_TRADE", "CLOSE"} else None
    return (
        f'{{"schema_version":"ai-vision-decision/1","symbol":"{symbol}","action":"{action}",'
        f'"confidence":0.6,"horizon_bars":6,"stop_loss_pct":{stop},"take_profit_pct":{take},'
        '"invalidation":null,"rationale":"Recuperación transaccional PAPER."}'
    )


class ScriptedProvider(ReplayProvider):
    """One scripted answer per call, repeating the last one when the list runs out."""

    def __init__(self, actions: list[str]) -> None:
        self._actions = list(actions) or ["NO_TRADE"]
        self.seen = 0
        super().__init__(self._script)

    def _script(self, request) -> str:  # type: ignore[no-untyped-def]
        index = min(self.seen, len(self._actions) - 1)
        return _answer(request.chart.symbol, self._actions[index])

    def analyze(self, request) -> VisionResponse:  # type: ignore[override]
        response = super().analyze(request)
        self.seen += 1
        return response


def _bars(path: list[tuple[float, float]]) -> list[Bar]:
    out: list[Bar] = []
    for index, (opened, closed) in enumerate(path):
        pad = 0.0005
        out.append(
            Bar(
                ts_ms=START_MS + index * HOUR_MS,
                open=opened,
                high=max(opened, closed) * (1.0 + pad),
                low=min(opened, closed) * (1.0 - pad),
                close=closed,
                volume=100.0 + index,
            )
        )
    return out


def _holed(bars: list[Bar]) -> list[Bar]:
    """The 1-hour grid with the 22nd bar missing: the hole the minutes have to cover."""
    return [bar for index, bar in enumerate(bars) if index != 22]


def _hole_series(*, low: float | None = None, high: float | None = None) -> MinuteBarQuoteFeed:
    start = START_MS + 22 * HOUR_MS
    rows = []
    for index in range(60):
        stamp = start + index * MINUTE_MS
        minute_low = 99.6 if low is None or index != 15 else low
        minute_high = 100.4 if high is None or index != 15 else high
        rows.append([stamp, 100.0, minute_high, minute_low, 100.0, 1.0])
    return MinuteBarQuoteFeed({SYMBOL: MinuteSeries.from_rows(SYMBOL, rows)})


def _config():  # type: ignore[no-untyped-def]
    base = load_vision_config(env={})
    return base.__class__(
        provider=base.provider,
        lane=base.lane.__class__(
            timeframe="1h",
            window_bars=20,
            decision_every_bars=1,
            max_calls_per_run=50,
            max_estimated_spend_usd=1.0,
            data_delay_ms=0,
        ),
    )


def _deny_network(root: Path) -> dict[str, object]:
    """Refuse every outbound socket in this process, and record the attempt.

    An audit hook, not a spy on one method: ``ccxt.binance({...})`` opens its HTTP session
    in the constructor (the RFC003 incident), and a method spy would not have seen it. The
    hook is process-wide and cannot be removed once installed.
    """
    log = root / "network.jsonl"
    state: dict[str, object] = {"attempts": 0, "denied": 0, "path": str(log)}
    denied_events = {
        "socket.connect",
        "socket.getaddrinfo",
        "socket.gethostbyname",
        "urllib.Request",
        "http.client.connect",
    }

    def hook(event: str, args: tuple[object, ...]) -> None:
        if event not in denied_events:
            return
        state["attempts"] = int(state["attempts"]) + 1  # type: ignore[arg-type]
        with log.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(
                json.dumps({"event": event, "pid": os.getpid(), "args": repr(args)[:200]}) + "\n"
            )
        raise PermissionError(f"network denied in the recovery laboratory: {event}")

    sys.addaudithook(hook)
    return state


def _run(args: argparse.Namespace) -> dict[str, object]:
    root = Path(args.root)
    root.mkdir(parents=True, exist_ok=True)
    state_dir = root / "state"
    store = LaneBookStore(state_dir)
    ledger_path = Path(args.ledger)
    started = time.perf_counter()

    if args.mode == "inspect":
        #: Read the disk the crash left behind, in a fresh process, without touching it.
        return {"role": "inspect"}

    if args.mode == "lock-only":
        lock = store.lock(session_id=args.session)
        try:
            time.sleep(max(0.0, args.hold_lock_ms / 1000.0))
        finally:
            lock.release()
        return {"role": "lock-holder", "held_ms": args.hold_lock_ms}

    if args.mode == "network-probe":
        from trading_bot.app import _cmd_place_order

        result: dict[str, object] = {}
        try:
            code = _cmd_place_order(argparse.Namespace(**{"confirm_live": False}))
            result["place_order_exit"] = int(code)
        except SystemExit as exc:  # argparse-driven refusals
            result["place_order_exit"] = int(exc.code or 0)
        except Exception as exc:
            result["place_order_exit"] = None
            result["place_order_error"] = f"{type(exc).__name__}: {exc}"
        #: Positive control for the deny hook itself: a loopback connect must be refused
        #: by the same audit hook that would refuse the venue. Without this the zero
        #: could mean "no attempt" or "no guard", and the two are not the same claim.
        import socket

        try:
            socket.create_connection(("127.0.0.1", 9), timeout=0.01).close()
            result["deny_probe"] = "CONNECTED_UNEXPECTEDLY"
        except PermissionError as exc:
            result["deny_probe"] = "DENIED"
            result["deny_probe_detail"] = str(exc)
        except OSError as exc:
            result["deny_probe"] = f"OS_ERROR:{type(exc).__name__}"
        result["role"] = "network-probe"
        return result

    book = store.load() if args.role == "resume" else None
    lock = store.lock(session_id=args.session)
    try:
        series = _bars(EXTEND_STOP)
        if args.bars == "open_at_end":
            series = _bars(OPEN_AT_END)
        elif args.bars == "extend_flat":
            series = _bars(EXTEND_FLAT)
        elif args.bars == "holed":
            series = _holed(_bars(EXTEND_STOP))
        feed = None
        if args.feed == "stop_hole":
            feed = _hole_series(low=99.0)
        elif args.feed == "take_hole":
            feed = _hole_series(high=101.5)
        elif args.feed == "quiet_hole":
            feed = _hole_series()
        lane = VisionLane(
            series={SYMBOL: series},
            provider=ScriptedProvider(
                ["NO_TRADE"] if args.role == "resume" else ["LONG", "NO_TRADE"]
            ),
            config=_config(),
            risk_policy=load_settings(config_dir=REPO / "config", env_file=None).risk,
            ledger_path=ledger_path,
            equity=10_000.0,
            book_id=args.book_id,
            decision_every_bars=1,
            book_store=store,
            book=book,
            session_id=args.session,
            quote_feed=feed,
        )
        summary = lane.run()
    finally:
        lock.release()

    return {
        "role": args.role,
        "session": args.session,
        "summary": summary,
        "ledger_stats": {
            "duplicates_suppressed": int(lane.ledger.duplicates_suppressed),
            "tail_repair": lane.ledger.tail_repair,
        },
        "store_recovery": getattr(lane, "store_recovery", None),
        "elapsed_s": round(time.perf_counter() - started, 3),
    }


def _snapshot(args: argparse.Namespace, payload: dict[str, object]) -> dict[str, object]:
    root = Path(args.root)
    store = LaneBookStore(root / "state")
    payload["book"] = None
    payload["book_state_digest"] = None
    payload["barrier_ms"] = None
    try:
        book = store.load()
    except CorruptBook as exc:
        payload["book_load_error"] = str(exc)
        book = None
    if book is not None:
        payload.update(
            book=book.body,
            book_digest=book.digest,
            book_state_digest=book.state_digest,
            barrier_ms=book.barrier_ms,
            book_closed_digest=closed_digest(book.closed_trades),
        )
    ledger_path = Path(args.ledger)
    payload["ledger"] = {
        "path": str(ledger_path),
        "exists": ledger_path.exists(),
        "chain": verify_chain(ledger_path),
        "entries": read_entries(ledger_path),
        "torn": (ledger_path.with_suffix(ledger_path.suffix + ".torn.json")).exists(),
    }
    try:
        payload["events"] = [row for row in store.events()]
    except Exception as exc:
        payload["events"] = []
        payload["events_error"] = f"{type(exc).__name__}: {exc}"
    #: An empty ledger is not a projection: it has no row to compare, and asking for one
    #: would refuse every account whose ledger lives somewhere else (the RFC003 drill book
    #: is exactly that case).
    projection = ledger_path if ledger_path.exists() and ledger_path.stat().st_size > 0 else None
    try:
        payload["store_recovery"] = store.recover(ledger_path=projection)
    except Exception as exc:
        payload["store_recovery"] = {
            "status": "ERROR",
            "detail": f"{type(exc).__name__}: {exc}",
        }
    payload["files"] = sorted(path.name for path in (root / "state").glob("*"))
    payload["lock"] = {
        "exists": store.lock_path.exists(),
        "holder": _read_json(store.lock_path),
        "holder_alive": _alive(store.lock_path),
    }
    return payload


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _alive(path: Path) -> bool | None:
    holder = _read_json(path)
    if not isinstance(holder, dict):
        return None
    return pid_alive(int(holder.get("pid", 0) or 0))


def main() -> int:
    parser = argparse.ArgumentParser(description="One recovery-laboratory session, one process.")
    parser.add_argument("--root", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--role", choices=["fresh", "resume"], default="resume")
    parser.add_argument(
        "--mode", choices=["run", "inspect", "lock-only", "network-probe"], default="run"
    )
    parser.add_argument("--bars", choices=["holed", "open_at_end", "extend_flat"], default="holed")
    parser.add_argument(
        "--feed", choices=["none", "stop_hole", "take_hole", "quiet_hole"], default="stop_hole"
    )
    parser.add_argument("--session", default="run")
    parser.add_argument("--book-id", default="rfc004-lab-book")
    parser.add_argument("--hold-lock-ms", type=float, default=0.0)
    parser.add_argument("--deny-network", action="store_true")
    args = parser.parse_args()

    payload: dict[str, object] = {"argv": sys.argv[1:], "pid": os.getpid()}
    if args.deny_network:
        payload["network"] = _deny_network(Path(args.root))
    try:
        payload.update(_run(args))
        code = 0
    except (RecoveryBlocked, SessionBusy, CorruptBook, OperationConflict) as exc:
        payload["status"] = "REFUSED"
        payload["refusal"] = type(exc).__name__
        payload["detail"] = str(exc)
        report = getattr(exc, "report", None)
        payload["report"] = report.to_dict() if hasattr(report, "to_dict") else None
        code = 2
    except Exception as exc:
        payload["status"] = "ERROR"
        payload["error"] = f"{type(exc).__name__}: {exc}"
        payload["traceback"] = traceback.format_exc()
        code = 3
    try:
        _snapshot(args, payload)
    except Exception as exc:
        payload["snapshot_error"] = f"{type(exc).__name__}: {exc}"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({"out": args.out, "exit": code, "pid": os.getpid()}))
    return code


if __name__ == "__main__":
    sys.exit(main())
