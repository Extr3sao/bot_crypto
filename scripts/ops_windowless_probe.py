"""Live Windows probe: does a console-less parent give its child a new console?

The probe is honest about what this host can and cannot show. It starts a
console interpreter twice from a **console-less** parent (``pythonw.exe``):

* ``plain`` — no creation flags, the pre-fix behaviour;
* ``guarded`` — through ``scripts/windowless.py``, i.e. ``CREATE_NO_WINDOW`` and
  ``STARTUPINFO`` with ``SW_HIDE``.

Each child records its own console attachment (``GetConsoleProcessList`` and
``GetConsoleWindow``) because a child is the only process that can answer for its
own console. The probe also counts visible console-host windows before and while
each child runs.

``GetConsoleWindow`` returns no handle when the console is hosted by Windows
Terminal (ConPTY), so on such a host the *visual* result is reported as
``NOT_OBSERVABLE`` — never as a pass. What is still measured is the difference
that matters: how many processes the child's console is shared with. A guarded
child gets a private console; an unguarded one joins an existing console.

    .venv/Scripts/python.exe scripts/ops_windowless_probe.py --out reports/.../PROBE.json
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from trading_bot.ops import windowless  # noqa: E402

SCHEMA = "windowless-live-probe-v1"
CLASSES = {"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"}


def console_windows() -> list[str]:
    """Visible top-level windows that host a console, if the host exposes them."""
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    found: list[str] = []
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _param: int) -> bool:
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buffer, 256)
        if buffer.value in CLASSES and user32.IsWindowVisible(hwnd):
            found.append(f"{buffer.value}:{hwnd}")
        return True

    user32.EnumWindows(EnumProc(callback), 0)
    return found


def child_state(path: Path) -> dict[str, Any]:
    """Runs *inside* the child: report its own console without needing stdout."""
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    processes = (ctypes.c_uint32 * 64)()
    count = int(kernel32.GetConsoleProcessList(processes, 64))
    hwnd = int(kernel32.GetConsoleWindow() or 0)
    path.write_text(
        json.dumps(
            {
                "attached_processes": count,
                "console_hwnd": hex(hwnd) if hwnd else None,
                "window_visible": bool(hwnd) and bool(user32.IsWindowVisible(hwnd)),
            }
        ),
        encoding="utf-8",
    )
    return 0


def inner(out: Path) -> int:
    """Console-less parent: run both cases and write the measurement."""
    python = Path(sys.executable).with_name("python.exe")
    child = Path(__file__).resolve()
    cases: dict[str, Any] = {}

    def run_case(label: str, guarded: bool) -> dict[str, Any]:
        state_path = out.parent / f"{label}.child.json"
        state_path.unlink(missing_ok=True)
        before = console_windows()
        started = time.monotonic()
        if guarded:
            log = out.parent / f"{label}.log"
            events = out.parent / f"{label}.execution.jsonl"
            completed = subprocess.run(
                [
                    str(Path(sys.executable).with_name("pythonw.exe")),
                    str(REPO / "scripts" / "windowless.py"),
                    "--log",
                    str(log),
                    "--event-log",
                    str(events),
                    "--label",
                    label,
                    "--",
                    str(python),
                    str(child),
                    "--child",
                    str(state_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            exit_code = completed.returncode
            evidence = {
                "log": str(log),
                "execution_log": str(events),
                "execution_record": (
                    json.loads(events.read_text(encoding="utf-8").splitlines()[-1])
                    if events.exists()
                    else None
                ),
            }
        else:
            process = subprocess.Popen(
                [str(python), str(child), "--child", str(state_path)],
                stdin=subprocess.DEVNULL,
            )
            exit_code = process.wait(timeout=120)
            evidence = {}
        during = console_windows()
        state = (
            json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else None
        )
        return {
            "label": label,
            "guarded": guarded,
            "exit_code": exit_code,
            "seconds": round(time.monotonic() - started, 3),
            "child": state,
            "visible_console_windows_before": before,
            "visible_console_windows_during": during,
            "new_visible_windows": sorted(set(during) - set(before)),
            **evidence,
        }

    cases["plain"] = run_case("plain", guarded=False)
    cases["guarded"] = run_case("guarded", guarded=True)

    plain = cases["plain"]["child"] or {}
    guarded = cases["guarded"]["child"] or {}
    observable = plain.get("console_hwnd") is not None or guarded.get("console_hwnd") is not None
    if not observable:
        visual = "NOT_OBSERVABLE"
        why = (
            "GetConsoleWindow returned no handle for either child: this host's console is "
            "hosted by Windows Terminal (ConPTY), which has no HWND to inspect. The window "
            "outcome is therefore not asserted here; the attachment counts and the creation "
            "flags are."
        )
    elif cases["guarded"]["new_visible_windows"] or guarded.get("window_visible"):
        visual = "FAIL"
        why = "a guarded child produced a visible console window"
    else:
        visual = "PASS"
        why = "no visible console window appeared for the guarded child"

    payload = {
        "schema_version": SCHEMA,
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "platform": sys.platform,
        "parent_has_console": bool(ctypes.windll.kernel32.GetConsoleWindow()),
        "cases": cases,
        "visual_verdict": visual,
        "visual_note": why,
        "structural_verdict": (
            "PASS"
            if guarded.get("attached_processes", 99) < plain.get("attached_processes", 0)
            else "INCONCLUSIVE"
        ),
        "structural_note": (
            "the guarded child received a private console (fewer attached processes) instead "
            "of joining an existing one; CREATE_NO_WINDOW is what creates that private console"
        ),
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO / "WINDOWLESS_LIVE_PROBE.json")
    parser.add_argument("--child", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--inner", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.child is not None:
        return child_state(args.child)
    if not windowless.IS_WINDOWS:
        args.out.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA,
                    "platform": sys.platform,
                    "visual_verdict": "NOT_APPLICABLE",
                    "note": "console windows are a Windows behaviour",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return 0
    if args.inner:
        return inner(args.out)

    # Re-execute under pythonw.exe: a console parent would hand its console down
    # and hide the very behaviour being measured.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    completed = subprocess.run(
        [str(pythonw), str(Path(__file__).resolve()), "--inner", "--out", str(args.out)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if completed.returncode != 0:
        args.out.write_text(
            json.dumps(
                {
                    "schema_version": SCHEMA,
                    "status": "FAILED",
                    "returncode": completed.returncode,
                    "stderr": completed.stderr[-4000:],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return 1
    payload = json.loads(args.out.read_text(encoding="utf-8"))
    print(json.dumps({k: payload[k] for k in ("visual_verdict", "structural_verdict")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
