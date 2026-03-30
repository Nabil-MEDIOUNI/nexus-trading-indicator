"""
OHLCV data fetching via CCXT (Kraken or any exchange).
Caches to CSV in backtest/data/ for reproducible runs.
"""

import os

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def fetch_ohlcv(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    exchange_id: str = "kraken",
    limit: int = 5000,
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Fetch OHLCV data from exchange or cache.
    Returns DataFrame with columns: open, high, low, close, volume
    and DatetimeIndex.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    cache_file = os.path.join(DATA_DIR, f"{symbol.replace('/', '_')}_{timeframe}_{exchange_id}.csv")

    if use_cache and os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        print(f"Loaded {len(df)} bars from cache: {cache_file}")
        return df

    try:
        import ccxt

        exchange = getattr(ccxt, exchange_id)()
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        df.to_csv(cache_file)
        print(f"Fetched {len(df)} bars from {exchange_id}, cached to {cache_file}")
        return df
    except ImportError as err:
        raise ImportError("ccxt not installed. Run: pip install ccxt") from err
    except Exception as e:
        raise RuntimeError(f"Failed to fetch data: {e}") from e


def timeframe_to_minutes(tf: str) -> int:
    """Convert timeframe string to minutes (e.g. '1h' -> 60, '5m' -> 5)."""
    tf = tf.lower().strip()
    if tf.endswith("m"):
        return int(tf[:-1])
    elif tf.endswith("h"):
        return int(tf[:-1]) * 60
    elif tf.endswith("d"):
        return int(tf[:-1]) * 1440
    elif tf.endswith("w"):
        return int(tf[:-1]) * 10080
    else:
        return 60
