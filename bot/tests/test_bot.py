"""Tests for trading bot components."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import Config
from risk_engine import RiskEngine


class TestRiskEngine:
    def setup_method(self):
        self.config = Config()
        self.config.MAX_DAILY_LOSSES = 3
        self.config.MAX_DRAWDOWN_PCT = 10.0
        self.config.RISK_PER_TRADE_PCT = 1.0
        self.config.COOLDOWN_AFTER_LOSSES = 5
        self.risk = RiskEngine(self.config)
        self.risk.init_equity(10000.0)

    def test_can_trade_initially(self):
        ok, reason = self.risk.can_trade()
        assert ok is True
        assert reason == "OK"

    def test_daily_loss_limit(self):
        # Directly set daily losses to simulate hitting the limit
        self.risk.state.daily_losses = 3
        self.risk.state.current_day = __import__("datetime").date.today().isoformat()
        ok, reason = self.risk.can_trade()
        assert ok is False
        assert "Daily loss limit" in reason

    def test_position_sizing_1pct(self):
        qty = self.risk.calculate_position_size(10000, 100, 95)
        # 1% of 10000 = 100. SL distance = 5. qty = 100/5 = 20
        assert qty == pytest.approx(20.0)

    def test_position_sizing_zero_sl(self):
        qty = self.risk.calculate_position_size(10000, 100, 100)
        assert qty == 0.0

    def test_consecutive_loss_cooldown(self):
        self.risk.record_trade(-50)
        self.risk.record_trade(-50)
        self.risk.record_trade(-50)  # Triggers cooldown
        # Reset daily losses to not hit that limit
        self.risk.state.daily_losses = 0
        ok, reason = self.risk.can_trade()
        assert ok is False
        assert "Cooldown" in reason

    def test_win_resets_consecutive(self):
        self.risk.record_trade(-50)
        self.risk.record_trade(-50)
        self.risk.record_trade(100)  # Win resets streak
        assert self.risk.state.consecutive_losses == 0

    def test_drawdown_circuit_breaker(self):
        self.risk.init_equity(10000)
        # Simulate 10% drawdown
        self.risk.state.current_equity = 8900
        ok, reason = self.risk.can_trade()
        assert ok is False
        assert "drawdown" in reason.lower()

    def test_peak_equity_tracks_highs(self):
        self.risk.init_equity(10000)
        self.risk.record_trade(500)
        assert self.risk.state.peak_equity == 10500
        self.risk.record_trade(-200)
        assert self.risk.state.peak_equity == 10500  # Didn't decrease


class TestExecutor:
    def test_paper_mode_returns_paper_status(self):
        from executor import Executor

        config = Config()
        config.PAPER_TRADING = True
        ex = Executor(config)
        result = ex.place_order("BTC/USDT", "long", 42000, 41500, 43500, 0.01)
        assert result.status == "paper"
        assert result.direction == "long"
        assert result.quantity == 0.01

    def test_paper_balance(self):
        from executor import Executor

        config = Config()
        config.PAPER_TRADING = True
        ex = Executor(config)
        assert ex.get_balance() == 10000.0


class TestWebhook:
    def setup_method(self):
        os.environ["PAPER_TRADING"] = "true"
        from consumer import app

        self.client = app.test_client()

    def test_health_endpoint(self):
        resp = self.client.get("/health")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "running"
        assert data["paper_mode"] is True

    def test_valid_entry_signal(self):
        payload = {
            "signal": "entry",
            "dir": "long",
            "entry": 42000,
            "sl": 41500,
            "tp": 43500,
            "score": 5,
            "rr": 3.0,
            "ticker": "BTCUSDT",
            "tf": "60",
        }
        resp = self.client.post("/webhook", json=payload)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "paper"
        assert data["direction"] == "long"

    def test_missing_fields_rejected(self):
        payload = {"signal": "entry", "dir": "long"}
        resp = self.client.post("/webhook", json=payload)
        assert resp.status_code == 400

    def test_non_entry_signal_ignored(self):
        payload = {"signal": "info", "data": "test"}
        resp = self.client.post("/webhook", json=payload)
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "ignored"

    def test_invalid_json_rejected(self):
        resp = self.client.post("/webhook", data="not json", content_type="text/plain")
        assert resp.status_code == 400
