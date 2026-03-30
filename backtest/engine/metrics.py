"""
Performance metrics for backtest results.
"""

from dataclasses import dataclass

import numpy as np


@dataclass
class BacktestMetrics:
    total_trades: int = 0
    winners: int = 0
    losers: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    avg_rr: float = 0.0
    max_consecutive_losses: int = 0

    def __str__(self) -> str:
        return (
            f"{'=' * 50}\n"
            f"  NEXUS BACKTEST RESULTS\n"
            f"{'=' * 50}\n"
            f"  Total trades:      {self.total_trades}\n"
            f"  Winners:           {self.winners} ({self.win_rate:.1f}%)\n"
            f"  Losers:            {self.losers}\n"
            f"  Avg win:           {self.avg_win:.2f}%\n"
            f"  Avg loss:          {self.avg_loss:.2f}%\n"
            f"  Profit factor:     {self.profit_factor:.2f}\n"
            f"  Total PnL:         {self.total_pnl:.2f}%\n"
            f"  Max drawdown:      {self.max_drawdown:.2f}%\n"
            f"  Sharpe ratio:      {self.sharpe_ratio:.2f}\n"
            f"  Avg R:R achieved:  {self.avg_rr:.2f}\n"
            f"  Max consec losses: {self.max_consecutive_losses}\n"
            f"{'=' * 50}"
        )


def calculate_metrics(trades: list) -> BacktestMetrics:
    """Calculate performance metrics from a list of Trade objects."""
    if not trades:
        return BacktestMetrics()

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total = len(pnls)
    n_wins = len(wins)
    n_losses = len(losses)

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0

    # Max drawdown
    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(equity)
    drawdown = peak - equity
    max_dd = float(np.max(drawdown)) if len(drawdown) > 0 else 0

    # Sharpe (annualized, assuming ~252 trading days)
    pnl_arr = np.array(pnls)
    sharpe = float(np.mean(pnl_arr) / np.std(pnl_arr) * np.sqrt(252)) if np.std(pnl_arr) > 0 else 0

    # Max consecutive losses
    max_consec = 0
    current_consec = 0
    for p in pnls:
        if p <= 0:
            current_consec += 1
            max_consec = max(max_consec, current_consec)
        else:
            current_consec = 0

    # Average R:R achieved
    rr_list = []
    for t in trades:
        sl_dist = abs(t.entry_price - t.sl)
        if sl_dist > 0:
            rr_list.append(t.pnl / (sl_dist / t.entry_price * 100))

    return BacktestMetrics(
        total_trades=total,
        winners=n_wins,
        losers=n_losses,
        win_rate=n_wins / total * 100 if total > 0 else 0,
        avg_win=np.mean(wins) if wins else 0,
        avg_loss=np.mean(losses) if losses else 0,
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else float("inf"),
        total_pnl=sum(pnls),
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        avg_rr=np.mean(rr_list) if rr_list else 0,
        max_consecutive_losses=max_consec,
    )
