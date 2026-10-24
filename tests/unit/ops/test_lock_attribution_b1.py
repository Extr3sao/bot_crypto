"""B1 — the lock window, forced instead of hoped for.

The historical failure was ``LOCK_UNATTRIBUTED``: a session could not resume because a
lock file existed whose owner could not be verified.  Eight runs of the existing suite
did not reproduce it, which is not the same as a fix.  These tests stop waiting for the
race and construct it:

* the atomic path must never expose a lock whose content is missing or partial;
* the **fallback** path (``O_CREAT|O_EXCL`` then ``write``) does have a window, and a
  crash inside it leaves an empty lock file;
* an empty lock is refused with ``LOCK_UNATTRIBUTED`` and is never deleted — by design,
  because a lock that cannot be attributed could belong to a writer that is still alive.

So B1 is not "the race is gone".  It is "the race has one remaining site, the fallback,
and on this host the hard-link path is the one taken".  The tests measure both halves.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from trading_bot.ops import single_writer
from trading_bot.ops.single_writer import LockRefused, SingleWriter, diagnose_lock


def _acquire(path: Path) -> dict:
    return SingleWriter(path, purpose="b1").acquire()


def test_every_lock_that_becomes_visible_is_already_complete(tmp_path: Path) -> None:
    """200 acquisitions: the file has a full record the instant it exists.

    The assertion is made on the file as ``acquire`` returns, which is the state any
    reader (a status CLI, a second supervisor) can see.  On the hard-link path the link
    is installed with the content already in it, so there is no moment at which an empty
    file named like a lock exists.
    """

    path = tmp_path / "STREAM.jsonl.lock"
    for _ in range(200):
        holder = SingleWriter(path, purpose="b1-stress")
        holder.acquire()
        text = path.read_text(encoding="utf-8")
        assert _is_record(text), f"visible but not a complete record: {text!r}"
        assert path.stat().st_size > 0
        assert holder.release() is True


def _is_record(text: str) -> bool:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, dict) and bool(payload.get("token")) and isinstance(payload.get("pid"), int)


def test_the_fallback_path_still_writes_a_complete_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where hard links are refused, the two-step path must still finish its write."""

    def refuse(*_args, **_kwargs):
        raise OSError("hard links are not available here")

    monkeypatch.setattr(single_writer.os, "link", refuse)
    path = tmp_path / "STREAM.jsonl.lock"
    lock = SingleWriter(path, purpose="b1-fallback")
    lock.acquire()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["token"] == lock.record["token"]
    assert payload["pid"] == os.getpid()
    assert diagnose_lock(payload)["state"] == "HELD"


def test_a_crash_inside_the_fallback_window_leaves_the_empty_lock_b1_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The remaining site of B1, forced deterministically.

    ``os.link`` is made to fail (so the fallback runs) and ``os.write`` to fail after the
    file exists (the crash).  What is left on disk is exactly the shape the old code
    could produce, and the next writer must refuse it rather than steal it.
    """

    def refuse_link(*_args, **_kwargs):
        raise OSError("hard links are not available here")

    def crash_before_content(*_args, **_kwargs):
        raise OSError("simulated crash between create and write")

    monkeypatch.setattr(single_writer.os, "link", refuse_link)
    monkeypatch.setattr(single_writer.os, "write", crash_before_content)
    path = tmp_path / "STREAM.jsonl.lock"

    with pytest.raises(OSError, match="simulated crash"):
        SingleWriter(path, purpose="b1-crash").acquire()

    assert path.exists(), "the forced window did not leave a lock behind"
    assert path.read_text(encoding="utf-8") == "", "the forced crash must leave it empty"

    monkeypatch.setattr(single_writer.os, "write", os.write)
    with pytest.raises(LockRefused) as excinfo:
        SingleWriter(path, purpose="b1-next").acquire()
    assert excinfo.value.code == "LOCK_UNATTRIBUTED"
    assert path.read_text(encoding="utf-8") == "", "an unattributable lock is never deleted"


def test_an_empty_lock_on_disk_is_refused_and_left_alone(tmp_path: Path) -> None:
    """The symptom, without any monkeypatching: this is what B1 looked like."""

    path = tmp_path / "STREAM.jsonl.lock"
    path.write_text("", encoding="utf-8")

    assert diagnose_lock(single_writer._normalise(""))["state"] == "UNATTRIBUTED"
    with pytest.raises(LockRefused) as excinfo:
        _acquire(path)
    assert excinfo.value.code == "LOCK_UNATTRIBUTED"
    assert path.exists() and path.read_text(encoding="utf-8") == ""


def test_an_unparsable_lock_is_refused_rather_than_overwritten(tmp_path: Path) -> None:
    path = tmp_path / "STREAM.jsonl.lock"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(LockRefused) as excinfo:
        _acquire(path)
    assert excinfo.value.code == "LOCK_UNATTRIBUTED"
    assert path.read_text(encoding="utf-8") == "{not json"


def test_the_atomic_path_is_the_one_this_host_takes(tmp_path: Path) -> None:
    """Measured, not assumed: does ``os.link`` work where the locks actually live?"""

    probe = tmp_path / "probe"
    probe.write_text("x", encoding="utf-8")
    link = tmp_path / "probe.link"
    try:
        os.link(probe, link)
    except (OSError, NotImplementedError) as error:  # pragma: no cover - host dependent
        pytest.skip(f"this filesystem refuses hard links, so the fallback window is live: {error}")
    assert link.read_text(encoding="utf-8") == "x"
