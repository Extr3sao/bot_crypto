"""Measure order submissions with the boundary armed, not with a grep.

The earlier claim ("no order path exists in vision/ or paper/") was true about those two
directories and false about the process: the lane loads ``ccxt`` and the execution package
transitively, so a static argument cannot settle whether a submission happened.  What can be
settled is a count, provided the boundary is armed first and the count is zero *with the spy
in place*.

So this probe:
  1. instals an import audit hook before any project module loads,
  2. imports the lane and the broker, then **patches every submission symbol it can reach**
     (``ccxt.Exchange.create_order`` and friends, plus any ``place_order``/``create_order``/
     ``submit_order`` exposed by a ``trading_bot`` module) with a counter that refuses,
  3. runs a real lane session (open, commit, resume through a covered hole),
  4. reports how many spies were armed and how many were called.

A zero with zero spies armed proves nothing, so the payload carries ``spies_armed`` and the
verdict refuses to claim a measurement when it is 0.  It never contacts an exchange and never
reads credentials.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

SUBMISSION_NAMES = ("create_order", "place_order", "submit_order", "send_order",
                    "createOrder", "placeOrder")

loaded: set[str] = set()
armed: list[str] = []
calls: list[dict[str, Any]] = []


def _hook(event: str, args: tuple) -> None:  # noqa: ANN001 - audit hook signature
    if event == "import":
        loaded.add(str(args[0]))


#: Armed before a single project module loads, otherwise a transitively imported submission
#: module would be invisible to the probe it is supposed to expose.
sys.addaudithook(_hook)


def _repo_root() -> Path:
    override = os.environ.get("RFC_REPO")
    if override:
        return Path(override).resolve()
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src").is_dir():
            return parent
    raise SystemExit("cannot locate the repository root")


REPO = _repo_root()


def _refuse(label: str, original: Callable[..., Any]) -> Callable[..., Any]:
    def spy(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401 - transparent wrapper
        calls.append({"boundary": label, "args": repr(args)[:200],
                      "kwargs": repr(kwargs)[:200]})
        raise RuntimeError(f"order submission attempted through {label}; the probe refuses it")
    spy.__name__ = getattr(original, "__name__", "spy")
    return spy


def arm_spies() -> None:
    import ccxt  # noqa: PLC0415 - must be imported here so the hook sees it

    targets: list[tuple[Any, str, str]] = []
    for cls_name in ("Exchange", "binance", "binanceusdm"):
        cls = getattr(ccxt, cls_name, None)
        if cls is None:
            continue
        for name in SUBMISSION_NAMES:
            if hasattr(cls, name):
                targets.append((cls, name, f"ccxt.{cls_name}.{name}"))
    for module_name, module in list(sys.modules.items()):
        if not module_name.startswith("trading_bot"):
            continue
        for name in SUBMISSION_NAMES:
            obj = getattr(module, name, None)
            if callable(obj):
                targets.append((module, name, f"{module_name}.{name}"))
    for holder, name, label in targets:
        original = getattr(holder, name)
        try:
            setattr(holder, name, _refuse(label, original))
        except (AttributeError, TypeError):
            continue
        armed.append(label)


def main() -> int:
    sys.path.insert(0, str(REPO / "src"))
    sys.path.insert(0, str(REPO / "tests" / "unit" / "vision"))

    spec = importlib.util.spec_from_file_location(
        "recovery_fixtures", REPO / "tests" / "unit" / "vision" / "test_session_recovery.py")
    assert spec and spec.loader
    fixtures = importlib.util.module_from_spec(spec)
    import tempfile  # noqa: PLC0415

    spec.loader.exec_module(fixtures)

    from trading_bot.paper.broker import PaperBroker  # noqa: PLC0415

    arm_spies()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store, _, book, _ = fixtures._first_run(root, fixtures._bars(fixtures.OPEN_AT_END))
        _, _, entries = fixtures._resume(
            root, fixtures._holed_bars(fixtures.EXTEND_STOP), store,
            quote_feed=fixtures._hole_series(low=99.0))
        after = store.load()

    public = [name for name in dir(PaperBroker) if not name.startswith("_")]
    broker_submission = [name for name in public if name in SUBMISSION_NAMES]
    submission_modules = sorted(m for m in loaded
                                if m.split(".")[0] in {"ccxt", "trading_bot"}
                                and any(part in m for part in ("execution", "exchange", "live")))

    measured = bool(armed)
    payload = {
        "schema": "NO_ORDER_PROBE_V1",
        "scope": "one lane session: open a position, commit, resume through a covered hole",
        "modules_loaded": len(loaded),
        "submission_modules_loaded": submission_modules,
        "broker_public_methods": len(public),
        "broker_submission_attrs": broker_submission,
        "spies_armed": len(armed),
        "spy_boundaries": armed,
        "calls_crossed": calls,
        "order_submit_attempts": len(calls) if measured else None,
        "closes_in_resume": len(fixtures._closes(entries)),
        "open_after_resume": len(after.open_positions) if after else None,
        "verdict": ("the boundary was armed and nothing crossed it"
                    if measured and not calls
                    else "no spy could be armed; this is not a measurement"
                    if not measured
                    else "an order submission crossed the armed boundary"),
        "limitations": (
            "this measures the lane path only. src/trading_bot/app.py still exposes a gated "
            "live order command that this probe never executes, and no exchange was contacted, "
            "so external_orders remains NOT_VERIFIABLE"),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if measured and not calls else 1


if __name__ == "__main__":
    sys.exit(main())
