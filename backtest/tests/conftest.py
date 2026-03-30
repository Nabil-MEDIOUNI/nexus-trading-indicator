"""Shared fixtures for Nexus backtest tests."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_ohlcv():
    """Generate 500 bars of synthetic OHLCV data with a trend reversal."""
    np.random.seed(42)
    n = 500
    dates = pd.date_range("2025-01-01", periods=n, freq="h")

    # Uptrend (0-200), downtrend (200-350), uptrend (350-500)
    price = 100.0
    prices = []
    for i in range(n):
        if i < 200:
            drift = 0.05
        elif i < 350:
            drift = -0.08
        else:
            drift = 0.06
        change = drift + np.random.randn() * 0.5
        price = max(price + change, 10)
        prices.append(price)

    closes = np.array(prices)
    highs = closes + np.abs(np.random.randn(n)) * 0.3
    lows = closes - np.abs(np.random.randn(n)) * 0.3
    opens = closes + np.random.randn(n) * 0.15
    volumes = np.random.randint(100, 10000, n).astype(float)

    return pd.DataFrame(
        {
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        },
        index=dates,
    )


@pytest.fixture
def flat_ohlcv():
    """Generate flat/ranging market data (no trend)."""
    np.random.seed(99)
    n = 200
    dates = pd.date_range("2025-06-01", periods=n, freq="h")
    base = 50000.0
    closes = base + np.random.randn(n) * 50
    return pd.DataFrame(
        {
            "open": closes + np.random.randn(n) * 10,
            "high": closes + np.abs(np.random.randn(n)) * 30,
            "low": closes - np.abs(np.random.randn(n)) * 30,
            "close": closes,
            "volume": np.random.randint(100, 5000, n).astype(float),
        },
        index=dates,
    )
