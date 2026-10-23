"""paper_session_status — ask a PAPER session what it is doing, without changing it.

Thin CLI over ``trading_bot.ops.session_status``: the logic (and its read-only guarantee)
lives in one place and is unit-tested there, so an operator command cannot drift into a
second opinion. It writes nothing unless ``--json`` names a path outside the session
directory, and it never runs a recovery.

Exit codes:

``0``  the state was read (and matched ``--expect`` when one was given)
``3``  the state was read but did not match ``--expect``
``4``  there is no such session directory

Usage::

    python scripts/paper_session_status.py --session reports/.../session
    python scripts/paper_session_status.py --session S --expect RECOVERING --json status.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.ops.session_status import session_status  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only PAPER session status")
    parser.add_argument("--session", required=True, help="session output directory")
    parser.add_argument("--json", default=None, help="also write the status here")
    parser.add_argument(
        "--expect",
        default=None,
        help="exit 3 unless the state is exactly this (RUNNING/RECOVERING/...)",
    )
    args = parser.parse_args(argv)

    session = Path(args.session)
    if not session.is_dir():
        print(json.dumps({"error": "NO_SUCH_SESSION", "session": str(session)}))
        return 4

    status = session_status(session)
    text = json.dumps(status, indent=2, sort_keys=True)
    print(text)
    if args.json:
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
    if args.expect and status["state"] != args.expect:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
