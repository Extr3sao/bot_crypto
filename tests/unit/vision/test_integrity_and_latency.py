"""P0 de RFC-TAP-AI-BOTS-002 v3: dos formas de operar sobre un gráfico que no existe.

* un hash de imagen distinto debe **abortar** la decisión (no sólo registrarse);
* una respuesta que llega después de abrirse la barra de ejecución no puede
  rellenarse al precio de esa apertura.

Ambos tests atacan el runtime real (`VisionLane.run`), no un simulador paralelo.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from trading_bot.config.settings import load_settings
from trading_bot.research.economic_recovery.experiments import Bar
from trading_bot.vision.lane import VisionLane
from trading_bot.vision.ledger import read_entries
from trading_bot.vision.provider import ReplayProvider, VisionResponse
from trading_bot.vision.settings import load_vision_config

HOUR_MS = 3_600_000
REPO = Path(__file__).resolve().parents[3]
WEEKDAY_MS = int(datetime(2026, 3, 3, tzinfo=UTC).timestamp() * 1000)

LONG = (
    '{"schema_version":"ai-vision-decision/1","symbol":"BTC/USDT","action":"LONG",'
    '"confidence":0.7,"horizon_bars":8,"stop_loss_pct":1.0,"take_profit_pct":2.0,'
    '"invalidation":null,"rationale":"Higher lows."}'
)


class DoctoredProvider(ReplayProvider):
    """A replay provider whose answers lie about the image or arrive late.

    It is a *transport* wrapper: the lane, the guards, the risk manager and the broker
    are the production ones, so a passing test says something about the real path.
    """

    def __init__(self, answers: list[str], *, latency_ms: int = 0, image_sha: str | None = None):
        super().__init__(list(answers))
        self._latency_ms = latency_ms
        self._image_sha = image_sha

    def analyze(self, request):  # type: ignore[override]
        response: VisionResponse = super().analyze(request)
        return replace(
            response,
            latency_ms=self._latency_ms,
            image_sha256_in_request=(
                response.image_sha256_in_request
                if self._image_sha is None
                else self._image_sha
            ),
        )


def bars(count: int = 96, *, start: int = WEEKDAY_MS, drift: float = 0.004) -> list[Bar]:
    out: list[Bar] = []
    price = 100.0
    for i in range(count):
        step = -drift if i % 12 == 11 else drift
        close = price * (1.0 + step)
        out.append(
            Bar(
                ts_ms=start + i * HOUR_MS,
                open=price,
                high=max(price, close) * 1.002,
                low=min(price, close) * 0.998,
                close=close,
                volume=200.0,
            )
        )
        price = close
    return out


def config():
    base = load_vision_config(env={})
    lane = base.lane
    merged = {
        "timeframe": lane.timeframe,
        "window_bars": 30,
        "decision_every_bars": 15,
        "max_calls_per_run": 40,
        "max_estimated_spend_usd": 5.0,
    }
    return base.__class__(provider=base.provider, lane=lane.__class__(**merged))


def run_lane(tmp_path: Path, provider):
    policy = load_settings(config_dir=REPO / "config", env_file=None).risk
    lane = VisionLane(
        series={"BTC/USDT": bars()},
        provider=provider,
        config=config(),
        risk_policy=policy,
        ledger_path=tmp_path / "d.jsonl",
    )
    return lane.run()


def ledger_rows(tmp_path: Path) -> list[dict]:
    return [row["entry"] for row in read_entries(tmp_path / "d.jsonl")]


def test_a_mismatched_image_hash_aborts_the_decision_and_every_fill(tmp_path):
    """P0 (BOT-12): the answer belongs to another image, so nothing downstream may run."""
    summary = run_lane(
        tmp_path,
        DoctoredProvider([LONG] * 40, image_sha="0" * 64),
    )
    rows = ledger_rows(tmp_path)

    integrity = [row for row in rows if row["kind"] == "INTEGRITY_FAILURE"]
    assert integrity, "the mismatch must be recorded, not swallowed"
    assert integrity[0]["expected_image_sha256"] != integrity[0]["request_image_sha256"]
    assert integrity[0]["discarded"] is True

    decisions = [row for row in rows if row["kind"] == "DECISION"]
    assert decisions == [], "a decision about another image must never be produced"
    assert summary["fills"] == 0
    assert summary["counters"].get("integrity_failure", 0) >= 1
    assert not [row for row in rows if row["kind"] == "FILL"]


def test_an_answer_that_arrives_after_the_fill_bar_opened_is_dropped(tmp_path):
    """P0 (BOT-13): two hours of latency cannot buy the fill bar's open price."""
    summary = run_lane(
        tmp_path,
        DoctoredProvider([LONG] * 40, latency_ms=2 * HOUR_MS),
    )
    rows = ledger_rows(tmp_path)

    late = [row for row in rows if row["kind"] == "GUARD_REJECT" and row["code"] == "LATE_RESPONSE"]
    assert late, "the late answer must be rejected at execution, with its own code"
    assert summary["fills"] == 0
    assert not [row for row in rows if row["kind"] == "FILL"]
    assert summary["counters"].get("guard:LATE_RESPONSE", 0) >= 1


def test_an_on_time_answer_still_fills(tmp_path):
    """Control: the new guard must not silently forbid every trade."""
    summary = run_lane(tmp_path, DoctoredProvider([LONG] * 40, latency_ms=0))
    rows = ledger_rows(tmp_path)

    assert summary["fills"] > 0, "zero latency must still be tradable"
    assert [row for row in rows if row["kind"] == "FILL"]
    assert not [row for row in rows if row["kind"] == "INTEGRITY_FAILURE"]
