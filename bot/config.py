"""
Bot configuration. Load from environment variables for security.
NEVER hardcode API keys.
"""

import os


class Config:
    # Kraken API (set via environment variables)
    KRAKEN_API_KEY = os.environ.get("KRAKEN_API_KEY", "")
    KRAKEN_API_SECRET = os.environ.get("KRAKEN_API_SECRET", "")

    # Webhook
    WEBHOOK_HOST = os.environ.get("WEBHOOK_HOST", "127.0.0.1")
    WEBHOOK_PORT = int(os.environ.get("WEBHOOK_PORT", "5000"))
    WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "nexus-secret-change-me")

    # Risk
    RISK_PER_TRADE_PCT = float(os.environ.get("RISK_PER_TRADE", "1.0"))
    MAX_DAILY_LOSSES = int(os.environ.get("MAX_DAILY_LOSSES", "3"))
    MAX_DRAWDOWN_PCT = float(os.environ.get("MAX_DRAWDOWN_PCT", "10.0"))
    COOLDOWN_AFTER_LOSSES = int(os.environ.get("COOLDOWN_BARS", "5"))

    # Mode
    PAPER_TRADING = os.environ.get("PAPER_TRADING", "true").lower() == "true"

    # Logging
    JOURNAL_DIR = os.path.join(os.path.dirname(__file__), "journal")
