"""
Nexus Dashboard - Flask routes for the live scoring dashboard.
"""

import logging
from dataclasses import asdict

from flask import Blueprint, jsonify, render_template
from scoring import compute_scores

logger = logging.getLogger("nexus.dashboard")

dashboard_bp = Blueprint("dashboard", __name__, template_folder="templates")

# Default config
DASHBOARD_SYMBOL = "BTC/EUR"
DASHBOARD_EXCHANGE = "kraken"


@dashboard_bp.route("/dashboard")
def dashboard():
    """Serve the dashboard HTML page."""
    return render_template("dashboard.html", symbol=DASHBOARD_SYMBOL)


@dashboard_bp.route("/api/scores")
def api_scores():
    """JSON API endpoint returning current scores. Called by frontend polling."""
    scores = compute_scores(symbol=DASHBOARD_SYMBOL, exchange=DASHBOARD_EXCHANGE)
    return jsonify(asdict(scores))
