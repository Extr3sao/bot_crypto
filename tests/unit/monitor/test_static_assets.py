"""Static-asset contract tests (WP-TDM-03).

The UI is plain HTML/CSS/JS served from disk, so its safety properties are
inspectable without a browser. These tests pin the ones that failed or would
fail silently:

* no remote script, font or image (CSP is ``'self'`` only);
* no ``innerHTML`` (every runtime string is rendered with ``textContent``);
* the vendored chart library is the pinned build and keeps its licence banner;
* ``[hidden]`` wins over component ``display`` rules — the bug that made an
  invisible drawer swallow every click (DEF-TDM-03-1).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

STATIC = Path("src/trading_bot/monitor/static")
VENDOR = STATIC / "vendor" / "lightweight-charts.standalone.production.js"
PINNED_SHA256 = "e6bd6516d9ab9cb897c0d6438e3fe1126f2fdce07e68c23836e84d527de81f52"


def test_every_asset_exists() -> None:
    for name in ("index.html", "app.js", "app.css", "vendor/VENDOR.md"):
        assert (STATIC / name).is_file(), f"missing static asset: {name}"


def test_index_only_references_local_assets() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    sources = [s for s in re.findall(r'(?:src|href)="([^"]+)"', html) if not s.startswith("#")]
    assert sources, "the page must load its own assets"
    for source in sources:
        assert source.startswith("/"), f"asset must be same-origin: {source}"
        assert "//" not in source, f"remote asset forbidden by CSP: {source}"


def test_app_js_never_uses_innerhtml() -> None:
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"\.innerHTML\s*=", js), "server text must never be assigned as HTML"
    assert not re.search(r"\.outerHTML\s*=", js)
    assert "insertAdjacentHTML" not in js
    assert "document.write" not in js
    assert not re.search(r"\beval\s*\(", js)
    assert "textContent" in js


def test_app_js_has_no_network_target_other_than_the_monitor_api() -> None:
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "http://" not in js and "https://" not in js
    assert "fetch(" in js
    assert "/api/monitor/" in js


def test_hidden_attribute_is_enforced_in_css() -> None:
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert "[hidden] { display: none !important; }" in css, (
        "without this rule, `hidden` drawers/overlays keep receiving clicks"
    )


def test_vendored_chart_library_is_pinned_and_licensed() -> None:
    payload = VENDOR.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == PINNED_SHA256
    head = payload[:400].decode("utf-8", errors="replace")
    assert "TradingView Lightweight Charts" in head
    assert "Apache License 2.0" in head
    license_file = (STATIC / "vendor" / "LICENSE.lightweight-charts.txt").read_text(encoding="utf-8")
    assert "Apache License" in license_file


def test_attribution_is_rendered_in_the_ui() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "TradingView Lightweight Charts" in html
    assert "Apache-2.0" in html


def test_marker_mapping_never_paints_a_fill_for_an_acceptance() -> None:
    """The accepted state must be visually distinct from the filled state."""
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    def branch(status: str) -> str:
        match = re.search(
            r"else if \(top\.status === '" + status + r"'\)\s*\{(?P<body>[^}]*)\}", js
        )
        assert match is not None, f"marker branch for {status} is missing"
        return match.group("body")

    assert "#6ea8ff" in branch("EXECUTED_PAPER")
    assert "#2ea043" in branch("ACCEPTED_NOT_EXECUTED")
    assert "#6ea8ff" not in branch("ACCEPTED_NOT_EXECUTED"), (
        "an acceptance must never use the fill colour"
    )


@pytest.mark.parametrize(
    "label",
    ["NO_TRADE", "SHADOW (NO EJECUTADA)", "ACEPTADA (NO EJECUTADA)", "EJECUTADA PAPER"],
)
def test_rfc_state_labels_are_reachable_in_the_ui(label: str) -> None:
    """Either the UI or the API provides the label; both are checked elsewhere."""
    from trading_bot.monitor.contracts import DECISION_STATUS_LABELS

    assert label in set(DECISION_STATUS_LABELS.values())


def test_no_component_can_override_the_hidden_attribute() -> None:
    """Regression for the invisible-overlay bug found while driving the panel.

    ``.drawer`` and ``.chart-overlay`` set ``display:flex``. A later rule with
    ``!important`` on those selectors would defeat ``[hidden]`` again and put an
    invisible layer over the chart, swallowing every click.
    """
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    blocks = re.findall(r"(?P<selector>[^{}]+)\{(?P<body>[^{}]*)\}", css)
    offenders = [
        selector.strip()
        for selector, body in blocks
        if "display" in body and "!important" in body and "[hidden]" not in selector
    ]
    assert offenders == [], f"these rules fight the hidden attribute: {offenders}"

    hidden_rule = next(
        (
            body
            for selector, body in blocks
            if selector.strip().splitlines()[-1].strip() == "[hidden]"
        ),
        None,
    )
    assert hidden_rule is not None
    assert "display: none !important" in hidden_rule


def test_the_default_symbol_filter_shows_every_symbol() -> None:
    """Regression: '' is the \"Todos\" value and must never be coerced to one symbol.

    The first live load of the panel defaulted the symbol filter to ``BTC/USDT``,
    so the ETH decision existed in the counters but was missing from the timeline
    — an implicit filter the operator never asked for.
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "if (keep.symbol && !(assets.symbols || []).includes(keep.symbol)) keep.symbol = '';" in js
    assert "assets.symbols[0]" not in js, "the first symbol must not become the default filter"


def test_the_chart_pins_one_symbol_and_filters_markers_to_it() -> None:
    """With "Todos" selected the chart must not scatter other assets' markers.

    The chart can only plot one series, so it pins the first available symbol,
    labels the choice, and filters markers to that same symbol while the timeline
    keeps every asset.
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "function chartSymbol()" in js
    assert "if (decision.symbol !== chartSymbol()) continue;" in js
    assert "timeline: todos los símbolos" in js


def test_marker_labels_are_dropped_when_the_window_is_dense() -> None:
    """Regression: on a 2 232-decision replay the labels overlapped into a block.

    Markers must stay (they are the evidence), but the text label is only drawn
    when the visible window is sparse enough to read.
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "const MARKER_LABEL_LIMIT" in js
    assert "const labelBudget = groupByTime.size <= MARKER_LABEL_LIMIT;" in js
    assert "text: labelBudget ? (top.status_label || top.status) + extra : ''," in js
