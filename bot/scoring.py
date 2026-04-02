"""
Nexus Dashboard Scoring Engine.
Fetches multi-TF data via CCXT and computes confluence + entry scores.
Uses the same indicator logic as the backtest engine for consistency.
"""

import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

# Add backtest engine to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backtest"))

from engine.data import fetch_ohlcv
from engine.indicators import choch_bos, compute_ema_alignment, detect_fvg

logger = logging.getLogger("nexus.scoring")

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
    conf_w_score: int = 0
    conf_d_score: int = 0
    conf_4h_score: int = 0
    conf_1h_score: int = 0
    confluence_score: int = 0  # max 7

    # Direction
    bull_align: int = 0
    bear_align: int = 0
    direction: int = 0  # 1=long, -1=short, 0=neutral
    direction_text: str = "NEUTRAL"

    # Entry (LTF)
    entry_tfs: list = field(default_factory=list)  # list of TFBias
    entry_15m_score: int = 0
    entry_5m_score: int = 0
    entry_1m_score: int = 0

    # FVG
    fvg_active: bool = False
    fvg_tf: str = ""
    fvg_dir: str = ""
    fvg_top: float = 0.0
    fvg_bottom: float = 0.0

    entry_score: int = 0  # max 7

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
        # Fetch data for all timeframes
        tf_data = {}
        for tf in CONFLUENCE_TFS + ENTRY_TFS + FVG_TFS:
            if tf not in tf_data:
                tf_data[tf] = fetch_ohlcv(symbol, tf, exchange, limit=500, use_cache=False)

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

        # Essential: cross-TF alignment
        wd_aligned = w.choch != 0 and d.choch != 0 and w.choch == d.choch
        d4h_aligned = d.choch != 0 and h4.choch != 0 and d.choch == h4.choch
        h4h1_aligned = h4.choch != 0 and h1.choch != 0 and h4.choch == h1.choch

        # Nice-to-have: same-TF match
        w_match = w.choch != 0 and w.ema != 0 and w.choch == w.ema
        d_match = d.choch != 0 and d.ema != 0 and d.choch == d.ema
        h4_match = h4.choch != 0 and h4.ema != 0 and h4.choch == h4.ema
        h1_match = h1.choch != 0 and h1.ema != 0 and h1.choch == h1.ema

        # Per-row scores
        scores.conf_w_score = int(w_match)
        scores.conf_d_score = int(d_match) + int(wd_aligned)
        scores.conf_4h_score = int(h4_match) + int(d4h_aligned)
        scores.conf_1h_score = int(h1_match) + int(h4h1_aligned)
        scores.confluence_score = (
            scores.conf_w_score + scores.conf_d_score + scores.conf_4h_score + scores.conf_1h_score
        )

        # Direction: requires 2+ alignments
        scores.bull_align = (
            int(wd_aligned and w.choch == 1) + int(d4h_aligned and d.choch == 1) + int(h4h1_aligned and h4.choch == 1)
        )
        scores.bear_align = (
            int(wd_aligned and w.choch == -1)
            + int(d4h_aligned and d.choch == -1)
            + int(h4h1_aligned and h4.choch == -1)
        )

        if scores.bull_align >= 2:
            scores.direction = 1
            scores.direction_text = "LONG"
        elif scores.bear_align >= 2:
            scores.direction = -1
            scores.direction_text = "SHORT"
        else:
            scores.direction = 0
            scores.direction_text = "NEUTRAL"

        # === ENTRY (LTF) ===
        entry_bias = {}
        for tf in ENTRY_TFS:
            df = tf_data.get(tf, pd.DataFrame())
            choch, ema = _get_last_choch_ema(df)
            tf_label = tf.upper().replace("M", "m")
            entry_bias[tf] = TFBias(timeframe=tf_label, choch=choch, ema=ema)

        scores.entry_tfs = [entry_bias[tf] for tf in ENTRY_TFS]

        # LTF scoring: CHoCH + EMA match with direction
        for tf, attr in [("15m", "entry_15m_score"), ("5m", "entry_5m_score"), ("1m", "entry_1m_score")]:
            b = entry_bias[tf]
            choch_ok = (scores.direction == 1 and b.choch == 1) or (scores.direction == -1 and b.choch == -1)
            ema_ok = (scores.direction == 1 and b.ema == 1) or (scores.direction == -1 and b.ema == -1)
            setattr(scores, attr, int(choch_ok) + int(ema_ok))

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

        # Entry total
        scores.entry_score = (
            (1 if scores.fvg_active else 0) + scores.entry_15m_score + scores.entry_5m_score + scores.entry_1m_score
        )

        # Session
        scores.session = _detect_session()

    except Exception as e:
        logger.error(f"Scoring failed: {e}")

    return scores
