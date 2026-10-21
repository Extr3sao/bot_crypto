"""failpoints — crash injection at the runtime's real persistence calls.

A failpoint that lives next to a test helper proves nothing about the runtime: the RFC003
audit measured that difference (a package shadowed by ``PYTHONPATH`` made the gate refuse,
but the *runtime* path is the one that has to be interrupted). These points therefore sit
inside :mod:`trading_bot.vision.durable` and :mod:`trading_bot.vision.ledger`, on the exact
lines that write, flush, fsync and replace, and the lane arms them without a second code
path.

The defaults are what make this safe to ship:

* **off unless asked.** Nothing happens unless ``TRADING_BOT_FAILPOINT`` names a point.
* **armed only inside a sandbox.** ``TRADING_BOT_FAILPOINT_SANDBOX`` must name a directory
  that contains the file being written. A failpoint pointed at a real book is refused, not
  ignored, so a stale environment variable cannot end a live paper session.
* **a crash, not an exception.** The process ends with :func:`os._exit`: no ``finally``, no
  buffer flush, no atexit hook. An exception would let the caller catch it and continue,
  which is the one thing a crash test must not allow.

Grammar of the specification (environment, never a file inside the repo)::

    TRADING_BOT_FAILPOINT=book.after_replace
    TRADING_BOT_FAILPOINT=book.after_replace@2          # ignore the first 2 matches
    TRADING_BOT_FAILPOINT={"name":"book.after_replace","skip":1,"match":{"closed_trades":1}}

``match`` compares the keyword context the call site passes (``closed_trades``,
``kind`` …) and only fires when every key equals. Combined with ``skip`` it names one
specific write among many identical-looking ones, which is what a crash matrix needs.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_EXIT_CODE",
    "ENV_EXIT_CODE",
    "ENV_SANDBOX",
    "ENV_SPEC",
    "FAILPOINTS",
    "FailpointRefused",
    "Spec",
    "armed",
    "describe",
    "reset",
    "set_trigger_hook",
    "spec",
    "trigger",
]

ENV_SPEC = "TRADING_BOT_FAILPOINT"
ENV_SANDBOX = "TRADING_BOT_FAILPOINT_SANDBOX"
ENV_EXIT_CODE = "TRADING_BOT_FAILPOINT_EXIT"

#: Distinct from 1 so a harness cannot confuse "the test failed" with "the process was
#: killed on purpose". Windows reports it as-is for ``os._exit``.
DEFAULT_EXIT_CODE = 86

#: The complete inventory. A name that is not here cannot fire, so a typo in an
#: environment variable fails loudly instead of silently testing nothing.
FAILPOINTS = frozenset(
    {
        # ledger (the append-only projection of one session)
        "ledger.before_write",
        "ledger.after_write",
        "ledger.after_fsync",
        # the book (the economic authority)
        "book.before_save",
        "book.after_tmp_write",
        "book.after_tmp_fsync",
        "book.after_prev_copy",
        "book.after_replace",
        "book.after_dir_fsync",
        # the event log (how the book became true)
        "event.after_write",
        "event.after_fsync",
        # the lane, around the one durable write of a bar
        "bar.before_commit",
        "bar.after_commit",
        # the lock
        "lock.after_acquire",
    }
)


class FailpointRefused(RuntimeError):
    """A failpoint was armed against a path the sandbox does not contain."""


@dataclass(frozen=True, slots=True)
class Spec:
    name: str
    skip: int = 0
    match: dict[str, Any] = field(default_factory=dict)
    exit_code: int = DEFAULT_EXIT_CODE
    raw: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "skip": self.skip,
            "match": dict(self.match),
            "exit_code": self.exit_code,
        }


#: ``_RAW`` is the environment string the cache was parsed from, not a boolean flag. Keying
#: the cache on the value means a process that arms a failpoint *after* its first call (a
#: laboratory child started by a test, a monkeypatched ``pytest`` process) still observes it;
#: a boolean "already loaded" turned that into a silent no-op, which is the worst possible
#: failure mode for this module.
_UNSET = object()
_RAW: object | str = _UNSET
_CACHE: Spec | None = None
_SEEN: dict[str, int] = {}
_HOOK: Callable[[Spec], None] | None = None


def _parse(text: str) -> Spec:
    text = text.strip()
    if not text:
        raise FailpointRefused(f"{ENV_SPEC} is empty")
    if text.startswith("{"):
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as exc:
            raise FailpointRefused(f"{ENV_SPEC} is not valid JSON: {exc}") from exc
        if not isinstance(doc, dict):
            raise FailpointRefused(f"{ENV_SPEC} must be an object or a name")
        name = str(doc.get("name", ""))
        skip = int(doc.get("skip", 0) or 0)
        match = {str(key): value for key, value in dict(doc.get("match") or {}).items()}
        exit_code = int(doc.get("exit_code", DEFAULT_EXIT_CODE) or DEFAULT_EXIT_CODE)
    else:
        name, _, raw_skip = text.partition("@")
        skip = int(raw_skip) if raw_skip else 0
        match = {}
        exit_code = DEFAULT_EXIT_CODE
    name = name.strip()
    if name not in FAILPOINTS:
        raise FailpointRefused(
            f"{name!r} is not a known failpoint; known points: {', '.join(sorted(FAILPOINTS))}"
        )
    if skip < 0:
        raise FailpointRefused("skip must be >= 0")
    return Spec(name=name, skip=skip, match=match, exit_code=exit_code, raw=text)


def spec() -> Spec | None:
    """The armed failpoint (``None`` when nothing is armed), parsed once per distinct value."""
    global _CACHE, _RAW
    raw = os.environ.get(ENV_SPEC, "").strip()
    if raw != _RAW:
        _RAW = raw
        _CACHE = _parse(raw) if raw else None
    return _CACHE


def reset() -> None:
    """Forget the parsed spec and the skip counters. Tests only."""
    global _CACHE, _RAW
    _CACHE = None
    _RAW = _UNSET
    _SEEN.clear()


def set_trigger_hook(hook: Callable[[Spec], None] | None) -> None:
    """Replace ``os._exit`` with ``hook`` so a unit test can observe the fire.

    The runtime never calls this; a crash test that did would be testing the hook.
    """
    global _HOOK
    _HOOK = hook


def _inside(path: Path, sandbox: Path) -> bool:
    try:
        path.resolve().relative_to(sandbox.resolve())
    except ValueError:
        return False
    return True


def _sandbox() -> Path:
    raw = os.environ.get(ENV_SANDBOX, "").strip()
    if not raw:
        raise FailpointRefused(
            f"{ENV_SPEC} is armed but {ENV_SANDBOX} is not set: a failpoint without a "
            "sandbox could end a live session"
        )
    return Path(raw)


def armed(*, path: str | Path) -> bool:
    """``True`` when this write would be interrupted.

    Raises :class:`FailpointRefused` when the point is armed outside its sandbox, so the
    caller learns about the misconfiguration instead of running to completion.
    """
    current = spec()
    if current is None:
        return False
    if not isinstance(path, (str, Path)):
        raise FailpointRefused("failpoints.armed() requires the path being written")
    if not _inside(Path(path), _sandbox()):
        raise FailpointRefused(
            f"{current.name} is armed for {path}, which is outside {ENV_SANDBOX}: "
            "refusing to interrupt a write the laboratory was not handed"
        )
    return True


def _matches(current: Spec, context: dict[str, Any]) -> bool:
    for key, expected in current.match.items():
        if key not in context:
            return False
        actual = context[key]
        if isinstance(expected, bool) or isinstance(actual, bool):
            if bool(expected) != bool(actual):
                return False
        elif str(actual) != str(expected):
            return False
    return True


def trigger(name: str, *, path: str | Path, **context: Any) -> None:
    """Fire ``name`` if it is armed for ``path`` and its context matches.

    A no-op when nothing is armed, which is every production and test run. The skip
    counter counts only *fully matching* triggers, so ``skip=1`` means "the second write
    that matches", not "the second call to this function".
    """
    current = spec()
    if current is None or current.name != name:
        return
    if not armed(path=path):
        return
    if not _matches(current, context):
        return
    seen = _SEEN.get(name, 0)
    if seen < current.skip:
        _SEEN[name] = seen + 1
        return
    _SEEN[name] = seen + 1
    if _HOOK is not None:
        _HOOK(current)
        return
    os._exit(current.exit_code)


def describe() -> dict[str, Any]:
    """The armed point, for evidence. Never contains a path outside the sandbox."""
    current = spec()
    if current is None:
        return {"armed": False}
    return {
        "armed": True,
        **current.to_dict(),
        "sandbox": os.environ.get(ENV_SANDBOX, ""),
        "seen": dict(_SEEN),
    }
