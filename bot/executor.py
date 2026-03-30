"""
Order executor - places trades on Kraken via CCXT.
Supports both live and paper trading modes.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

import ccxt
from config import Config

logger = logging.getLogger("nexus.executor")


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    direction: str
    entry_price: float
    sl_price: float
    tp_price: float
    quantity: float
    status: str  # "filled", "paper", "failed"
    timestamp: str
    error: str = ""


class Executor:
    def __init__(self, config: Config = Config()):
        self.config = config
        self.paper = config.PAPER_TRADING
        self._exchange = None

    @property
    def exchange(self):
        if self._exchange is None and not self.paper:
            self._exchange = ccxt.kraken(
                {
                    "apiKey": self.config.KRAKEN_API_KEY,
                    "secret": self.config.KRAKEN_API_SECRET,
                    "enableRateLimit": True,
                }
            )
        return self._exchange

    def place_order(
        self, symbol: str, direction: str, entry: float, sl: float, tp: float, quantity: float
    ) -> OrderResult:
        """
        Place a trade with SL and TP.
        In paper mode, logs the trade without touching the exchange.
        """
        timestamp = datetime.utcnow().isoformat()

        if self.paper:
            logger.info(
                f"PAPER {direction.upper()} {symbol} qty={quantity:.6f} entry={entry:.2f} sl={sl:.2f} tp={tp:.2f}"
            )
            return OrderResult(
                order_id=f"paper-{timestamp}",
                symbol=symbol,
                direction=direction,
                entry_price=entry,
                sl_price=sl,
                tp_price=tp,
                quantity=quantity,
                status="paper",
                timestamp=timestamp,
            )

        try:
            side = "buy" if direction == "long" else "sell"
            order = self.exchange.create_order(
                symbol=symbol,
                type="limit",
                side=side,
                amount=quantity,
                price=entry,
            )

            order_id = order.get("id", "unknown")
            logger.info(f"LIVE {direction.upper()} {symbol} order={order_id} qty={quantity:.6f} entry={entry:.2f}")

            # Place SL as stop-loss order
            sl_side = "sell" if direction == "long" else "buy"
            self.exchange.create_order(
                symbol=symbol,
                type="stop-loss",
                side=sl_side,
                amount=quantity,
                price=sl,
            )

            # Place TP as take-profit order
            self.exchange.create_order(
                symbol=symbol,
                type="take-profit",
                side=sl_side,
                amount=quantity,
                price=tp,
            )

            return OrderResult(
                order_id=order_id,
                symbol=symbol,
                direction=direction,
                entry_price=entry,
                sl_price=sl,
                tp_price=tp,
                quantity=quantity,
                status="filled",
                timestamp=timestamp,
            )

        except Exception as e:
            logger.error(f"Order failed: {e}")
            return OrderResult(
                order_id="",
                symbol=symbol,
                direction=direction,
                entry_price=entry,
                sl_price=sl,
                tp_price=tp,
                quantity=quantity,
                status="failed",
                timestamp=timestamp,
                error=str(e),
            )

    def get_balance(self, currency: str = "USDT") -> float:
        """Get available balance for position sizing."""
        if self.paper:
            return 10000.0  # Paper trading default balance
        try:
            balance = self.exchange.fetch_balance()
            return float(balance.get("free", {}).get(currency, 0))
        except Exception as e:
            logger.error(f"Balance fetch failed: {e}")
            return 0.0
