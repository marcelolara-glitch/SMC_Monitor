"""
OBJETIVO
    Smoke test da Onda 1: prova que os 6 UDTs e o EngineState
    instanciam com defaults verbatim do Pine fonte e que mutação
    funciona conforme semântica Pine.

FONTE DE DADOS
    Não consome dados — apenas instancia e inspeciona.
    Cada teste rastreia a uma linha específica do fonte
    luxalgo_smc_compute_only.py ou do Mapa Camada 1.

LIMITAÇÕES CONHECIDAS
    Não testa lógica SMC — não há lógica nesta onda.

NÃO FAZER
    Não usar este teste como prova de que a engine "funciona". Engine
    só ganha sentido a partir da Onda 9.
    Não adicionar testes que dependam de pandas ou freqtrade.
"""
from dataclasses import asdict

from smc_engine import (
    ATR,
    BEARISH,
    BEARISH_LEG,
    BULLISH,
    BULLISH_LEG,
    CLOSE,
    HIGHLOW,
    RANGE,
    Alerts,
    EngineState,
    FairValueGap,
    OrderBlock,
    Pivot,
    TrailingExtremes,
    Trend,
)


# ----- Constantes -----

def test_constants_int_match_pine_source() -> None:
    """Verbatim das linhas 73-76 de luxalgo_smc_compute_only.py."""
    assert BULLISH == 1
    assert BEARISH == -1
    assert BULLISH_LEG == 1
    assert BEARISH_LEG == 0


def test_constants_string_match_pine_source() -> None:
    """Verbatim das linhas 53-56 de luxalgo_smc_compute_only.py."""
    assert ATR == 'Atr'
    assert RANGE == 'Cumulative Mean Range'
    assert CLOSE == 'Close'
    assert HIGHLOW == 'High/Low'


# ----- UDT Pivot -----

def test_pivot_default_is_all_none() -> None:
    """Pine `pivot` UDT sem args resulta em todos campos `na`."""
    p = Pivot()
    assert p.current_level is None
    assert p.last_level is None
    assert p.crossed is None
    assert p.bar_time is None
    assert p.bar_index is None


def test_pivot_field_count_matches_pine() -> None:
    """Pine `pivot` UDT tem 5 campos (linhas 39-44)."""
    assert len(Pivot.__dataclass_fields__) == 5


# ----- UDT Trend -----

def test_trend_field_count_matches_pine() -> None:
    """Pine `trend` UDT tem 1 campo (linhas 35-37)."""
    assert len(Trend.__dataclass_fields__) == 1
    assert Trend().bias is None


# ----- UDT Alerts -----

def test_alerts_has_16_fields_all_false_default() -> None:
    """Pine `alerts` UDT tem 16 booleans, todos default False."""
    fields = Alerts.__dataclass_fields__
    assert len(fields) == 16
    a = Alerts()
    for f in fields:
        assert getattr(a, f) is False, f"{f} should default to False"


def test_alerts_field_order_matches_pine() -> None:
    """Ordem dos 16 campos verbatim do Pine fonte (linhas 14-31)."""
    expected = [
        'internal_bullish_bos',
        'internal_bearish_bos',
        'internal_bullish_choch',
        'internal_bearish_choch',
        'swing_bullish_bos',
        'swing_bearish_bos',
        'swing_bullish_choch',
        'swing_bearish_choch',
        'internal_bullish_order_block',
        'internal_bearish_order_block',
        'swing_bullish_order_block',
        'swing_bearish_order_block',
        'equal_highs',
        'equal_lows',
        'bullish_fair_value_gap',
        'bearish_fair_value_gap',
    ]
    assert list(Alerts.__dataclass_fields__.keys()) == expected


# ----- UDT OrderBlock -----

def test_order_block_field_count_matches_pine() -> None:
    """Pine `orderBlock` UDT tem 4 campos (linhas 46-50)."""
    assert len(OrderBlock.__dataclass_fields__) == 4


def test_order_block_default_is_all_none() -> None:
    ob = OrderBlock()
    assert ob.bar_high is None
    assert ob.bar_low is None
    assert ob.bar_time is None
    assert ob.bias is None


# ----- UDT FairValueGap -----

def test_fair_value_gap_field_count_matches_pine() -> None:
    """Pine `fairValueGap` UDT tem 3 campos (linhas 30-33)."""
    assert len(FairValueGap.__dataclass_fields__) == 3


def test_fair_value_gap_default_is_all_none() -> None:
    fvg = FairValueGap()
    assert fvg.top is None
    assert fvg.bottom is None
    assert fvg.bias is None


# ----- UDT TrailingExtremes -----

def test_trailing_extremes_field_count_matches_pine() -> None:
    """Pine `trailingExtremes` UDT tem 6 campos (linhas 22-28)."""
    assert len(TrailingExtremes.__dataclass_fields__) == 6


def test_trailing_extremes_default_is_all_none() -> None:
    t = TrailingExtremes()
    assert t.top is None
    assert t.bottom is None
    assert t.bar_time is None
    assert t.bar_index is None
    assert t.last_top_time is None
    assert t.last_bottom_time is None


# ----- EngineState -----

def test_engine_state_has_exactly_17_attributes() -> None:
    """Mapa Camada 1 §2 + verbatim do Pine main() linhas 78-94."""
    assert len(EngineState.__dataclass_fields__) == 17


def test_engine_state_pivots_match_pine_init() -> None:
    """Pine: `pivot(na, na, False)` -> crossed=False, outros None."""
    s = EngineState()
    pivot_attrs = [
        'swing_high',
        'swing_low',
        'internal_high',
        'internal_low',
        'equal_high',
        'equal_low',
    ]
    for name in pivot_attrs:
        p = getattr(s, name)
        assert p.current_level is None, f"{name}.current_level should be None"
        assert p.last_level is None, f"{name}.last_level should be None"
        assert p.crossed is False, f"{name}.crossed should be False (Pine literal)"
        assert p.bar_time is None, f"{name}.bar_time should be None"
        assert p.bar_index is None, f"{name}.bar_index should be None"


def test_engine_state_trends_match_pine_init() -> None:
    """Pine: `trend(0)` -> bias=0 inteiro, NÃO None."""
    s = EngineState()
    assert s.swing_trend.bias == 0
    assert s.internal_trend.bias == 0


def test_engine_state_lists_start_empty() -> None:
    """Pine: array.new() / array.new_float() / array.new_int() -> listas vazias."""
    s = EngineState()
    assert s.fair_value_gaps == []
    assert s.parsed_highs == []
    assert s.parsed_lows == []
    assert s.highs == []
    assert s.lows == []
    assert s.times == []
    assert s.swing_order_blocks == []
    assert s.internal_order_blocks == []


def test_engine_state_trailing_default_is_all_none() -> None:
    """Pine: `trailingExtremes()` sem args -> todos campos `na`."""
    s = EngineState()
    t = s.trailing
    assert t.top is None
    assert t.bottom is None
    assert t.bar_time is None
    assert t.bar_index is None
    assert t.last_top_time is None
    assert t.last_bottom_time is None


def test_engine_state_pivot_attribute_names_match_pine() -> None:
    """6 pivots + 2 trends + 6 listas + 1 trailing + 2 OBs lists = 17."""
    expected = [
        'swing_high',
        'swing_low',
        'internal_high',
        'internal_low',
        'equal_high',
        'equal_low',
        'swing_trend',
        'internal_trend',
        'fair_value_gaps',
        'parsed_highs',
        'parsed_lows',
        'highs',
        'lows',
        'times',
        'trailing',
        'swing_order_blocks',
        'internal_order_blocks',
    ]
    assert list(EngineState.__dataclass_fields__.keys()) == expected


# ----- Mutação e isolamento -----

def test_pivot_mutation_works() -> None:
    """Garante mutabilidade — semântica Pine de pivot.crossed = True."""
    s = EngineState()
    s.swing_high.crossed = True
    s.swing_high.current_level = 100.5
    assert s.swing_high.crossed is True
    assert s.swing_high.current_level == 100.5


def test_engine_state_independence_lists() -> None:
    """default_factory garante listas independentes entre instâncias."""
    s1 = EngineState()
    s2 = EngineState()
    s1.parsed_highs.append(1.0)
    s1.swing_order_blocks.append(OrderBlock(bar_high=10.0, bar_low=5.0, bias=BULLISH))
    assert s2.parsed_highs == []
    assert s2.swing_order_blocks == []


def test_engine_state_independence_pivots() -> None:
    """default_factory garante objetos Pivot independentes entre instâncias."""
    s1 = EngineState()
    s2 = EngineState()
    s1.swing_high.crossed = True
    s1.swing_high.current_level = 99.0
    assert s2.swing_high.crossed is False
    assert s2.swing_high.current_level is None


def test_engine_state_independence_trends() -> None:
    """default_factory garante objetos Trend independentes entre instâncias."""
    s1 = EngineState()
    s2 = EngineState()
    s1.swing_trend.bias = BULLISH
    assert s2.swing_trend.bias == 0


# ----- Sanidade serialização -----

def test_pivot_asdict_roundtrip() -> None:
    """asdict() funciona — útil para debug/logging futuro."""
    p = Pivot(current_level=100.5, crossed=True, bar_index=42)
    d = asdict(p)
    assert d == {
        'current_level': 100.5,
        'last_level': None,
        'crossed': True,
        'bar_time': None,
        'bar_index': 42,
    }
