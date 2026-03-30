"""Tests for individual indicator calculations."""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.indicators import (
    atr,
    choch_bos,
    compute_ema_alignment,
    detect_fvg,
    detect_pivots,
    liquidity_swings,
    smc_swing_zones,
    swing_length_for_tf,
)


class TestATR:
    def test_returns_series(self, sample_ohlcv):
        result = atr(sample_ohlcv, 14)
        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_ohlcv)

    def test_first_n_bars_are_nan(self, sample_ohlcv):
        result = atr(sample_ohlcv, 14)
        assert result.iloc[:13].isna().all()
        assert not result.iloc[14:].isna().any()

    def test_always_positive(self, sample_ohlcv):
        result = atr(sample_ohlcv, 14).dropna()
        assert (result > 0).all()


class TestDetectPivots:
    def test_returns_two_series(self, sample_ohlcv):
        ph, pl = detect_pivots(sample_ohlcv, 5)
        assert isinstance(ph, pd.Series)
        assert isinstance(pl, pd.Series)
        assert len(ph) == len(sample_ohlcv)

    def test_pivots_are_at_extremes(self, sample_ohlcv):
        ph, pl = detect_pivots(sample_ohlcv, 5)
        valid_highs = ph.dropna()
        valid_lows = pl.dropna()
        # Pivot highs should be actual high values
        for idx in valid_highs.index:
            assert valid_highs[idx] == sample_ohlcv.loc[idx, "high"]
        for idx in valid_lows.index:
            assert valid_lows[idx] == sample_ohlcv.loc[idx, "low"]

    def test_finds_pivots_in_trending_data(self, sample_ohlcv):
        ph, pl = detect_pivots(sample_ohlcv, 5)
        assert ph.notna().sum() > 0
        assert pl.notna().sum() > 0


class TestChochBos:
    def test_returns_series(self, sample_ohlcv):
        result = choch_bos(sample_ohlcv, 1)
        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_ohlcv)

    def test_values_are_valid(self, sample_ohlcv):
        result = choch_bos(sample_ohlcv, 1)
        unique = set(result.unique())
        assert unique.issubset({-1, 0, 1})

    def test_detects_direction_changes(self, sample_ohlcv):
        result = choch_bos(sample_ohlcv, 1)
        changes = (result != result.shift(1)).sum()
        assert changes > 0  # Should detect at least some structure shifts


class TestDetectFVG:
    def test_returns_two_lists(self, sample_ohlcv):
        up, dn = detect_fvg(sample_ohlcv)
        assert isinstance(up, list)
        assert isinstance(dn, list)

    def test_fvg_has_correct_structure(self, sample_ohlcv):
        up, dn = detect_fvg(sample_ohlcv)
        for f in up + dn:
            assert "bar" in f
            assert "top" in f
            assert "bottom" in f
            assert "active" in f
            assert f["top"] >= f["bottom"]  # top should be above bottom


class TestLiquiditySwings:
    def test_returns_four_series(self, sample_ohlcv):
        ph_top, pl_btm, sweep_h, sweep_l = liquidity_swings(sample_ohlcv, 14)
        assert len(ph_top) == len(sample_ohlcv)
        assert len(pl_btm) == len(sample_ohlcv)
        assert sweep_h.dtype == bool
        assert sweep_l.dtype == bool

    def test_sweeps_are_boolean(self, sample_ohlcv):
        _, _, sweep_h, sweep_l = liquidity_swings(sample_ohlcv, 14)
        assert set(sweep_h.unique()).issubset({True, False})
        assert set(sweep_l.unique()).issubset({True, False})


class TestSwingLengthForTF:
    def test_known_values(self):
        assert swing_length_for_tf(5) == 20
        assert swing_length_for_tf(15) == 25
        assert swing_length_for_tf(60) == 35
        assert swing_length_for_tf(240) == 40
        assert swing_length_for_tf(1440) == 20  # daily

    def test_default_fallback(self):
        assert swing_length_for_tf(999999) == 6  # monthly


class TestSmcSwingZones:
    def test_returns_two_series(self, sample_ohlcv):
        top, btm = smc_swing_zones(sample_ohlcv, 20)
        assert len(top) == len(sample_ohlcv)
        assert len(btm) == len(sample_ohlcv)

    def test_top_above_bottom(self, sample_ohlcv):
        top, btm = smc_swing_zones(sample_ohlcv, 20)
        valid = top.notna() & btm.notna()
        assert (top[valid] >= btm[valid]).all()


class TestEmaAlignment:
    def test_returns_series(self, sample_ohlcv):
        result = compute_ema_alignment(sample_ohlcv)
        assert isinstance(result, pd.Series)
        assert len(result) == len(sample_ohlcv)

    def test_values_are_valid(self, sample_ohlcv):
        result = compute_ema_alignment(sample_ohlcv)
        unique = set(result.dropna().unique())
        assert unique.issubset({-1, 0, 1})

    def test_bullish_when_ema50_above(self):
        n = 300
        dates = pd.date_range("2025-01-01", periods=n, freq="h")
        prices = np.linspace(100, 200, n)
        df = pd.DataFrame(
            {
                "open": prices,
                "high": prices + 1,
                "low": prices - 1,
                "close": prices,
                "volume": np.ones(n) * 1000,
            },
            index=dates,
        )
        result = compute_ema_alignment(df)
        assert result.iloc[-1] == 1

    def test_bearish_when_ema50_below(self):
        n = 300
        dates = pd.date_range("2025-01-01", periods=n, freq="h")
        prices = np.linspace(200, 100, n)
        df = pd.DataFrame(
            {
                "open": prices,
                "high": prices + 1,
                "low": prices - 1,
                "close": prices,
                "volume": np.ones(n) * 1000,
            },
            index=dates,
        )
        result = compute_ema_alignment(df)
        assert result.iloc[-1] == -1
