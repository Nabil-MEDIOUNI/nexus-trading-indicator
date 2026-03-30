"""
Nexus 5-Step Strategy - Python implementation for backtesting.
Mirrors the confluence scorer + entry/exit logic from nexus-strategy.pine.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .indicators import atr, choch_bos, detect_fvg, liquidity_swings, smc_swing_zones, swing_length_for_tf


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
    min_score: int = 4
    sweep_expiry: int = 20
    bos_expiry: int = 15
    max_daily_losses: int = 3
    commission_pct: float = 0.1
    slippage_pct: float = 0.05
    liq_swing_length: int = 14
    tf_minutes: int = 60


def compute_confluence(
    df: pd.DataFrame,
    config: StrategyConfig,
    htf_bias: pd.Series,
    sweep_high: pd.Series,
    sweep_low: pd.Series,
    choch: pd.Series,
    fvg_up: list,
    fvg_dn: list,
    trail_top: pd.Series,
    trail_btm: pd.Series,
) -> tuple[pd.Series, pd.Series]:
    """Compute confluence scores for long and short on every bar."""
    n = len(df)
    score_long = pd.Series(0, index=df.index, dtype=int)
    score_short = pd.Series(0, index=df.index, dtype=int)

    last_sweep_high_bar = -999
    last_sweep_low_bar = -999
    last_bos_bull_bar = -999
    last_bos_bear_bar = -999

    # Precompute active FVG state per bar
    fvg_bull_active = pd.Series(False, index=df.index)
    fvg_bear_active = pd.Series(False, index=df.index)

    # Track FVG lifecycle
    active_up = []
    active_dn = []
    fvg_up_idx = 0
    fvg_dn_idx = 0

    for i in range(n):
        # Add new FVGs that appeared at this bar
        while fvg_up_idx < len(fvg_up) and fvg_up[fvg_up_idx]["bar"] <= i:
            active_up.append(fvg_up[fvg_up_idx])
            fvg_up_idx += 1
        while fvg_dn_idx < len(fvg_dn) and fvg_dn[fvg_dn_idx]["bar"] <= i:
            active_dn.append(fvg_dn[fvg_dn_idx])
            fvg_dn_idx += 1

        # Break FVGs
        for f in active_up:
            if f["active"] and df["low"].iloc[i] < f["bottom"]:
                f["active"] = False
        for f in active_dn:
            if f["active"] and df["high"].iloc[i] > f["top"]:
                f["active"] = False

        fvg_bull_active.iloc[i] = any(f["active"] for f in active_up[-10:]) if active_up else False
        fvg_bear_active.iloc[i] = any(f["active"] for f in active_dn[-10:]) if active_dn else False

        # Track event bars
        if sweep_high.iloc[i]:
            last_sweep_high_bar = i
        if sweep_low.iloc[i]:
            last_sweep_low_bar = i
        if i > 0 and choch.iloc[i] == 1 and choch.iloc[i - 1] != 1:
            last_bos_bull_bar = i
        if i > 0 and choch.iloc[i] == -1 and choch.iloc[i - 1] != -1:
            last_bos_bear_bar = i

        # Factor 1: Bias (simplified - use HTF choch)
        f1_bull = int(htf_bias.iloc[i] == 1) if not np.isnan(htf_bias.iloc[i]) else 0
        f1_bear = int(htf_bias.iloc[i] == -1) if not np.isnan(htf_bias.iloc[i]) else 0

        # Factor 2: Zone
        eq = (trail_top.iloc[i] + trail_btm.iloc[i]) / 2 if not np.isnan(trail_top.iloc[i]) else np.nan
        f2_bull = int(not np.isnan(eq) and df["close"].iloc[i] < eq)
        f2_bear = int(not np.isnan(eq) and df["close"].iloc[i] > eq)

        # Factor 3: Sweep (with expiry)
        f3_bull = int((i - last_sweep_low_bar) <= config.sweep_expiry)
        f3_bear = int((i - last_sweep_high_bar) <= config.sweep_expiry)

        # Factor 4: FVG
        f4_bull = int(fvg_bull_active.iloc[i])
        f4_bear = int(fvg_bear_active.iloc[i])

        # Factor 5: BOS (with expiry)
        f5_bull = int((i - last_bos_bull_bar) <= config.bos_expiry)
        f5_bear = int((i - last_bos_bear_bar) <= config.bos_expiry)

        # Factor 6: Session (always 1 for backtesting simplicity)
        f6 = 1

        score_long.iloc[i] = f1_bull + f2_bull + f3_bull + f4_bull + f5_bull + f6
        score_short.iloc[i] = f1_bear + f2_bear + f3_bear + f4_bear + f5_bear + f6

    return score_long, score_short


def run_backtest(df: pd.DataFrame, config: StrategyConfig = StrategyConfig()) -> list[Trade]:
    """
    Run the Nexus 5-step strategy backtest on OHLCV data.
    Returns list of Trade objects with entry/exit details.
    """
    swing_len = swing_length_for_tf(config.tf_minutes)
    entry_atr = atr(df, config.atr_period)

    # Compute all indicators
    choch = choch_bos(df, pivot_length=1)
    fvg_up, fvg_dn = detect_fvg(df)
    liq_ph_top, liq_pl_btm, sweep_high, sweep_low = liquidity_swings(df, config.liq_swing_length)
    trail_top, trail_btm = smc_swing_zones(df, swing_len)

    # HTF bias (use choch from same TF as proxy - in production, use actual HTF data)
    htf_bias = choch

    # Confluence
    score_long, score_short = compute_confluence(
        df, config, htf_bias, sweep_high, sweep_low, choch, fvg_up, fvg_dn, trail_top, trail_btm
    )

    # Equilibrium
    equilibrium = (trail_top + trail_btm) / 2

    # Pullback detection
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
        eq = equilibrium.iloc[i]
        atr_val = entry_atr.iloc[i]
        if np.isnan(atr_val) or np.isnan(eq):
            continue

        # Long entry
        if score_long.iloc[i] >= config.min_score and score_long.iloc[i - 1] < config.min_score:
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
            current_trade = Trade(bar=i, direction=1, entry_price=entry, sl=sl, tp=tp, score=score_long.iloc[i])
            in_trade = True

        # Short entry
        elif score_short.iloc[i] >= config.min_score and score_short.iloc[i - 1] < config.min_score:
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
            current_trade = Trade(bar=i, direction=-1, entry_price=entry, sl=sl, tp=tp, score=score_short.iloc[i])
            in_trade = True

    return trades
