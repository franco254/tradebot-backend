from flask import Blueprint, jsonify
from services.broker import get_portfolio, get_equity_curve

portfolio_bp = Blueprint('portfolio', __name__)

@portfolio_bp.route('/', methods=['GET'])
def portfolio():
    data = get_portfolio()
    data['equity_curve'] = get_equity_curve()
    return jsonify(data)
