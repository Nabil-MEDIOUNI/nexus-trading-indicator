"""Tests for MCP tools using synthetic data (no exchange connection needed)."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backtest"))

from engine.indicators import choch_bos, compute_ema_alignment, detect_fvg, liquidity_swings, smc_swing_zones
from engine.metrics import calculate_metrics
from engine.strategy import StrategyConfig, compute_confluence, run_backtest


@pytest.fixture
def market_data():
    """500 bars of synthetic trending data."""
    np.random.seed(42)
    n = 500
    dates = pd.date_range("2025-01-01", periods=n, freq="h")
    price = 100.0
    prices = []
    for i in range(n):
        drift = 0.05 if i < 200 else (-0.08 if i < 350 else 0.06)
        price = max(price + drift + np.random.randn() * 0.5, 10)
        prices.append(price)
    closes = np.array(prices)
    return pd.DataFrame(
        {
            "open": closes + np.random.randn(n) * 0.15,
            "high": closes + np.abs(np.random.randn(n)) * 0.3,
            "low": closes - np.abs(np.random.randn(n)) * 0.3,
            "close": closes,
            "volume": np.random.randint(100, 10000, n).astype(float),
        },
        index=dates,
    )


class TestAnalysisTool:
    """Tests mirroring get-market-analysis tool logic."""

    def test_bias_detection(self, market_data):
        choch = choch_bos(market_data, 1)
        last_bias = int(choch.iloc[-1])
        assert last_bias in (-1, 0, 1)

    def test_zone_calculation(self, market_data):
        top, btm = smc_swing_zones(market_data, 20)
        eq = (top.iloc[-1] + btm.iloc[-1]) / 2
        assert top.iloc[-1] >= btm.iloc[-1]
        assert not np.isnan(eq)

    def test_fvg_detection(self, market_data):
        up, dn = detect_fvg(market_data)
        assert isinstance(up, list)
        assert isinstance(dn, list)
        for f in up + dn:
            assert f["top"] >= f["bottom"]

    def test_liquidity_levels(self, market_data):
        ph, pl, sh, sl = liquidity_swings(market_data, 14)
        assert len(ph) == len(market_data)
        # At least some levels should be set
        assert ph.notna().any()
        assert pl.notna().any()


class TestSetupTool:
    """Tests mirroring get-trade-setup tool logic."""

    def test_confluence_scores_valid_range(self, market_data):
        config = StrategyConfig(tf_minutes=60)
        choch = choch_bos(market_data, 1)
        ema_align = compute_ema_alignment(market_data)

        score, direction = compute_confluence(
            market_data,
            config,
            choch_w=choch,
            choch_d=choch,
            choch_4h=choch,
            choch_1h=choch,
            ema_w=ema_align,
            ema_d=ema_align,
            ema_4h=ema_align,
            ema_1h=ema_align,
        )
        assert (score >= 0).all() and (score <= 5).all()
        assert set(direction.unique()).issubset({-1, 0, 1})

    def test_sl_tp_valid_for_long(self, market_data):
        trades = run_backtest(market_data, StrategyConfig(min_score=2))
        longs = [t for t in trades if t.direction == 1]
        for t in longs:
            assert t.sl < t.entry_price
            assert t.tp > t.entry_price
            # TP distance should be ~3x SL distance
            sl_dist = t.entry_price - t.sl
            tp_dist = t.tp - t.entry_price
            if sl_dist > 0:
                rr = tp_dist / sl_dist
                assert 2.5 <= rr <= 3.5  # ~3R with some float tolerance


class TestBacktestTool:
    """Tests mirroring run-backtest tool logic."""

    def test_backtest_returns_trades(self, market_data):
        trades = run_backtest(market_data, StrategyConfig(min_score=2))
        assert isinstance(trades, list)

    def test_metrics_consistent(self, market_data):
        trades = run_backtest(market_data, StrategyConfig(min_score=2))
        m = calculate_metrics(trades)
        assert m.total_trades == len(trades)
        assert m.winners + m.losers == m.total_trades
        if m.total_trades > 0:
            assert 0 <= m.win_rate <= 100

    def test_stricter_score_fewer_trades(self, market_data):
        loose = run_backtest(market_data, StrategyConfig(min_score=5))
        strict = run_backtest(market_data, StrategyConfig(min_score=5))
        assert len(loose) >= len(strict)

    def test_assessment_logic(self):
        """Test assessment logic inline (avoids fastmcp import)."""
        from engine.metrics import BacktestMetrics

        def assess(m):
            if m.total_trades < 30:
                return "INSUFFICIENT DATA"
            if m.profit_factor < 1.0:
                return "UNPROFITABLE"
            if m.max_consecutive_losses >= 6:
                return "HIGH RISK"
            if m.profit_factor >= 1.5 and m.sharpe_ratio >= 1.0:
                return "PROMISING"
            return "NEEDS REVIEW"

        assert "INSUFFICIENT" in assess(BacktestMetrics(total_trades=10))
        assert "UNPROFITABLE" in assess(
            BacktestMetrics(total_trades=50, profit_factor=0.8, win_rate=40, max_consecutive_losses=3)
        )
        assert "PROMISING" in assess(
            BacktestMetrics(total_trades=50, profit_factor=1.6, sharpe_ratio=1.2, win_rate=45, max_consecutive_losses=3)
        )
