from flask import Blueprint, jsonify, request
from services.broker import (
    get_active_trades, get_trade_history,
    place_order, close_trade, close_all_trades
)

trades_bp = Blueprint('trades', __name__)

@trades_bp.route('/active', methods=['GET'])
def active():
    return jsonify(get_active_trades())

@trades_bp.route('/history', methods=['GET'])
def history():
    return jsonify(get_trade_history())

@trades_bp.route('/open', methods=['POST'])
def open_trade():
    data = request.get_json()
    result = place_order(
        symbol     = data['symbol'],
        market     = data['market'],
        direction  = data['direction'],
        amount_usd = float(data.get('amount_usd', 200)),
        sl_pct     = float(data.get('sl_pct', 1.5)),
        tp_pct     = float(data.get('tp_pct', 3.0)),
    )
    return jsonify(result)

@trades_bp.route('/close/<trade_id>', methods=['POST'])
def close(trade_id):
    return jsonify(close_trade(trade_id))

@trades_bp.route('/close-all', methods=['POST'])
def close_all():
    return jsonify(close_all_trades())
