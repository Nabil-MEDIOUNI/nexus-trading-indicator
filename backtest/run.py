#!/usr/bin/env python3
"""
Nexus Strategy Backtester - Main Runner
Usage: python backtest/run.py [--symbol BTC/USDT] [--tf 1h] [--exchange kraken]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from engine import StrategyConfig, calculate_metrics, run_backtest
from engine.data import fetch_ohlcv, timeframe_to_minutes


def main():
    parser = argparse.ArgumentParser(description="Nexus Strategy Backtester")
    parser.add_argument("--symbol", default="BTC/USDT", help="Trading pair")
    parser.add_argument("--tf", default="1h", help="Timeframe (1m, 5m, 15m, 1h, 4h, 1d)")
    parser.add_argument("--exchange", default="kraken", help="Exchange (kraken, binance, etc.)")
    parser.add_argument("--limit", type=int, default=5000, help="Number of bars to fetch")
    parser.add_argument("--min-score", type=int, default=4, help="Min confluence score (1-6)")
    parser.add_argument("--rr", type=float, default=3.0, help="Risk:Reward ratio")
    parser.add_argument("--no-cache", action="store_true", help="Bypass data cache")
    args = parser.parse_args()

    print(f"Nexus Backtester - {args.symbol} {args.tf} on {args.exchange}")
    print("-" * 50)

    # Fetch data
    df = fetch_ohlcv(args.symbol, args.tf, args.exchange, args.limit, not args.no_cache)

    # Configure strategy
    config = StrategyConfig(
        rr_ratio=args.rr,
        min_score=args.min_score,
        tf_minutes=timeframe_to_minutes(args.tf),
    )

    # Run backtest
    print(f"Running backtest on {len(df)} bars...")
    trades = run_backtest(df, config)

    # Calculate and display metrics
    metrics = calculate_metrics(trades)
    print(metrics)

    # Trade list
    if trades:
        print("\nLast 10 trades:")
        print(f"{'#':>4} {'Dir':>5} {'Entry':>10} {'SL':>10} {'TP':>10} {'PnL%':>8} {'Exit':>5} {'Score':>5}")
        for i, t in enumerate(trades[-10:]):
            d = "LONG" if t.direction == 1 else "SHORT"
            print(
                f"{len(trades) - 9 + i:4d} {d:>5} {t.entry_price:10.2f} {t.sl:10.2f} {t.tp:10.2f} {t.pnl:8.2f} {t.exit_reason:>5} {t.score:5d}"
            )

    return 0 if trades else 1


if __name__ == "__main__":
    sys.exit(main())
