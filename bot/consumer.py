"""
Nexus Trading Bot - Webhook consumer.
Receives JSON alerts from TradingView, validates via risk engine, executes on Kraken.

Usage:
  PAPER_TRADING=true python bot/consumer.py          # Paper mode (default)
  PAPER_TRADING=false python bot/consumer.py         # Live mode (requires API keys)

TradingView alert webhook URL: http://<your-ip>:5000/webhook
"""

import logging

from config import Config
from dashboard import dashboard_bp
from executor import Executor
from flask import Flask, jsonify, request
from journal import Journal
from risk_engine import RiskEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("nexus.bot")

app = Flask(__name__)
app.register_blueprint(dashboard_bp)
config = Config()
executor = Executor(config)
risk = RiskEngine(config)
journal = Journal(config)

# Initialize equity on startup
balance = executor.get_balance()
risk.init_equity(balance)
logger.info(
    f"Bot started | Paper={config.PAPER_TRADING} | Balance={balance:.2f} | Max daily losses={config.MAX_DAILY_LOSSES}"
)


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Receive TradingView JSON alert.
    Expected payload (from nexus-indicator.pine alert()):
    {
      "signal": "entry",
      "dir": "long" | "short",
      "entry": 42150.50,
      "sl": 41800.25,
      "tp": 43201.25,
      "score": 5,
      "rr": 3.0,
      "ticker": "BTCUSDT",
      "tf": "60"
    }
    """
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    if not data or "signal" not in data:
        return jsonify({"error": "Missing signal field"}), 400

    journal.log_signal(data)
    logger.info(
        f"Signal received: {data.get('dir', '?').upper()} {data.get('ticker', '?')} score={data.get('score', '?')}"
    )

    if data.get("signal") != "entry":
        return jsonify({"status": "ignored", "reason": "Not an entry signal"}), 200

    # Validate required fields
    required = ["dir", "entry", "sl", "tp", "ticker"]
    missing = [f for f in required if f not in data]
    if missing:
        journal.log_skip(data, f"Missing fields: {missing}")
        return jsonify({"error": f"Missing fields: {missing}"}), 400

    # Risk check
    can_trade, reason = risk.can_trade()
    if not can_trade:
        journal.log_skip(data, reason)
        logger.warning(f"Trade blocked: {reason}")
        return jsonify({"status": "blocked", "reason": reason}), 200

    # Parse numeric fields safely
    try:
        entry = float(data["entry"])
        sl = float(data["sl"])
        tp = float(data["tp"])
    except (ValueError, TypeError) as e:
        journal.log_skip(data, f"Invalid numeric field: {e}")
        return jsonify({"error": f"Invalid numeric field: {e}"}), 400

    direction = data["dir"]

    # Calculate position size
    balance = executor.get_balance()
    quantity = risk.calculate_position_size(balance, entry, sl)
    if quantity <= 0:
        journal.log_skip(data, "Position size calculation returned 0")
        return jsonify({"status": "blocked", "reason": "Invalid position size"}), 200

    # Map ticker to CCXT symbol
    # Known quote currencies for proper splitting (BTCUSDT -> BTC/USDT, DOGEUSDT -> DOGE/USDT)
    ticker = data["ticker"]
    symbol = ticker  # default passthrough
    if "/" not in ticker:
        for quote in ["USDT", "USD", "EUR", "BTC", "ETH"]:
            if ticker.endswith(quote):
                symbol = ticker[: -len(quote)] + "/" + quote
                break

    # Execute
    result = executor.place_order(symbol, direction, entry, sl, tp, quantity)
    journal.log_trade(result, reason)

    if result.status == "failed":
        logger.error(f"Order failed: {result.error}")
        return jsonify({"status": "failed", "error": result.error}), 500

    logger.info(f"Order placed: {result.order_id} | {result.status}")
    return jsonify(
        {
            "status": result.status,
            "order_id": result.order_id,
            "direction": direction,
            "quantity": round(quantity, 6),
            "entry": entry,
            "sl": sl,
            "tp": tp,
        }
    ), 200


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify(
        {
            "status": "running",
            "paper_mode": config.PAPER_TRADING,
            "daily_losses": risk.state.daily_losses,
            "equity": round(risk.state.current_equity, 2),
            "can_trade": risk.can_trade()[0],
        }
    )


if __name__ == "__main__":
    app.run(host=config.WEBHOOK_HOST, port=config.WEBHOOK_PORT, debug=False)
