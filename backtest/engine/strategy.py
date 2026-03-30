"""
Nexus 5-Step Strategy - Python implementation for backtesting.
Mirrors the confluence scorer + entry/exit logic from nexus-strategy.pine.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import atr, choch_bos, compute_ema_alignment, liquidity_swings, smc_swing_zones, swing_length_for_tf


@dataclass
class Trade:
    bar: int
    direction: int  # 1=long, -1=short
    entry_price: float
    sl: float
    tp: float
    score: int
    exit_bar: int = 0
    exit_price: float = 0.0
    pnl: float = 0.0
    exit_reason: str = ""


@dataclass
class StrategyConfig:
    rr_ratio: float = 3.0
    sl_buffer_atr: float = 0.5
    atr_period: int = 20
    min_score: int = 6
    max_daily_losses: int = 3
    commission_pct: float = 0.1
    slippage_pct: float = 0.05
    liq_swing_length: int = 14
    tf_minutes: int = 60


def compute_confluence(
    df: pd.DataFrame,
    config: StrategyConfig,
    choch_w: pd.Series,
    choch_d: pd.Series,
    choch_4h: pd.Series,
    choch_1h: pd.Series,
    ema_w: pd.Series,
    ema_d: pd.Series,
    ema_4h: pd.Series,
    ema_1h: pd.Series,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Compute 9-factor confluence: CHoCH + EMA on W/D/4H/1H + session.
    Returns (score, direction, session_score) series.
    """
    bull_count = (
        (choch_w == 1).astype(int)
        + (choch_d == 1).astype(int)
        + (choch_4h == 1).astype(int)
        + (choch_1h == 1).astype(int)
        + (ema_w == 1).astype(int)
        + (ema_d == 1).astype(int)
        + (ema_4h == 1).astype(int)
        + (ema_1h == 1).astype(int)
    )
    bear_count = (
        (choch_w == -1).astype(int)
        + (choch_d == -1).astype(int)
        + (choch_4h == -1).astype(int)
        + (choch_1h == -1).astype(int)
        + (ema_w == -1).astype(int)
        + (ema_d == -1).astype(int)
        + (ema_4h == -1).astype(int)
        + (ema_1h == -1).astype(int)
    )

    session = pd.Series(1, index=df.index, dtype=int)

    direction = pd.Series(0, index=df.index, dtype=int)
    direction[bull_count > bear_count] = 1
    direction[bear_count > bull_count] = -1

    score = pd.Series(0, index=df.index, dtype=int)
    score[direction == 1] = bull_count[direction == 1] + session[direction == 1]
    score[direction == -1] = bear_count[direction == -1] + session[direction == -1]

    return score, direction, session


def run_backtest(df: pd.DataFrame, config: StrategyConfig = StrategyConfig()) -> list[Trade]:
    """
    Run the Nexus 5-step strategy backtest on OHLCV data.
    Returns list of Trade objects with entry/exit details.
    """
    swing_len = swing_length_for_tf(config.tf_minutes)
    entry_atr = atr(df, config.atr_period)

    # Compute all indicators
    choch = choch_bos(df, pivot_length=1)
    liq_ph_top, liq_pl_btm, _, _ = liquidity_swings(df, config.liq_swing_length)
    trail_top, trail_btm = smc_swing_zones(df, swing_len)

    # EMA alignment
    ema_align = compute_ema_alignment(df)

    # Confluence (single TF proxy — in production, pass actual HTF series)
    choch_1h = choch
    score, direction, _ = compute_confluence(
        df,
        config,
        choch_w=choch_1h,
        choch_d=choch_1h,
        choch_4h=choch_1h,
        choch_1h=choch_1h,
        ema_w=ema_align,
        ema_d=ema_align,
        ema_4h=ema_align,
        ema_1h=ema_align,
    )

    n = len(df)
    trades: list[Trade] = []
    in_trade = False
    current_trade = None
    daily_losses = 0
    current_day = -1

    for i in range(1, n):
        # Daily loss reset
        day = df.index[i].day if hasattr(df.index[i], "day") else i // 1440
        if day != current_day:
            daily_losses = 0
            current_day = day

        # Check if current trade hit SL or TP
        if in_trade and current_trade is not None:
            t = current_trade
            if t.direction == 1:  # long
                if df["low"].iloc[i] <= t.sl:
                    t.exit_bar = i
                    t.exit_price = t.sl
                    t.exit_reason = "SL"
                    t.pnl = (t.exit_price - t.entry_price) / t.entry_price * 100 - config.commission_pct * 2
                    trades.append(t)
                    in_trade = False
                    daily_losses += 1
                elif df["high"].iloc[i] >= t.tp:
                    t.exit_bar = i
                    t.exit_price = t.tp
                    t.exit_reason = "TP"
                    t.pnl = (t.exit_price - t.entry_price) / t.entry_price * 100 - config.commission_pct * 2
                    trades.append(t)
                    in_trade = False
            else:  # short
                if df["high"].iloc[i] >= t.sl:
                    t.exit_bar = i
                    t.exit_price = t.sl
                    t.exit_reason = "SL"
                    t.pnl = (t.entry_price - t.exit_price) / t.entry_price * 100 - config.commission_pct * 2
                    trades.append(t)
                    in_trade = False
                    daily_losses += 1
                elif df["low"].iloc[i] <= t.tp:
                    t.exit_bar = i
                    t.exit_price = t.tp
                    t.exit_reason = "TP"
                    t.pnl = (t.entry_price - t.exit_price) / t.entry_price * 100 - config.commission_pct * 2
                    trades.append(t)
                    in_trade = False
            continue

        # Skip if in trade or daily limit hit
        if in_trade or daily_losses >= config.max_daily_losses:
            continue

        # Check entry conditions
        atr_val = entry_atr.iloc[i]
        if np.isnan(atr_val):
            continue

        # Long entry
        if score.iloc[i] >= config.min_score and score.iloc[i - 1] < config.min_score and direction.iloc[i] == 1:
            sl = (
                liq_pl_btm.iloc[i] - atr_val * config.sl_buffer_atr
                if not np.isnan(liq_pl_btm.iloc[i])
                else trail_btm.iloc[i] - atr_val * config.sl_buffer_atr
            )
            if np.isnan(sl):
                continue
            entry = df["close"].iloc[i] * (1 + config.slippage_pct / 100)
            sl_dist = entry - sl
            if sl_dist <= 0:
                continue
            tp = entry + sl_dist * config.rr_ratio
            current_trade = Trade(bar=i, direction=1, entry_price=entry, sl=sl, tp=tp, score=int(score.iloc[i]))
            in_trade = True

        # Short entry
        if score.iloc[i] >= config.min_score and score.iloc[i - 1] < config.min_score and direction.iloc[i] == -1:
            sl = (
                liq_ph_top.iloc[i] + atr_val * config.sl_buffer_atr
                if not np.isnan(liq_ph_top.iloc[i])
                else trail_top.iloc[i] + atr_val * config.sl_buffer_atr
            )
            if np.isnan(sl):
                continue
            entry = df["close"].iloc[i] * (1 - config.slippage_pct / 100)
            sl_dist = sl - entry
            if sl_dist <= 0:
                continue
            tp = entry - sl_dist * config.rr_ratio
            current_trade = Trade(bar=i, direction=-1, entry_price=entry, sl=sl, tp=tp, score=int(score.iloc[i]))
            in_trade = True

    return trades
