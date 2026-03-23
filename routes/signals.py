from flask import Blueprint, jsonify, request
from services.scheduler import get_signals_cache, run_analysis
import threading

signals_bp = Blueprint('signals', __name__)

@signals_bp.route('/', methods=['GET'])
def get_signals():
    market = request.args.get('market', 'ALL').upper()
    cache  = get_signals_cache()
    signals = list(cache.values())
    if market != 'ALL':
        signals = [s for s in signals if s.get('market') == market]
    signals.sort(key=lambda x: x.get('confidence', 0), reverse=True)
    return jsonify(signals)

@signals_bp.route('/<symbol>', methods=['GET'])
def get_signal(symbol):
    cache = get_signals_cache()
    symbol = symbol.upper().replace('-', '/')
    if symbol not in cache:
        return jsonify({'error': 'Symbol not found'}), 404
    return jsonify(cache[symbol])

@signals_bp.route('/refresh', methods=['GET'])
def refresh_signals():
    """Force an immediate analysis cycle and return results."""
    threading.Thread(target=run_analysis, daemon=True).start()
    import time; time.sleep(5)
    cache = get_signals_cache()
    return jsonify({
        'count': len(cache),
        'signals': list(cache.values())
    })
