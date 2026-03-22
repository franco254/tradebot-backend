from flask import Blueprint, jsonify, request
from services.scheduler import get_signals_cache

signals_bp = Blueprint('signals', __name__)

@signals_bp.route('/', methods=['GET'])
def get_signals():
    market = request.args.get('market', 'ALL').upper()
    cache  = get_signals_cache()

    signals = list(cache.values())
    if market != 'ALL':
        signals = [s for s in signals if s.get('market') == market]

    # Sort by confidence descending
    signals.sort(key=lambda x: x.get('confidence', 0), reverse=True)
    return jsonify(signals)


@signals_bp.route('/<symbol>', methods=['GET'])
def get_signal(symbol):
    cache = get_signals_cache()
    symbol = symbol.upper().replace('-', '/')
    if symbol not in cache:
        return jsonify({'error': 'Symbol not found'}), 404
    return jsonify(cache[symbol])
