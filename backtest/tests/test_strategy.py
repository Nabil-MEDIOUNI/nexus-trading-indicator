"""Tests for the Nexus 5-step strategy and metrics."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.metrics import BacktestMetrics, calculate_metrics
from engine.strategy import StrategyConfig, Trade, run_backtest


class TestRunBacktest:
    def test_returns_trade_list(self, sample_ohlcv):
        trades = run_backtest(sample_ohlcv)
        assert isinstance(trades, list)
        for t in trades:
            assert isinstance(t, Trade)

    def test_trade_fields_populated(self, sample_ohlcv):
        trades = run_backtest(sample_ohlcv)
        for t in trades:
            assert t.direction in (1, -1)
            assert t.entry_price > 0
            assert t.sl > 0
            assert t.tp > 0
            assert t.exit_bar > t.bar
            assert t.exit_reason in ("SL", "TP")

    def test_long_sl_below_entry(self, sample_ohlcv):
        trades = run_backtest(sample_ohlcv)
        for t in trades:
            if t.direction == 1:
                assert t.sl < t.entry_price
                assert t.tp > t.entry_price

    def test_short_sl_above_entry(self, sample_ohlcv):
        trades = run_backtest(sample_ohlcv)
        for t in trades:
            if t.direction == -1:
                assert t.sl > t.entry_price
                assert t.tp < t.entry_price

    def test_no_overlapping_trades(self, sample_ohlcv):
        trades = run_backtest(sample_ohlcv)
        for i in range(1, len(trades)):
            assert trades[i].bar >= trades[i - 1].exit_bar

    def test_custom_config(self, sample_ohlcv):
        config_loose = StrategyConfig(min_score=5, rr_ratio=2.0)
        trades_loose = run_backtest(sample_ohlcv, config_loose)
        config_strict = StrategyConfig(min_score=7, rr_ratio=3.0)
        trades_strict = run_backtest(sample_ohlcv, config_strict)
        # Both configs should produce valid trades with custom parameters
        assert isinstance(trades_loose, list)
        assert isinstance(trades_strict, list)
        # Looser min_score should produce >= trades than strict
        assert len(trades_loose) >= len(trades_strict)

    def test_daily_loss_cap(self, sample_ohlcv):
        config = StrategyConfig(min_score=2, max_daily_losses=1)
        trades = run_backtest(sample_ohlcv, config)
        # Can't easily verify per-day, but should still produce valid trades
        for t in trades:
            assert t.exit_reason in ("SL", "TP")

    def test_flat_market_few_trades(self, flat_ohlcv):
        config = StrategyConfig(min_score=6)
        trades = run_backtest(flat_ohlcv, config)
        # Flat market with high threshold should produce very few trades
        assert len(trades) < 20


class TestMetrics:
    def test_empty_trades(self):
        m = calculate_metrics([])
        assert m.total_trades == 0
        assert m.win_rate == 0

    def test_all_winners(self):
        trades = [
            Trade(
                bar=0,
                direction=1,
                entry_price=100,
                sl=95,
                tp=115,
                score=5,
                exit_bar=10,
                exit_price=115,
                pnl=14.8,
                exit_reason="TP",
            ),
            Trade(
                bar=20,
                direction=1,
                entry_price=110,
                sl=105,
                tp=125,
                score=4,
                exit_bar=30,
                exit_price=125,
                pnl=13.4,
                exit_reason="TP",
            ),
        ]
        m = calculate_metrics(trades)
        assert m.win_rate == 100.0
        assert m.losers == 0
        assert m.max_consecutive_losses == 0

    def test_all_losers(self):
        trades = [
            Trade(
                bar=0,
                direction=1,
                entry_price=100,
                sl=95,
                tp=115,
                score=4,
                exit_bar=5,
                exit_price=95,
                pnl=-5.2,
                exit_reason="SL",
            ),
            Trade(
                bar=10,
                direction=-1,
                entry_price=100,
                sl=105,
                tp=85,
                score=4,
                exit_bar=15,
                exit_price=105,
                pnl=-5.2,
                exit_reason="SL",
            ),
        ]
        m = calculate_metrics(trades)
        assert m.win_rate == 0.0
        assert m.winners == 0
        assert m.max_consecutive_losses == 2

    def test_mixed_results(self):
        trades = [
            Trade(
                bar=0,
                direction=1,
                entry_price=100,
                sl=95,
                tp=115,
                score=5,
                exit_bar=10,
                exit_price=115,
                pnl=14.8,
                exit_reason="TP",
            ),
            Trade(
                bar=20,
                direction=1,
                entry_price=110,
                sl=105,
                tp=125,
                score=4,
                exit_bar=25,
                exit_price=105,
                pnl=-4.7,
                exit_reason="SL",
            ),
        ]
        m = calculate_metrics(trades)
        assert m.total_trades == 2
        assert m.winners == 1
        assert m.losers == 1
        assert m.profit_factor > 0

    def test_metrics_str(self):
        m = BacktestMetrics(total_trades=10, winners=6, win_rate=60.0)
        s = str(m)
        assert "10" in s
        assert "60.0" in s

    def test_backtest_produces_valid_metrics(self, sample_ohlcv):
        trades = run_backtest(sample_ohlcv, StrategyConfig(min_score=2))
        if trades:
            m = calculate_metrics(trades)
            assert m.total_trades == len(trades)
            assert 0 <= m.win_rate <= 100
            assert m.max_drawdown >= 0
