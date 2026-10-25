"""Name the process that owns the console, so a window can be traced to its source.

When a console window appears during automation, guessing whose it is wastes a
session. This walks the real parent chain and reads each ancestor's executable
subsystem from its own PE header:

* a **GUI** ancestor (subsystem 2) has no console, so the first console-subsystem
  child it starts is given a *new* one — which is a window;
* a **console** ancestor (subsystem 3) hands its console down, so children share
  it and no new window appears.

    .venv/Scripts/python.exe scripts/ops_window_origin.py [--json]

The answer is evidence, not a recommendation: it says who spawned the chain and
at which link a console first had to be created.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "window-origin-v1"


class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260),
    ]


def _image(pid: int) -> str | None:
    if os.name != "nt":  # pragma: no cover - platform dependent
        return None
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return str(buffer.value)
    finally:
        kernel32.CloseHandle(handle)


def _parent(pid: int) -> int | None:
    if os.name != "nt":  # pragma: no cover - platform dependent
        return None
    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot == ctypes.c_void_p(-1).value:
        return None
    try:
        entry = _PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
        ok = kernel32.Process32First(snapshot, ctypes.byref(entry))
        while ok:
            if int(entry.th32ProcessID) == pid:
                return int(entry.th32ParentProcessID) or None
            ok = kernel32.Process32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return None


def _subsystem(image: str | None) -> str:
    """Read the PE optional header's Subsystem field (2 GUI, 3 console)."""
    if not image:
        return "UNKNOWN"
    try:
        with open(image, "rb") as handle:
            if handle.read(2) != b"MZ":
                return "UNKNOWN"
            handle.seek(0x3C)
            offset = int.from_bytes(handle.read(4), "little")
            handle.seek(offset)
            if handle.read(4) != b"PE\0\0":
                return "UNKNOWN"
            handle.seek(offset + 24)
            magic = int.from_bytes(handle.read(2), "little")
            handle.seek(offset + 24 + (68 if magic == 0x20B else 64))
            value = int.from_bytes(handle.read(2), "little")
    except OSError:
        return "UNKNOWN"
    return {2: "GUI", 3: "CONSOLE"}.get(value, f"OTHER({value})")


def chain(start: int | None = None) -> list[dict[str, Any]]:
    pid = os.getpid() if start is None else start
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for _ in range(32):
        if pid in seen or not pid:
            break
        seen.add(pid)
        image = _image(pid)
        rows.append(
            {
                "pid": pid,
                "image": image,
                "exe": Path(image).name if image else None,
                "subsystem": _subsystem(image),
            }
        )
        parent = _parent(pid)
        if parent is None or parent == pid:
            break
        pid = parent
    return rows


def analyse(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Find the first link where a console had to be created."""
    first_gui = next((row for row in rows if row["subsystem"] == "GUI"), None)
    first_console_child = None
    if first_gui is not None:
        index = rows.index(first_gui)
        if index > 0:
            first_console_child = rows[index - 1]
    return {
        "gui_ancestor": first_gui,
        "first_console_child_of_gui": first_console_child,
        "console_is_created_at": (
            f"{first_gui['exe']} (GUI) -> {first_console_child['exe']} (CONSOLE)"
            if first_gui and first_console_child
            else None
        ),
        "interpretation": (
            "a GUI ancestor has no console, so the first console-subsystem child is given a new "
            "one: that allocation is the window. A console ancestor passes its console down, so "
            "no new window is created for its descendants."
            if first_gui
            else "every ancestor in this chain is console-subsystem, so the child inherited the "
            "existing console instead of allocating a window"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    rows = chain()
    payload = {
        "schema_version": SCHEMA,
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "pid": os.getpid(),
        "platform": sys.platform,
        "chain": rows,
        **analyse(rows),
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    if args.json:
        print(text)
    else:
        for row in rows:
            print(f"{row['pid']:>7}  {row['subsystem']:<8}  {row['image']}")
        print()
        print(payload["console_is_created_at"] or "no GUI ancestor: console inherited")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
