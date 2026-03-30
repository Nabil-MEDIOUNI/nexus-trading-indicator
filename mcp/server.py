"""
Nexus Trading MCP Server

Exposes SMC trading analysis, trade setups, and backtesting to Claude and other LLM agents.

Usage:
  python mcp/server.py                    # Start server (stdio)
  fastmcp dev mcp/server.py               # Dev mode with inspector

Claude Code config (~/.claude/settings.json):
  "mcpServers": {
    "nexus": {
      "command": "python",
      "args": ["mcp/server.py"]
    }
  }
"""

from fastmcp import FastMCP

mcp = FastMCP(
    "nexus_mcp",
    description="SMC trading analysis, confluence scoring, and backtesting for the Nexus Trading Indicator",
)


def _setup_paths():
    """Add backtest engine to path (called lazily, not on import)."""
    import os
    import sys

    engine_path = os.path.join(os.path.dirname(__file__), "..", "backtest")
    if engine_path not in sys.path:
        sys.path.insert(0, engine_path)


# --- Resources ---


@mcp.resource("nexus://config/strategy")
def get_strategy_config() -> str:
    """Current default strategy configuration."""
    return (
        "Strategy defaults:\n"
        "  min_score: 4 (minimum confluence score to trade, range 1-6)\n"
        "  rr_ratio: 3.0 (risk:reward ratio for TP calculation)\n"
        "  max_daily_losses: 3\n"
        "  sweep_expiry: 20 bars\n"
        "  bos_expiry: 15 bars\n"
        "  sl_buffer: 0.5 ATR\n"
    )


@mcp.resource("nexus://supported/exchanges")
def get_supported_exchanges() -> str:
    """List of supported exchanges via CCXT."""
    return "kraken, binance, bybit, okx, coinbase, bitfinex, kucoin (any CCXT-supported exchange)"


@mcp.resource("nexus://supported/timeframes")
def get_supported_timeframes() -> str:
    """Supported timeframe strings."""
    return "1m, 5m, 15m, 1h, 4h, 1d, 1w"


# --- Tools ---

VALID_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1d", "1w"}


def _validate_params(symbol: str, timeframe: str):
    """Validate common parameters. Returns error string or None."""
    if "/" not in symbol:
        return f"Invalid symbol format '{symbol}'. Use CCXT format: BTC/USDT, ETH/USDT, SOL/USDT"
    if timeframe not in VALID_TIMEFRAMES:
        return f"Invalid timeframe '{timeframe}'. Use one of: {', '.join(sorted(VALID_TIMEFRAMES))}"
    return None


@mcp.tool(
    name="nexus_get_market_analysis",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def nexus_get_market_analysis(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    exchange: str = "kraken",
    bars: int = 500,
) -> dict:
    """
    Analyze current market state for a trading pair using Smart Money Concepts.
    Returns bias direction (bullish/bearish/neutral), premium/discount zone position,
    active Fair Value Gaps, nearest liquidity levels, and recent sweep status.
    Read-only - does not place any orders. Takes 2-10 seconds depending on exchange.

    Args:
        symbol: Trading pair in CCXT format (e.g. BTC/USDT, ETH/USDT, SOL/USDT)
        timeframe: Chart timeframe (1m, 5m, 15m, 1h, 4h, 1d, 1w)
        exchange: Any CCXT-supported exchange (kraken, binance, bybit, okx, etc.)
        bars: Number of bars to analyze (default 500, max 5000)
    """
    err = _validate_params(symbol, timeframe)
    if err:
        return {"error": err}

    bars = max(50, min(bars, 5000))

    _setup_paths()
    try:
        import numpy as np
        from engine.data import fetch_ohlcv, timeframe_to_minutes
        from engine.indicators import atr, choch_bos, detect_fvg, liquidity_swings, smc_swing_zones, swing_length_for_tf

        df = fetch_ohlcv(symbol, timeframe, exchange, limit=bars)
        if df.empty:
            return {"error": f"No data returned for {symbol} on {exchange}. Check the symbol and exchange."}

        tf_min = timeframe_to_minutes(timeframe)
        swing_len = swing_length_for_tf(tf_min)

        choch = choch_bos(df, pivot_length=1)
        fvg_up, fvg_dn = detect_fvg(df)
        liq_ph_top, liq_pl_btm, sweep_h, sweep_l = liquidity_swings(df, 14)
        trail_top, trail_btm = smc_swing_zones(df, swing_len)
        current_atr = atr(df, 20)

        last = len(df) - 1
        eq = (trail_top.iloc[last] + trail_btm.iloc[last]) / 2
        price = df["close"].iloc[last]

        active_bull_fvgs = [f for f in fvg_up if f["active"]][-3:]
        active_bear_fvgs = [f for f in fvg_dn if f["active"]][-3:]

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "price": round(float(price), 2),
            "atr": round(float(current_atr.iloc[last]), 2) if not np.isnan(current_atr.iloc[last]) else None,
            "bias": {
                "choch": int(choch.iloc[last]),
                "direction": "bullish" if choch.iloc[last] == 1 else "bearish" if choch.iloc[last] == -1 else "neutral",
            },
            "zone": {
                "swing_high": round(float(trail_top.iloc[last]), 2),
                "swing_low": round(float(trail_btm.iloc[last]), 2),
                "equilibrium": round(float(eq), 2),
                "position": "discount" if price < eq else "premium",
                "pct_from_eq": round(float((price - eq) / eq * 100), 2),
            },
            "liquidity": {
                "nearest_high": round(float(liq_ph_top.iloc[last]), 2) if not np.isnan(liq_ph_top.iloc[last]) else None,
                "nearest_low": round(float(liq_pl_btm.iloc[last]), 2) if not np.isnan(liq_pl_btm.iloc[last]) else None,
                "recent_sweep_high": bool(sweep_h.iloc[-20:].any()),
                "recent_sweep_low": bool(sweep_l.iloc[-20:].any()),
            },
            "fvg": {
                "active_bullish": len(active_bull_fvgs),
                "active_bearish": len(active_bear_fvgs),
                "nearest_bull": {
                    "top": round(active_bull_fvgs[-1]["top"], 2),
                    "bottom": round(active_bull_fvgs[-1]["bottom"], 2),
                }
                if active_bull_fvgs
                else None,
                "nearest_bear": {
                    "top": round(active_bear_fvgs[-1]["top"], 2),
                    "bottom": round(active_bear_fvgs[-1]["bottom"], 2),
                }
                if active_bear_fvgs
                else None,
            },
            "bars_analyzed": len(df),
        }

    except Exception as e:
        return {"error": f"Analysis failed: {str(e)}", "suggestion": "Check symbol format (BTC/USDT) and exchange name"}


@mcp.tool(
    name="nexus_get_trade_setup",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def nexus_get_trade_setup(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    exchange: str = "kraken",
    min_score: int = 4,
    rr_ratio: float = 3.0,
) -> dict:
    """
    Check if a qualified trade setup exists right now using the 5-step SMC execution model
    (Bias, Sweep, Confirm, Enter, Manage). Returns 'no setup' when confluence score is below
    threshold, or entry/SL/TP levels when a setup qualifies. Read-only - does not place orders.

    Args:
        symbol: Trading pair in CCXT format (e.g. BTC/USDT)
        timeframe: Chart timeframe (1m, 5m, 15m, 1h, 4h, 1d, 1w)
        exchange: Any CCXT-supported exchange
        min_score: Minimum confluence score to qualify a setup (1-6, default 4)
        rr_ratio: Risk:Reward ratio for take profit calculation (default 3.0)
    """
    err = _validate_params(symbol, timeframe)
    if err:
        return {"error": err}

    min_score = max(1, min(min_score, 6))
    rr_ratio = max(0.5, min(rr_ratio, 10.0))

    _setup_paths()
    try:
        import numpy as np
        from engine.data import fetch_ohlcv, timeframe_to_minutes
        from engine.indicators import atr, choch_bos, detect_fvg, liquidity_swings, smc_swing_zones, swing_length_for_tf
        from engine.strategy import StrategyConfig, compute_confluence

        df = fetch_ohlcv(symbol, timeframe, exchange, limit=500)
        if df.empty:
            return {"error": f"No data returned for {symbol} on {exchange}."}

        tf_min = timeframe_to_minutes(timeframe)
        swing_len = swing_length_for_tf(tf_min)
        config = StrategyConfig(min_score=min_score, rr_ratio=rr_ratio, tf_minutes=tf_min)

        choch = choch_bos(df, pivot_length=1)
        fvg_up, fvg_dn = detect_fvg(df)
        liq_ph_top, liq_pl_btm, sweep_h, sweep_l = liquidity_swings(df, 14)
        trail_top, trail_btm = smc_swing_zones(df, swing_len)
        entry_atr = atr(df, config.atr_period)

        score_long, score_short = compute_confluence(
            df,
            config,
            choch,
            sweep_h,
            sweep_l,
            choch,
            fvg_up,
            fvg_dn,
            trail_top,
            trail_btm,
        )

        last = len(df) - 1
        price = df["close"].iloc[last]
        atr_val = entry_atr.iloc[last] if not np.isnan(entry_atr.iloc[last]) else 0

        long_score = int(score_long.iloc[last])
        short_score = int(score_short.iloc[last])

        setup = {
            "symbol": symbol,
            "timeframe": timeframe,
            "price": round(float(price), 2),
            "long": {"score": long_score, "qualified": long_score >= min_score},
            "short": {"score": short_score, "qualified": short_score >= min_score},
            "recommendation": "no setup",
        }

        if long_score >= min_score and (short_score < min_score or long_score > short_score):
            sl_level = (
                float(liq_pl_btm.iloc[last]) if not np.isnan(liq_pl_btm.iloc[last]) else float(trail_btm.iloc[last])
            )
            sl = sl_level - atr_val * config.sl_buffer_atr
            sl_dist = price - sl
            if sl_dist > 0:
                tp = price + sl_dist * rr_ratio
                setup.update(
                    {
                        "recommendation": "LONG",
                        "entry": round(float(price), 2),
                        "sl": round(float(sl), 2),
                        "tp": round(float(tp), 2),
                        "rr": rr_ratio,
                        "risk_pct": round(float(sl_dist / price * 100), 2),
                    }
                )

        elif short_score >= min_score:
            sl_level = (
                float(liq_ph_top.iloc[last]) if not np.isnan(liq_ph_top.iloc[last]) else float(trail_top.iloc[last])
            )
            sl = sl_level + atr_val * config.sl_buffer_atr
            sl_dist = sl - price
            if sl_dist > 0:
                tp = price - sl_dist * rr_ratio
                setup.update(
                    {
                        "recommendation": "SHORT",
                        "entry": round(float(price), 2),
                        "sl": round(float(sl), 2),
                        "tp": round(float(tp), 2),
                        "rr": rr_ratio,
                        "risk_pct": round(float(sl_dist / price * 100), 2),
                    }
                )

        return setup

    except Exception as e:
        return {"error": f"Setup check failed: {str(e)}"}


@mcp.tool(
    name="nexus_run_backtest",
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
def nexus_run_backtest(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    exchange: str = "kraken",
    bars: int = 2000,
    min_score: int = 4,
    rr_ratio: float = 3.0,
    max_daily_losses: int = 3,
) -> dict:
    """
    Run the Nexus 5-step SMC strategy backtest on historical data. Returns performance
    metrics (win rate, Sharpe ratio, max drawdown, profit factor), the last 20 trades,
    and an assessment. May take 5-30 seconds for 2000+ bars. Read-only - no orders placed.

    Args:
        symbol: Trading pair in CCXT format (e.g. BTC/USDT, ETH/USDT)
        timeframe: Chart timeframe (1m, 5m, 15m, 1h, 4h, 1d, 1w)
        exchange: Any CCXT-supported exchange
        bars: Number of historical bars to test (50-5000, more = slower but more reliable)
        min_score: Minimum confluence score to enter trades (1-6, default 4)
        rr_ratio: Risk:Reward ratio (default 3.0 = 3R take profit)
        max_daily_losses: Stop trading after N losses per day (1-10, default 3)
    """
    err = _validate_params(symbol, timeframe)
    if err:
        return {"error": err}

    bars = max(50, min(bars, 5000))
    min_score = max(1, min(min_score, 6))
    rr_ratio = max(0.5, min(rr_ratio, 10.0))
    max_daily_losses = max(1, min(max_daily_losses, 10))

    _setup_paths()
    try:
        from engine.data import fetch_ohlcv, timeframe_to_minutes
        from engine.metrics import calculate_metrics
        from engine.strategy import StrategyConfig, run_backtest

        df = fetch_ohlcv(symbol, timeframe, exchange, limit=bars)
        if df.empty:
            return {"error": f"No data returned for {symbol} on {exchange}."}

        tf_min = timeframe_to_minutes(timeframe)
        config = StrategyConfig(
            rr_ratio=rr_ratio, min_score=min_score, max_daily_losses=max_daily_losses, tf_minutes=tf_min
        )

        trades = run_backtest(df, config)
        metrics = calculate_metrics(trades)

        trade_list = [
            {
                "direction": "long" if t.direction == 1 else "short",
                "entry": round(t.entry_price, 2),
                "sl": round(t.sl, 2),
                "tp": round(t.tp, 2),
                "pnl_pct": round(t.pnl, 2),
                "exit": t.exit_reason,
                "score": t.score,
            }
            for t in trades[-20:]
        ]

        assessment = "INSUFFICIENT DATA - need 30+ trades for statistical confidence"
        if metrics.total_trades >= 30:
            if metrics.profit_factor < 1.0:
                assessment = "UNPROFITABLE - strategy loses money after costs"
            elif metrics.max_consecutive_losses >= 6:
                assessment = "HIGH RISK - long losing streaks suggest fragility"
            elif metrics.win_rate < 30:
                assessment = "LOW WIN RATE - even with good R:R, psychologically difficult"
            elif metrics.profit_factor >= 1.5 and metrics.sharpe_ratio >= 1.0:
                assessment = "PROMISING - positive expectancy with acceptable risk metrics"
            elif metrics.profit_factor >= 1.2:
                assessment = "MARGINAL - small edge, sensitive to execution quality"
            else:
                assessment = "NEEDS REVIEW - check parameter sensitivity before trading"

        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "bars": len(df),
            "config": {"min_score": min_score, "rr_ratio": rr_ratio, "max_daily_losses": max_daily_losses},
            "metrics": {
                "total_trades": metrics.total_trades,
                "win_rate": round(metrics.win_rate, 1),
                "profit_factor": round(metrics.profit_factor, 2),
                "total_pnl_pct": round(metrics.total_pnl, 2),
                "max_drawdown_pct": round(metrics.max_drawdown, 2),
                "sharpe_ratio": round(metrics.sharpe_ratio, 2),
                "avg_win_pct": round(metrics.avg_win, 2),
                "avg_loss_pct": round(metrics.avg_loss, 2),
                "max_consecutive_losses": metrics.max_consecutive_losses,
            },
            "recent_trades": trade_list,
            "assessment": assessment,
        }

    except Exception as e:
        return {"error": f"Backtest failed: {str(e)}", "suggestion": "Try fewer bars or check exchange connectivity"}


if __name__ == "__main__":
    mcp.run()
