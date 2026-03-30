"""
Risk engine - position sizing, daily loss tracking, drawdown circuit breaker.
"""

import logging
from dataclasses import dataclass
from datetime import date

from config import Config

logger = logging.getLogger("nexus.risk")


@dataclass
class RiskState:
    daily_losses: int = 0
    daily_trades: int = 0
    current_day: str = ""
    peak_equity: float = 0.0
    current_equity: float = 0.0
    total_pnl: float = 0.0
    consecutive_losses: int = 0
    cooldown_remaining: int = 0


class RiskEngine:
    def __init__(self, config: Config = Config()):
        self.config = config
        self.state = RiskState()

    def reset_daily(self):
        """Reset daily counters if new day."""
        today = date.today().isoformat()
        if today != self.state.current_day:
            logger.info(f"New trading day: {today} (prev losses: {self.state.daily_losses})")
            self.state.daily_losses = 0
            self.state.daily_trades = 0
            self.state.current_day = today

    def can_trade(self) -> tuple[bool, str]:
        """Check if trading is allowed. Returns (allowed, reason)."""
        self.reset_daily()

        if self.state.daily_losses >= self.config.MAX_DAILY_LOSSES:
            return False, f"Daily loss limit reached ({self.state.daily_losses}/{self.config.MAX_DAILY_LOSSES})"

        if self.state.cooldown_remaining > 0:
            self.state.cooldown_remaining -= 1
            return False, f"Cooldown active ({self.state.cooldown_remaining} remaining)"

        if self.state.peak_equity > 0:
            drawdown = (self.state.peak_equity - self.state.current_equity) / self.state.peak_equity * 100
            if drawdown >= self.config.MAX_DRAWDOWN_PCT:
                return False, f"Max drawdown breached ({drawdown:.1f}% >= {self.config.MAX_DRAWDOWN_PCT}%)"

        return True, "OK"

    def calculate_position_size(self, balance: float, entry: float, sl: float) -> float:
        """
        Calculate position size based on 1% risk rule.
        Returns quantity in base currency.
        """
        sl_distance = abs(entry - sl)
        if sl_distance == 0 or entry == 0:
            return 0.0

        risk_amount = balance * (self.config.RISK_PER_TRADE_PCT / 100)
        quantity = risk_amount / sl_distance
        return quantity

    def record_trade(self, pnl: float):
        """Record trade result and update risk state."""
        self.state.daily_trades += 1
        self.state.total_pnl += pnl
        self.state.current_equity += pnl

        if self.state.current_equity > self.state.peak_equity:
            self.state.peak_equity = self.state.current_equity

        if pnl < 0:
            self.state.daily_losses += 1
            self.state.consecutive_losses += 1
            if self.state.consecutive_losses >= 3:
                self.state.cooldown_remaining = self.config.COOLDOWN_AFTER_LOSSES
                logger.warning(
                    f"3 consecutive losses - cooldown activated ({self.config.COOLDOWN_AFTER_LOSSES} periods)"
                )
        else:
            self.state.consecutive_losses = 0

        logger.info(
            f"Trade recorded: PnL={pnl:.2f} | Daily losses={self.state.daily_losses} | Equity={self.state.current_equity:.2f}"
        )

    def init_equity(self, balance: float):
        """Initialize equity tracking from current balance."""
        self.state.current_equity = balance
        self.state.peak_equity = balance
