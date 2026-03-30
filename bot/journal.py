"""
Trade journal - logs every signal and trade for review.
"""

import json
import logging
import os
from datetime import datetime

from config import Config

logger = logging.getLogger("nexus.journal")


class Journal:
    def __init__(self, config: Config = Config()):
        self.journal_dir = config.JOURNAL_DIR
        os.makedirs(self.journal_dir, exist_ok=True)

    def _today_file(self) -> str:
        return os.path.join(self.journal_dir, f"{datetime.utcnow().strftime('%Y-%m-%d')}.jsonl")

    def log_signal(self, signal: dict):
        """Log incoming webhook signal."""
        entry = {
            "type": "signal",
            "timestamp": datetime.utcnow().isoformat(),
            "data": signal,
        }
        self._append(entry)

    def log_trade(self, order_result, risk_check: str):
        """Log trade execution."""
        entry = {
            "type": "trade",
            "timestamp": datetime.utcnow().isoformat(),
            "order_id": order_result.order_id,
            "symbol": order_result.symbol,
            "direction": order_result.direction,
            "entry": order_result.entry_price,
            "sl": order_result.sl_price,
            "tp": order_result.tp_price,
            "quantity": order_result.quantity,
            "status": order_result.status,
            "risk_check": risk_check,
        }
        self._append(entry)

    def log_skip(self, signal: dict, reason: str):
        """Log a skipped signal with reason."""
        entry = {
            "type": "skip",
            "timestamp": datetime.utcnow().isoformat(),
            "reason": reason,
            "signal": signal,
        }
        self._append(entry)

    def _append(self, entry: dict):
        path = self._today_file()
        with open(path, "a") as f:
            f.write(json.dumps(entry) + "\n")
        logger.debug(f"Journal: {entry['type']} logged to {path}")
