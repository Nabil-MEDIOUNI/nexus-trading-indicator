"""
Nexus Dashboard Scoring Engine.
Fetches multi-TF data via CCXT and computes confluence + entry scores.
Uses the same indicator logic as the backtest engine for consistency.
"""

import logging
import os
import sys
import time as _time
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

# Add backtest engine to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backtest"))

from engine.data import fetch_ohlcv
from engine.indicators import choch_bos, compute_ema_alignment, detect_fvg

logger = logging.getLogger("nexus.scoring")

# --- Data Cache ---
# Cache fetched data to avoid Kraken rate limits.
# Each TF has its own cache TTL (higher TFs change less often).
_cache = {}  # {tf: {"data": df, "expires": timestamp}}
CACHE_TTL = {
    "1w": 3600,  # Weekly: cache 1 hour
    "1d": 600,  # Daily: cache 10 min
    "4h": 300,  # 4H: cache 5 min
    "1h": 120,  # 1H: cache 2 min
    "15m": 60,  # 15m: cache 1 min
    "5m": 30,  # 5m: cache 30 sec
    "1m": 15,  # 1m: cache 15 sec
}


def _fetch_cached(symbol: str, tf: str, exchange: str) -> pd.DataFrame:
    """Fetch OHLCV with per-TF caching to avoid rate limits."""
    cache_key = f"{symbol}_{tf}_{exchange}"
    now = _time.time()

    if cache_key in _cache and now < _cache[cache_key]["expires"]:
        return _cache[cache_key]["data"]

    try:
        df = fetch_ohlcv(symbol, tf, exchange, limit=500, use_cache=False)
        ttl = CACHE_TTL.get(tf, 60)
        _cache[cache_key] = {"data": df, "expires": now + ttl}
        return df
    except Exception as e:
        logger.warning(f"Fetch failed for {tf}: {e}")
        # Return stale cache if available
        if cache_key in _cache:
            return _cache[cache_key]["data"]
        return pd.DataFrame()


# Timeframes for confluence (HTF)
CONFLUENCE_TFS = ["1w", "1d", "4h", "1h"]
# Timeframes for entry (LTF)
ENTRY_TFS = ["15m", "5m", "1m"]
# Timeframes for FVG detection
FVG_TFS = ["4h", "1h", "15m"]


@dataclass
class TFBias:
    """CHoCH and EMA state for a single timeframe."""

    timeframe: str
    choch: int = 0  # 1=bullish, -1=bearish, 0=neutral
    ema: int = 0  # 1=bullish, -1=bearish, 0=neutral


@dataclass
class FVGZone:
    """Active FVG zone."""

    timeframe: str
    top: float
    bottom: float
    is_bull: bool


@dataclass
class DashboardScores:
    """Complete scoring state for the dashboard."""

    # Confluence (HTF)
    confluence_tfs: list = field(default_factory=list)  # list of TFBias
    confluence_score: int = 0  # max 5

    # Direction
    direction: int = 0  # 1=long, -1=short, 0=neutral
    direction_text: str = "NEUTRAL"

    # Confluence details (for tooltip)
    wd_aligned: bool = False
    d4h_aligned: bool = False
    h4h1h_aligned: bool = False
    all_same: bool = False
    ema_confirm_count: int = 0
    ema_confirmed: bool = False
    is_primary: bool = False
    is_secondary: bool = False

    # Entry (LTF)
    entry_tfs: list = field(default_factory=list)  # list of TFBias

    # Entry details (for tooltip)
    entry_15m5m_aligned: bool = False
    entry_5m1m_aligned: bool = False
    entry_all_ltf: bool = False
    entry_ema_count: int = 0
    entry_ema_confirmed: bool = False

    # FVG
    fvg_active: bool = False
    fvg_tf: str = ""
    fvg_dir: str = ""
    fvg_top: float = 0.0
    fvg_bottom: float = 0.0

    entry_score: int = 0  # max 5

    # Session
    session: str = "Off Hours"

    # Meta
    symbol: str = ""
    price: float = 0.0
    timestamp: str = ""


def _get_last_choch_ema(df: pd.DataFrame) -> tuple:
    """Get the last confirmed CHoCH and EMA values from a dataframe."""
    if df.empty or len(df) < 2:
        return 0, 0
    choch = choch_bos(df, pivot_length=1)
    ema = compute_ema_alignment(df)
    # Use second-to-last bar (confirmed, like Pine [1] offset)
    return int(choch.iloc[-2]), int(ema.iloc[-2])


def _detect_active_fvg(df: pd.DataFrame, price: float) -> tuple:
    """Detect if price is inside an active FVG. Returns (is_active, top, bottom, is_bull)."""
    if df.empty or len(df) < 5:
        return False, 0.0, 0.0, False

    fvg_up, fvg_dn = detect_fvg(df)

    # Check bullish FVGs (price dips into zone)
    for fvg in reversed(fvg_up):
        if fvg["active"] and price <= fvg["top"] and price > fvg["bottom"]:
            return True, fvg["top"], fvg["bottom"], True

    # Check bearish FVGs (price rises into zone)
    for fvg in reversed(fvg_dn):
        if fvg["active"] and price >= fvg["bottom"] and price < fvg["top"]:
            return True, fvg["top"], fvg["bottom"], False

    return False, 0.0, 0.0, False


def _detect_session() -> str:
    """Detect current trading session based on UTC time."""
    hour = datetime.utcnow().hour
    # NY: 13:00-22:00 UTC, London: 07:00-16:00 UTC, Asia: 00:00-09:00 UTC
    is_ny = 13 <= hour < 22
    is_ldn = 7 <= hour < 16
    is_asia = 0 <= hour < 9

    if is_ny and is_ldn:
        return "London / NY"
    elif is_ny:
        return "New York"
    elif is_ldn:
        return "London"
    elif is_asia:
        return "Asia"
    else:
        return "Off Hours"


def compute_scores(symbol: str = "BTC/USDT", exchange: str = "kraken") -> DashboardScores:
    """
    Compute all confluence + entry scores by fetching real multi-TF data.
    This is the core function that replaces Pine's request.security().
    """
    scores = DashboardScores(symbol=symbol, timestamp=datetime.utcnow().isoformat())

    try:
        # Fetch data for all timeframes (cached to avoid rate limits)
        tf_data = {}
        for tf in CONFLUENCE_TFS + ENTRY_TFS + FVG_TFS:
            if tf not in tf_data:
                tf_data[tf] = _fetch_cached(symbol, tf, exchange)

        # Current price from shortest timeframe
        shortest_tf = ENTRY_TFS[-1]  # 1m
        if not tf_data[shortest_tf].empty:
            scores.price = float(tf_data[shortest_tf]["close"].iloc[-1])

        # === CONFLUENCE (HTF) ===
        bias = {}
        for tf in CONFLUENCE_TFS:
            df = tf_data.get(tf, pd.DataFrame())
            choch, ema = _get_last_choch_ema(df)
            tf_label = tf.upper().replace("1W", "Weekly").replace("1D", "Daily").replace("4H", "4H").replace("1H", "1H")
            bias[tf] = TFBias(timeframe=tf_label, choch=choch, ema=ema)

        scores.confluence_tfs = [bias[tf] for tf in CONFLUENCE_TFS]

        w = bias["1w"]
        d = bias["1d"]
        h4 = bias["4h"]
        h1 = bias["1h"]

        # Cross-TF CHoCH alignment (neutral TFs don't block)
        wd_aligned = w.choch != 0 and d.choch != 0 and w.choch == d.choch
        d4h_aligned = d.choch != 0 and h4.choch != 0 and d.choch == h4.choch
        h4h1_aligned = h4.choch != 0 and h1.choch != 0 and h4.choch == h1.choch

        # All 4 same direction bonus
        all_same = (
            w.choch != 0
            and d.choch != 0
            and h4.choch != 0
            and h1.choch != 0
            and w.choch == d.choch
            and d.choch == h4.choch
            and h4.choch == h1.choch
        )

        # Base score (max 4)
        base_score = int(wd_aligned) + int(d4h_aligned) + int(h4h1_aligned) + int(all_same)

        # Direction: Primary (W→D→4H) or Secondary (D→4H→1H unanimous)
        primary_bull = wd_aligned and d4h_aligned and w.choch == 1
        primary_bear = wd_aligned and d4h_aligned and w.choch == -1
        secondary_bull = (
            not primary_bull and d4h_aligned and h4h1_aligned and d.choch == 1 and h4.choch == 1 and h1.choch == 1
        )
        secondary_bear = (
            not primary_bear and d4h_aligned and h4h1_aligned and d.choch == -1 and h4.choch == -1 and h1.choch == -1
        )

        is_primary = primary_bull or primary_bear
        is_secondary = secondary_bull or secondary_bear

        if primary_bull or secondary_bull:
            scores.direction = 1
            scores.direction_text = "LONG"
        elif primary_bear or secondary_bear:
            scores.direction = -1
            scores.direction_text = "SHORT"
        else:
            scores.direction = 0
            scores.direction_text = "NEUTRAL"

        # EMA confirmation: 3+ EMAs confirm direction
        ema_confirm_count = 0
        if scores.direction != 0:
            d_val = scores.direction
            ema_confirm_count = (
                int(w.ema == d_val) + int(d.ema == d_val) + int(h4.ema == d_val) + int(h1.ema == d_val)
            )
        ema_confirmed = ema_confirm_count >= 3

        # Total score (max 5)
        scores.confluence_score = base_score + int(ema_confirmed)

        # Store details for tooltip
        scores.wd_aligned = wd_aligned
        scores.d4h_aligned = d4h_aligned
        scores.h4h1h_aligned = h4h1_aligned
        scores.all_same = all_same
        scores.ema_confirm_count = ema_confirm_count
        scores.ema_confirmed = ema_confirmed
        scores.is_primary = is_primary
        scores.is_secondary = is_secondary

        # === ENTRY (LTF) ===
        entry_bias = {}
        for tf in ENTRY_TFS:
            df = tf_data.get(tf, pd.DataFrame())
            choch, ema = _get_last_choch_ema(df)
            tf_label = tf.upper().replace("M", "m")
            entry_bias[tf] = TFBias(timeframe=tf_label, choch=choch, ema=ema)

        scores.entry_tfs = [entry_bias[tf] for tf in ENTRY_TFS]

        e15 = entry_bias["15m"]
        e5 = entry_bias["5m"]
        e1 = entry_bias["1m"]
        d_val = scores.direction

        # LTF CHoCH chain alignment with direction
        entry_15m5m = (
            e15.choch != 0
            and e5.choch != 0
            and e15.choch == e5.choch
            and ((d_val == 1 and e15.choch == 1) or (d_val == -1 and e15.choch == -1))
        )
        entry_5m1m = (
            e5.choch != 0
            and e1.choch != 0
            and e5.choch == e1.choch
            and ((d_val == 1 and e5.choch == 1) or (d_val == -1 and e5.choch == -1))
        )

        # All 3 LTF CHoCH confirm direction
        entry_all_ltf = (
            d_val != 0
            and e15.choch != 0
            and e5.choch != 0
            and e1.choch != 0
            and (
                (d_val == 1 and e15.choch == 1 and e5.choch == 1 and e1.choch == 1)
                or (d_val == -1 and e15.choch == -1 and e5.choch == -1 and e1.choch == -1)
            )
        )

        # 3/3 LTF EMAs confirm direction
        entry_ema_count = 0
        if d_val != 0:
            entry_ema_count = (
                int((d_val == 1 and e15.ema == 1) or (d_val == -1 and e15.ema == -1))
                + int((d_val == 1 and e5.ema == 1) or (d_val == -1 and e5.ema == -1))
                + int((d_val == 1 and e1.ema == 1) or (d_val == -1 and e1.ema == -1))
            )
        entry_ema_confirmed = entry_ema_count >= 3

        # === FVG ===
        for fvg_tf in FVG_TFS:
            df = tf_data.get(fvg_tf, pd.DataFrame())
            active, top, btm, is_bull = _detect_active_fvg(df, scores.price)
            if active:
                scores.fvg_active = True
                scores.fvg_tf = fvg_tf.upper().replace("M", "m")
                scores.fvg_dir = "bullish" if is_bull else "bearish"
                scores.fvg_top = top
                scores.fvg_bottom = btm
                break  # Highest TF wins (4H > 1H > 15m)

        # Entry score (max 5)
        scores.entry_score = (
            int(entry_15m5m) + int(entry_5m1m) + int(entry_all_ltf) + int(entry_ema_confirmed) + (1 if scores.fvg_active else 0)
        )

        # Store details
        scores.entry_15m5m_aligned = entry_15m5m
        scores.entry_5m1m_aligned = entry_5m1m
        scores.entry_all_ltf = entry_all_ltf
        scores.entry_ema_count = entry_ema_count
        scores.entry_ema_confirmed = entry_ema_confirmed

        # Session
        scores.session = _detect_session()

    except Exception as e:
        logger.error(f"Scoring failed: {e}")

    return scores
