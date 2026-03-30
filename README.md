# Nexus Trading Indicator

**Stop guessing entries. Start trading with confluence.**

Nexus is an open-source Smart Money Concepts (SMC) trading system that scores every setup across 6 factors before you risk a dollar. From chart analysis to automated execution - every step of the 5-gate process is codified, tested, and ready to extend.

One indicator. One strategy. One score. No second-guessing.

## Why Nexus Exists

Nexus removes the guesswork. Every bar, across every timeframe, it checks 6 conditions and gives you a score. If the score hits your threshold, you trade. If it doesn't, you wait. No emotions. No FOMO.

And because it's open source, every rule is transparent, every decision is auditable, and anyone can improve it.

## The 5-Gate Execution Model

Every trade must pass through all 5 gates:

```
1. BIAS    ->  Is the higher timeframe structure aligned?
2. SWEEP   ->  Was liquidity taken recently?
3. CONFIRM ->  Did structure break? Is there an FVG?
4. ENTER   ->  Has price pulled back to a key level?
5. MANAGE  ->  SL at the swept level. TP at 3R.
```

### Confluence Scoring

The scorer checks 6 factors with **bar-based expiry** - a sweep from 50 bars ago doesn't inflate your score. Only fresh conditions count.

| Factor | What it checks | Adapts to TF? |
|--------|---------------|---------------|
| **Bias** | 3+ higher timeframes agree on direction | Yes - scalp checks 1H/4H/D, swing checks D/W |
| **Zone** | Price in discount (longs) or premium (shorts) | Yes |
| **Sweep** | Liquidity taken within N bars | Yes - configurable expiry |
| **FVG** | Active unbroken Fair Value Gap exists | Yes |
| **BOS** | Structure break (ChoCH/BOS) within N bars | Yes - configurable expiry |
| **Session** | NY or London session open | Yes - always +1 on daily+ |

**Minimum score to trade: 4/6** (configurable)

---

## Key Features

### TradingView Indicator
13 toggleable modules in one overlay:

- **Market Structure** - HH/HL/LH/LL with live zigzag tracking
- **Sessions** - NY, London, Asia with high/low levels
- **SMC** - Strong/Weak levels, EQH/EQL, MTF levels, Premium/Discount zones
- **ChoCH/BOS** - Structure break detection with configurable pivot length
- **Fair Value Gaps** - FVG/IFVG detection with break tracking
- **Liquidity Swings** - Pivot highs/lows with volume tracking
- **Candlestick Patterns** - 8 reversal patterns (hammer, engulfing, marubozu, etc.)
- **MTF Bias Table** - 7-timeframe CHoCH + EMA alignment at a glance
- **Confluence Scorer** - 6-factor table with live long/short scores
- **Entry/Exit Detection** - Pullback to FVG/equilibrium with SL/TP calculation
- **10 Alerts** - 8 alertconditions + 2 JSON webhooks with full trade data

### Python Backtesting
The entire indicator logic is ported to Python:

```bash
python backtest/run.py --symbol BTC/USDT --tf 1h --exchange kraken
```

Returns win rate, Sharpe ratio, max drawdown, profit factor, and a full trade list. Tweak parameters. Break the strategy. See what survives.

### AI Integration (MCP)
Three tools connect Nexus directly to your AI agent:

| Tool | What it does |
|------|-------------|
| `get-market-analysis` | Current bias, zones, FVGs, liquidity levels for any pair/TF |
| `get-trade-setup` | Entry/SL/TP when confluence meets your threshold |
| `run-strategy-backtest` | Full backtest with metrics and assessment |

### Automated Execution
TradingView fires the alert. The bot catches the webhook. Risk engine checks the rules. Kraken gets the order. Everything is logged.

## Quick Start

### 1. Try the indicator
Copy `src/nexus-indicator.pine` into TradingView Pine Editor. Click "Add to chart". Switch between 5m, 1H, and Daily to see the confluence table update.

### 2. Backtest the strategy
Copy `src/nexus-strategy.pine` into Pine Editor and open the Strategy Tester tab. Or run the Python backtester:

```bash
cd backtest && pip install -r requirements.txt
python run.py --symbol BTC/USDT --tf 1h
```

### 3. Connect Claude
```bash
pip install -r mcp/requirements.txt
```

Add to `~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "nexus": { "command": "python", "args": ["mcp/server.py"] }
  }
}
```

### 4. Paper trade
```bash
cd bot && pip install -r requirements.txt
PAPER_TRADING=true python consumer.py
```

Set `http://127.0.0.1:5000/webhook` as your TradingView alert webhook URL.

## Testing

```bash
# Validate Pine Script before pasting to TradingView
bash scripts/validate-pine.sh

# Run all Python tests (56 total)
cd backtest && python -m pytest tests/ -v
cd ../mcp && python -m pytest tests/ -v
cd ../bot && python -m pytest tests/ -v
```

## Open Source & Community

Nexus is released under the [MIT License](LICENSE) - use it, modify it, build on it.

### What you can build on this

Nexus is designed as a platform, not just an indicator:

- **Add new confluence factors** - Volume profile, order flow, funding rates, on-chain metrics
- **Add new exchanges** - Binance, Bybit, OKX (CCXT supports 100+ exchanges)
- **Build a dashboard** - Connect the MCP server to a web UI for real-time monitoring
- **Train ML models** - The Python backtest engine outputs structured trade data perfect for feature engineering
- **Add new strategies** - The 5-gate framework works for any SMC approach, not just this one
- **Multi-asset scanning** - Run confluence scoring across 50 pairs simultaneously
- **Telegram/Discord alerts** - Route the JSON webhook alerts to chat platforms
- **Portfolio management** - Track multiple positions across exchanges with the risk engine

### Contributing

Contributions are welcome. The best way to start:

1. **Report bugs** - Found a confluence score that doesn't make sense? Open an issue.
2. **Improve indicators** - The Python ports in `backtest/engine/indicators.py` can always be more accurate or faster.
3. **Add tests** - We have 56, but edge cases (empty data, NaN values, extreme prices) need coverage.
4. **Add exchange support** - The bot currently targets Kraken. Adding Binance or Bybit is straightforward via CCXT.
5. **Improve docs** - Explain a concept better, add examples, translate to other languages.

Open an issue first to discuss what you'd like to change, then submit a PR.

## Disclaimer

This software is for educational and research purposes. Trading cryptocurrency involves substantial risk of loss. Past performance from backtests does not guarantee future results. Always paper trade before risking real capital. The authors are not responsible for any financial losses incurred using this software.

## License

[MIT](LICENSE) - Copyright (c) 2026 Nabil Mediouni
