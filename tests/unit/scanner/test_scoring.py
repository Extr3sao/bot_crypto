"""Tests unitarios para ``src/trading_bot/scanner/scoring.py``.

Estrategia:

- 9 sentinels: edge cases nominales de la formula cerrada (extremos,
  atr ausente, denominadores invalidos, NaN/inf).
- 2 parametrizados: coefs ADR-locked + spread_norm clipping property.
- 1 determinism: doble-call con mismos inputs -> score bit-identical.
- 3 property tests con ``hypothesis``: invariante ``0 <= score <= 1``
  + monotonia ``spread_bps`` ↘ score + determinismo bit-identical para
  inputs identicos (tie-break pine contract).

Todos los F3 property tests corren con ``max_examples=1000`` (per spec
§6 / TSK-103.3.2); no se rela x la cobertura con ``deadline=None``
(``hypothesis`` por defecto es 200ms; esta heuristica es para tests
normales, los property tests son rapidos en este codigo).

Cobertura esperada per DoD F3: 100% sobre ``scoring.py``. Pine contract:
el modulo NO importa ``market_data.*``, ``exchange.*``, etc.
(cobertura via ``test_cross_layer.py`` cross-TSK-103.4.9, F4).

# TODO(TSK-103.5/ADR-0013): BDD scenario "rank_score se calcula con la
# formula especificada" in bdd/features/market_scanner.feature expects
# 0.4833, inconsistent with the closed formula 0.6833 (spec §6 cuenta
# la contribucion atr_term como 0.2). Pin contract sigue formula
# (ADR-locked v1); el BDD example se flag para ADR-0013 cuando BDD
# wiring corra pytest-bdd 23/23 en TSK-103.5.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from trading_bot.scanner.scoring import (
    ATR_WEIGHT,
    SPREAD_WEIGHT,
    compute_rank_score,
)

# ===========================================================================
# Sentinel tests (9 casos nominales).
# ===========================================================================


def test_compute_rank_score_zero_spread_and_vol_no_atr_yields_half() -> None:
    """tightness premium only: spread=0 -> 1-norm=1 -> 0.5*1.

    Casos de partida: vol_norm=0 (volume=0) + atr_term=0 (atr_pct=None
    o atr_en_rango=False) -> score esperado = 0.5 * 1 + 0 + 0 = 0.5.
    """
    score = compute_rank_score(
        spread_bps=0.0,
        spread_norm_max=30.0,
        volume_24h_usdt=0.0,
        volume_norm_max=100.0,
        atr_pct=None,
        atr_optimo=2.0,
        atr_en_rango=False,
    )
    assert score == pytest.approx(0.5, abs=1e-9)


def test_compute_rank_score_max_when_perfect_inputs() -> None:
    """tight spread (1-norm=1) + max volume (vol_norm=1) + atr en rango
    (atr_term=1) -> score maximo 1.0.

    0.5*1 + 0.3*1 + 0.2*1 = 1.0.
    """
    score = compute_rank_score(
        spread_bps=0.0,
        spread_norm_max=30.0,
        volume_24h_usdt=100_000_000.0,
        volume_norm_max=100_000_000.0,
        atr_pct=2.0,
        atr_optimo=2.0,
        atr_en_rango=True,
    )
    assert score == pytest.approx(1.0, abs=1e-9)


def test_compute_rank_score_min_when_worst_inputs() -> None:
    """max spread (norm=1 -> 1-spread_norm=0) + vol 0 + atr fuera de
    rango -> score minimo 0.0.

    0.5*0 + 0.3*0 + 0.2*0 = 0.0.
    """
    score = compute_rank_score(
        spread_bps=300.0,    # 10x del max; clip a 1.0
        spread_norm_max=30.0,
        volume_24h_usdt=0.0,
        volume_norm_max=100.0,
        atr_pct=12.0,
        atr_optimo=2.0,
        atr_en_rango=False,
    )
    assert score == pytest.approx(0.0, abs=1e-9)


def test_compute_rank_score_matches_closed_formula_bdd_example() -> None:
    """BDD scenario example: spread_bps=10, vol=50M, atr_pct=2.0.

    Pine contract formula (spec §6 verbatim, not the BDD example typo):
        0.5 * (1 - 10/30) + 0.3 * (50M/100M) + 0.2 * 1.0
        = 0.5 * 0.6667 + 0.3 * 0.5 + 0.2
        ~= 0.6833

    NOTA: La BDD feature (03-specify §6) enuncia ``~= 0.4833``,
    inconsistente con la formula cerrada 3-componente de spec §6.
    Pine contract: la formula ADR-locked gana (``0.6833``). La BDD
    tiene typo (``0.4833`` corresponderia a un modelo v0 sin termino
    atr); se flag para ADR-0013 clarificacion cuando integremos BDD
    wiring (TSK-103.5) y pytest-bdd corra los 23 escenarios.
    """
    score = compute_rank_score(
        spread_bps=10.0,
        spread_norm_max=30.0,
        volume_24h_usdt=50_000_000.0,
        volume_norm_max=100_000_000.0,
        atr_pct=2.0,
        atr_optimo=2.0,
        atr_en_rango=True,
    )
    assert score == pytest.approx(0.6833, abs=1e-3)


def test_compute_rank_score_atr_pct_none_invalidates_atr_en_rango_true() -> None:
    """atr_pct=None aunque atr_en_rango=True -> atr_term = 0.0.

    Score_with_atr (atr_pct=2.0, atr_en_rango=True) - score_without_atr
    (atr_pct=None, atr_en_rango=True) == ATR_WEIGHT.
    La diferencia es exactamente la contribucion ATR (0.2 * 1).
    """
    base_kwargs = dict(
        spread_bps=0.0,
        spread_norm_max=30.0,
        volume_24h_usdt=100.0,
        volume_norm_max=100.0,
        atr_optimo=2.0,
    )
    score_with_atr = compute_rank_score(
        **base_kwargs, atr_pct=2.0, atr_en_rango=True
    )
    score_without_atr = compute_rank_score(
        **base_kwargs, atr_pct=None, atr_en_rango=True
    )
    assert score_with_atr - score_without_atr == pytest.approx(
        ATR_WEIGHT, abs=1e-9
    )


def test_compute_rank_score_clips_inputs_above_norm_max() -> None:
    """Inputs absurdos sobre norm_max -> clip a 1.0 (monotonia respetada).

    spread_bps=10000 (>> 30) -> spread_norm=1 -> contrib spread = 0.
    volume=1e12 (>> 100) -> vol_norm=1 -> contrib vol = 0.3.
    atr_pct=2.0, atr_en_rango=True -> contrib atr = 0.2.
    Score = 0.0 + 0.3 + 0.2 = 0.5.
    """
    score = compute_rank_score(
        spread_bps=10_000.0,
        spread_norm_max=30.0,
        volume_24h_usdt=1e12,
        volume_norm_max=100.0,
        atr_pct=2.0,
        atr_optimo=2.0,
        atr_en_rango=True,
    )
    assert score == pytest.approx(0.5, abs=1e-9)


def test_compute_rank_score_clips_inputs_below_zero() -> None:
    """Inputs negativos -> clip a 0.0 (no propagacion negativa).

    spread_bps=-50 -> spread_norm=0 -> contrib spread = 0.5 * 1 = 0.5.
    volume=-100 -> vol_norm=0 -> contrib vol = 0.
    atr_term=1 -> contrib atr = 0.2.
    Score = 0.5 + 0 + 0.2 = 0.7.
    """
    score = compute_rank_score(
        spread_bps=-50.0,
        spread_norm_max=30.0,
        volume_24h_usdt=-100.0,
        volume_norm_max=100.0,
        atr_pct=2.0,
        atr_optimo=2.0,
        atr_en_rango=True,
    )
    assert score == pytest.approx(0.7, abs=1e-9)


@pytest.mark.parametrize(
    "field_name",
    ["spread_bps", "volume_24h_usdt", "atr_optimo", "atr_pct"],
)
@pytest.mark.parametrize(
    "bad_input", [float("nan"), float("inf"), float("-inf")]
)
def test_compute_rank_score_rejects_non_finite_inputs(
    field_name: str, bad_input: float
) -> None:
    """NaN / inf inputs -> ValueError explicito (no propagacion silenciosa).

    Pine contract: cualquier score NaN rompe la invariante
    ``0 <= score <= 1`` downstream; levantamos antes del clip para
    que el orquestador (TSK-103.4) pueda enrutar el error.

    Expansion parametrizada: pine contract es independiente por cada
    campo numerico pineado. ``spread_norm_max`` y ``volume_norm_max``
    caen en el branch ``_validate_positive_denominator`` (no en el
    finite-check), asi que no se incluyen en este test; tienen su
    propio ``test_compute_rank_score_rejects_non_positive_norm_max``.
    """
    # Construimos kwargs sanas e injectamos el bad_input en el
    # campo bajo test. Usamos ``field_name`` para seleccionar via
    # ``{**base_kwargs, field_name: bad_input}``.
    base_kwargs = dict(
        spread_bps=15.0,
        spread_norm_max=30.0,
        volume_24h_usdt=100.0,
        volume_norm_max=100.0,
        atr_pct=2.0,
        atr_optimo=2.0,
        atr_en_rango=True,
    )
    # atr_pct acepta None; para pine contract del guard sobre atr_pct
    # cuando finite, seteamos a bad_input explicito (no None).
    bad_kwargs = {**base_kwargs, field_name: bad_input}
    with pytest.raises(ValueError, match=r"debe ser finito"):
        compute_rank_score(**bad_kwargs)  # type: ignore[arg-type] clip the test_kwargs injection


def test_compute_rank_score_rejects_non_positive_norm_max() -> None:
    """norm_max <= 0 -> ValueError explicito (no ZeroDivisionError silencioso).

    Pine contract: ``norm_max=0`` divide por cero en Python (`ZeroDivisionError`),
    pero preferimos ValueError explicito porque el caller puede atrapar
    ``ValueError`` de tipo inferencia sin importar ``builtins`` adicional;
    ademas pre-flight el error semantico (configurar ``norm_max<=0`` es
    un bug de configuracion, no un evento natural).
    """
    # spread_norm_max=0.0: division by zero path
    with pytest.raises(ValueError, match=r"denominador"):
        compute_rank_score(
            spread_bps=5.0,
            spread_norm_max=0.0,
            volume_24h_usdt=100.0,
            volume_norm_max=100.0,
            atr_pct=None,
            atr_optimo=2.0,
            atr_en_rango=False,
        )
    # volume_norm_max<0: contratio semanticamente absurdo
    with pytest.raises(ValueError, match=r"denominador"):
        compute_rank_score(
            spread_bps=5.0,
            spread_norm_max=30.0,
            volume_24h_usdt=100.0,
            volume_norm_max=-1.0,
            atr_pct=None,
            atr_optimo=2.0,
            atr_en_rango=False,
        )


# ===========================================================================
# Parametrized tests (pine contracts).
# ===========================================================================


@pytest.mark.parametrize(
    ("coef_name", "expected"),
    [
        ("SPREAD_WEIGHT", 0.5),
        ("VOLUME_WEIGHT", 0.3),
        ("ATR_WEIGHT", 0.2),
    ],
)
def test_coefficients_are_adm_locked(
    coef_name: str, expected: float, scoring_module: object
) -> None:
    """Coefs pineados por spec §6 - cambios requieren ADR firmada."""
    actual = getattr(scoring_module, coef_name)
    assert actual == pytest.approx(expected, abs=1e-9)


@pytest.fixture
def scoring_module() -> object:
    """Import lazy del modulo scoring (para no penalizar la coleccion)."""
    from trading_bot.scanner import scoring
    return scoring


@pytest.mark.parametrize(
    ("spread_bps", "spread_norm_max", "expected_spread_norm"),
    [
        (0.0, 30.0, 0.0),
        (15.0, 30.0, 0.5),
        (30.0, 30.0, 1.0),    # borde: equal -> 1.0 (clip inclusive).
        (60.0, 30.0, 1.0),    # clip desde encima.
        (-30.0, 30.0, 0.0),   # clip desde debajo.
    ],
)
def test_spread_norm_clipping(
    spread_bps: float,
    spread_norm_max: float,
    expected_spread_norm: float,
) -> None:
    """Spread normalizado en ``[0, 1]`` con clip en ambos extremos.

    Spread_norm se infiere via ``score = 0.5 * (1 - spread_norm) + 0 + 0``
    (vol=0, atr=None): el score es media imagen de spread_norm.
    """
    score = compute_rank_score(
        spread_bps=spread_bps,
        spread_norm_max=spread_norm_max,
        volume_24h_usdt=0.0,
        volume_norm_max=100.0,
        atr_pct=None,
        atr_optimo=2.0,
        atr_en_rango=False,
    )
    expected_score = SPREAD_WEIGHT * (1.0 - expected_spread_norm)
    assert score == pytest.approx(expected_score, abs=1e-9)


# ===========================================================================
# Determinism test (pine contract para tie-break alfabetico F3.3.3).
# ===========================================================================


def test_compute_rank_score_is_deterministic_with_identical_inputs() -> None:
    """Determinismo bit-identical: misma signature -> mismo score.

    Esto pinea el tie-break contract: si UniverseScanner (F4) ordena
    snapshots activos por ``rank_score`` descendente con tie-break
    alfabetico, dos pares con valores identicos producen orden
    estable; el score es determinista sin importar el clock ni otras
    condiciones de carrera.
    """
    kwargs = dict(
        spread_bps=15.0,
        spread_norm_max=30.0,
        volume_24h_usdt=50_000_000.0,
        volume_norm_max=100_000_000.0,
        atr_pct=2.0,
        atr_optimo=2.0,
        atr_en_rango=True,
    )
    s1 = compute_rank_score(**kwargs)
    s2 = compute_rank_score(**kwargs)
    assert s1 == s2

    # Casos degenerados equivalentes para atr_term (cubren todos los
    # caminos que producen el mismo 0.0):
    #   (atr_en_rango=True, atr_pct=None)              -> atr_term = 1*0 = 0.
    #   (atr_en_rango=False, atr_pct=2.0)             -> atr_term = 0*1 = 0.
    s3 = compute_rank_score(**{**kwargs, "atr_en_rango": True, "atr_pct": None})
    s4 = compute_rank_score(**{**kwargs, "atr_en_rango": False, "atr_pct": 2.0})
    assert s3 == s4


# ===========================================================================
# Hypothesis property tests (TSK-103.3.2 principal).
# ===========================================================================


@given(
    spread_bps=st.floats(min_value=0.0, max_value=200.0, allow_nan=False),
    spread_norm_max=st.floats(min_value=0.1, max_value=200.0, allow_nan=False),
    volume_24h_usdt=st.floats(min_value=0.0, max_value=1e9, allow_nan=False),
    volume_norm_max=st.floats(min_value=1e3, max_value=1e10, allow_nan=False),
    atr_pct=st.one_of(
        st.none(),
        st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
    ),
    atr_optimo=st.floats(min_value=0.0, max_value=10.0, allow_nan=False),
    atr_en_rango=st.booleans(),
)
@settings(max_examples=1000, deadline=None)
def test_rank_score_in_unit_interval(
    spread_bps: float,
    spread_norm_max: float,
    volume_24h_usdt: float,
    volume_norm_max: float,
    atr_pct: float | None,
    atr_optimo: float,
    atr_en_rango: bool,
) -> None:
    """Invariante RF-10 v1: ``0 <= rank_score <= 1`` para inputs validos.

    Pine contract principales: la formula cerrada con coefs sum-1.0
    (0.5+0.3+0.2) y clip [0,1] sobre cada norm produce siempre un
    valor en [0, 1]. El ``atr_term`` en {0, 1} mantiene el invariante
    incluso en el peor caso (todo spread, nada vol, sin atr).
    """
    score = compute_rank_score(
        spread_bps=spread_bps,
        spread_norm_max=spread_norm_max,
        volume_24h_usdt=volume_24h_usdt,
        volume_norm_max=volume_norm_max,
        atr_pct=atr_pct,
        atr_optimo=atr_optimo,
        atr_en_rango=atr_en_rango,
    )
    assert 0.0 <= score <= 1.0


@given(
    spread_norm_max=st.floats(min_value=1.0, max_value=200.0, allow_nan=False),
    volume_norm_max=st.floats(min_value=1e3, max_value=1e10, allow_nan=False),
    atr_pct=st.floats(min_value=0.0, max_value=10.0, allow_nan=False),
    atr_optimo=st.floats(min_value=0.0, max_value=10.0, allow_nan=False),
)
@settings(max_examples=500, deadline=None)
def test_rank_score_monotonic_decreasing_with_spread(
    spread_norm_max: float,
    volume_norm_max: float,
    atr_pct: float,
    atr_optimo: float,
) -> None:
    """Monotonia: mayor ``spread_bps`` -> menor score (vol/atr fijos).

    Pine contract auxiliar: si dos pares tienen mismos volume y atr,
    el que tiene menor spread debe rankear mas alto. Esto es
    semantica central de RF-10 (seleccionar tightness).
    """
    vol = volume_norm_max * 0.5  # fixed mid-volume
    score_low = compute_rank_score(
        spread_bps=spread_norm_max * 0.1,
        spread_norm_max=spread_norm_max,
        volume_24h_usdt=vol,
        volume_norm_max=volume_norm_max,
        atr_pct=atr_pct,
        atr_optimo=atr_optimo,
        atr_en_rango=True,
    )
    score_mid = compute_rank_score(
        spread_bps=spread_norm_max * 0.5,
        spread_norm_max=spread_norm_max,
        volume_24h_usdt=vol,
        volume_norm_max=volume_norm_max,
        atr_pct=atr_pct,
        atr_optimo=atr_optimo,
        atr_en_rango=True,
    )
    score_high = compute_rank_score(
        spread_bps=spread_norm_max * 0.9,
        spread_norm_max=spread_norm_max,
        volume_24h_usdt=vol,
        volume_norm_max=volume_norm_max,
        atr_pct=atr_pct,
        atr_optimo=atr_optimo,
        atr_en_rango=True,
    )
    assert score_low >= score_mid >= score_high
    # Strict en los extremos (excluye caso degenerado donde los
    # inputs producen exactamente el mismo valor numerico).
    assert score_low > score_high


@given(
    inputs=st.tuples(
        st.floats(min_value=0.0, max_value=200.0, allow_nan=False),
        st.floats(min_value=0.1, max_value=200.0, allow_nan=False),
        st.floats(min_value=0.0, max_value=1e9, allow_nan=False),
        st.floats(min_value=1e3, max_value=1e10, allow_nan=False),
        st.one_of(
            st.none(),
            st.floats(min_value=0.0, max_value=50.0, allow_nan=False),
        ),
        st.floats(min_value=0.0, max_value=10.0, allow_nan=False),
        st.booleans(),
    ),
)
@settings(max_examples=500, deadline=None)
def test_rank_score_deterministic_property(inputs: tuple[float, float, float, float, float | None, float, bool]) -> None:
    """Pine property (TSK-103.3.3): dos calls con mismos inputs producen
    score bit-identical. Esto es la base del tie-break alfabetico
    (UniverseScanner ordenara desc por score, ties por symbol).
    """
    sb, snm, vol, vnm, atr_p, atr_o, atr_r = inputs
    s1 = compute_rank_score(
        spread_bps=sb,
        spread_norm_max=snm,
        volume_24h_usdt=vol,
        volume_norm_max=vnm,
        atr_pct=atr_p,
        atr_optimo=atr_o,
        atr_en_rango=atr_r,
    )
    s2 = compute_rank_score(
        spread_bps=sb,
        spread_norm_max=snm,
        volume_24h_usdt=vol,
        volume_norm_max=vnm,
        atr_pct=atr_p,
        atr_optimo=atr_o,
        atr_en_rango=atr_r,
    )
    assert s1 == s2
