"""
Nexus Trading Indicator - Python port of Pine Script detection logic.
Each function takes a pandas DataFrame with OHLCV columns and returns signals.
"""

import numpy as np
import pandas as pd


def swing_length_for_tf(tf_minutes: int) -> int:
    """Auto-adjust swing length based on timeframe (mirrors Pine smc_swing_len)."""
    if tf_minutes <= 5:
        return 20
    elif tf_minutes <= 15:
        return 25
    elif tf_minutes <= 30:
        return 30
    elif tf_minutes <= 60:
        return 35
    elif tf_minutes <= 240:
        return 40
    elif tf_minutes <= 1440:  # daily
        return 20
    elif tf_minutes <= 10080:  # weekly
        return 12
    else:
        return 6


def atr(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Average True Range."""
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def detect_pivots(df: pd.DataFrame, length: int) -> tuple[pd.Series, pd.Series]:
    """Detect pivot highs and lows. Vectorized using rolling max/min (O(n) instead of O(n*length))."""
    if len(df) < 2 * length + 1:
        return pd.Series(np.nan, index=df.index), pd.Series(np.nan, index=df.index)

    high = df["high"].values
    low = df["low"].values
    window = 2 * length + 1

    rolling_max = pd.Series(high).rolling(window, center=True).max().values
    rolling_min = pd.Series(low).rolling(window, center=True).min().values

    ph_mask = high == rolling_max
    pl_mask = low == rolling_min

    # Edges are invalid (incomplete window)
    ph_mask[:length] = False
    ph_mask[-length:] = False
    pl_mask[:length] = False
    pl_mask[-length:] = False

    ph = pd.Series(np.where(ph_mask, high, np.nan), index=df.index)
    pl = pd.Series(np.where(pl_mask, low, np.nan), index=df.index)
    return ph, pl


def choch_bos(df: pd.DataFrame, pivot_length: int = 1) -> pd.Series:
    """
    ChoCH/BOS detection. Returns series of direction: 1=bullish, -1=bearish, 0=neutral.
    Uses numpy arrays for performance (avoids .iloc overhead).
    """
    ph, pl = detect_pivots(df, pivot_length)
    n = len(df)
    ph_vals = ph.values
    pl_vals = pl.values
    close = df["close"].values
    os_arr = np.zeros(n, dtype=np.int8)

    upper_val = np.nan
    upper_crossed = False
    lower_val = np.nan
    lower_crossed = False
    current_os = 0

    for i in range(n):
        if not np.isnan(ph_vals[i]):
            upper_val = ph_vals[i]
            upper_crossed = False
        if not np.isnan(pl_vals[i]):
            lower_val = pl_vals[i]
            lower_crossed = False
        if not np.isnan(upper_val) and not upper_crossed and close[i] > upper_val:
            if i > 0 and close[i - 1] <= upper_val:
                current_os = 1
                upper_crossed = True
        if not np.isnan(lower_val) and not lower_crossed and close[i] < lower_val:
            if i > 0 and close[i - 1] >= lower_val:
                current_os = -1
                lower_crossed = True
        os_arr[i] = current_os

    return pd.Series(os_arr, index=df.index)


def detect_fvg(df: pd.DataFrame, body_threshold: float = 0.36) -> tuple[list, list]:
    """
    Detect Fair Value Gaps. Returns lists of dicts with {bar, top, bottom, active}.
    """
    fvg_up = []
    fvg_dn = []
    body = (df["close"] - df["open"]).abs()
    mx = pd.concat([df["close"], df["open"]], axis=1).max(axis=1)
    mn = pd.concat([df["close"], df["open"]], axis=1).min(axis=1)
    mean_body = body.rolling(2).mean()

    for i in range(2, len(df)):
        b = body.iloc[i - 1]
        mb = mean_body.iloc[i - 1]
        if np.isnan(mb) or mb == 0:
            continue

        is_large = b > mb
        upper_wick = df["high"].iloc[i - 1] - mx.iloc[i - 1]
        lower_wick = mn.iloc[i - 1] - df["low"].iloc[i - 1]
        is_body_candle = upper_wick < b * body_threshold and lower_wick < b * body_threshold

        if is_large and is_body_candle:
            if df["close"].iloc[i - 1] > df["open"].iloc[i - 1]:  # bullish candle
                if df["low"].iloc[i] > df["high"].iloc[i - 2]:  # gap up
                    fvg_up.append(
                        {"bar": i, "top": df["low"].iloc[i], "bottom": df["high"].iloc[i - 2], "active": True}
                    )
            else:  # bearish candle
                if df["high"].iloc[i] < df["low"].iloc[i - 2]:  # gap down
                    fvg_dn.append(
                        {"bar": i, "top": df["low"].iloc[i - 2], "bottom": df["high"].iloc[i], "active": True}
                    )

    return fvg_up, fvg_dn


def liquidity_swings(df: pd.DataFrame, length: int = 14) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """
    Detect liquidity sweeps. Returns:
    - liq_ph_top: swing high level
    - liq_pl_btm: swing low level
    - sweep_high: boolean series (True on bar where high is swept)
    - sweep_low: boolean series (True on bar where low is swept)
    """
    ph, pl = detect_pivots(df, length)
    n = len(df)

    liq_ph_top = pd.Series(np.nan, index=df.index)
    liq_pl_btm = pd.Series(np.nan, index=df.index)
    sweep_high = pd.Series(False, index=df.index)
    sweep_low = pd.Series(False, index=df.index)

    current_ph_top = np.nan
    current_pl_btm = np.nan
    ph_crossed = False
    pl_crossed = False

    for i in range(n):
        if not np.isnan(ph.iloc[i]):
            current_ph_top = ph.iloc[i]
            ph_crossed = False

        if not np.isnan(pl.iloc[i]):
            current_pl_btm = pl.iloc[i]
            pl_crossed = False

        liq_ph_top.iloc[i] = current_ph_top
        liq_pl_btm.iloc[i] = current_pl_btm

        if not np.isnan(current_ph_top) and df["close"].iloc[i] > current_ph_top and not ph_crossed:
            ph_crossed = True
            sweep_high.iloc[i] = True

        if not np.isnan(current_pl_btm) and df["close"].iloc[i] < current_pl_btm and not pl_crossed:
            pl_crossed = True
            sweep_low.iloc[i] = True

    return liq_ph_top, liq_pl_btm, sweep_high, sweep_low


def smc_swing_zones(df: pd.DataFrame, swing_len: int) -> tuple[pd.Series, pd.Series]:
    """
    Track SMC trailing swing top/bottom (for premium/discount zones).
    Uses precomputed rolling max/min for O(n) performance.
    """
    high = df["high"].values
    low = df["low"].values
    n = len(df)
    if n == 0:
        return pd.Series(dtype=float), pd.Series(dtype=float)

    rolling_high = pd.Series(high).rolling(swing_len + 1, min_periods=1).max().values
    rolling_low = pd.Series(low).rolling(swing_len + 1, min_periods=1).min().values

    trail_top = np.empty(n)
    trail_btm = np.empty(n)
    current_top = high[0]
    current_btm = low[0]

    for i in range(n):
        current_top = max(high[i], current_top)
        current_btm = min(low[i], current_btm)

        if i >= swing_len:
            if high[i] == rolling_high[i] and low[i - swing_len] == rolling_low[i]:
                current_btm = rolling_low[i]

        trail_top[i] = current_top
        trail_btm[i] = current_btm

    return pd.Series(trail_top, index=df.index), pd.Series(trail_btm, index=df.index)


def compute_ema_alignment(df: pd.DataFrame, fast: int = 50, mid: int = 100, slow: int = 200) -> pd.Series:
    """
    EMA alignment: 1 (bullish) when fast > mid AND fast > slow,
    -1 (bearish) when fast < mid AND fast < slow, 0 (neutral) otherwise.
    Mirrors Pine bias_ema() function.
    """
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_mid = df["close"].ewm(span=mid, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()

    bullish = (ema_fast > ema_mid) & (ema_fast > ema_slow)
    bearish = (ema_fast < ema_mid) & (ema_fast < ema_slow)

    result = pd.Series(0, index=df.index, dtype=np.int8)
    result[bullish] = 1
    result[bearish] = -1
    return result
