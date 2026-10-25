"""Session guards shared by every test package.

One lane reconfigures structlog's global wrapper to a CRITICAL filter and never
restores it: ``trading_bot.research.edge03.run.quiet_runtime_logs``.  In a CLI
process that is intended — it silences the runtime engine's own logging while the
forward lane drives it in a loop — but inside one pytest process it silences
every later ``structlog.testing.capture_logs`` assertion, and the first victims
are the scanner tests, which run after the research package.  The leak is
deterministic (research < scanner, alphabetically), so it is guarded here rather
than papered over in the victim's assertions: snapshot the global structlog
configuration before each test and put it back afterwards.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
import structlog


@pytest.fixture(autouse=True)
def _restore_structlog_config() -> Iterator[None]:
    """Undo any test's mutation of the process-wide structlog configuration."""
    before = structlog.get_config()
    yield
    structlog.configure(**before)
