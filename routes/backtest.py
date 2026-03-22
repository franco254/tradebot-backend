from flask import Blueprint, jsonify, request
from services.ta_engine import TAEngine
from services.broker import fetch_ohlcv
import pandas as pd

backtest_bp = Blueprint('backtest', __name__)

@backtest_bp.route('/', methods=['POST'])
def run_backtest():
    """
    Run a backtest on a symbol using the given strategy config.
    Body: { symbol, market, config: { rsi_period, ... } }
    Returns: win_rate, total_trades, pnl, equity_curve, trade_log
    """
    data   = request.get_json()
    symbol = data.get('symbol', 'BTC/USDT')
    market = data.get('market', 'CRYPTO')
    config = data.get('config', {})
    sl_pct = float(config.get('stop_loss_pct', 1.5))
    tp_pct = float(config.get('take_profit_pct', 3.0))

    # Fetch historical data (500 candles = ~20 days of 1h candles)
    df = fetch_ohlcv(symbol, market, limit=500)
    if df is None or len(df) < 50:
        return jsonify({'error': 'Not enough data'}), 400

    ta          = TAEngine(config)
    balance     = 10000.0
    equity      = balance
    trade_log   = []
    equity_curve = [{'i': 0, 'equity': equity}]
    in_trade    = False
    entry_price = direction = sl = tp = None
    wins = losses = 0

    for i in range(40, len(df)):
        window = df.iloc[:i+1]
        result = ta.analyze(window)
        signal = result['signal']
        price  = result['price']
        conf   = result['confidence']

        if not in_trade:
            if signal in ('BUY', 'SELL') and conf >= 65:
                in_trade    = True
                direction   = signal
                entry_price = price
                amount      = equity * 0.02  # 2% per trade
                sl = price * (1 - sl_pct/100) if direction == 'BUY' else price * (1 + sl_pct/100)
                tp = price * (1 + tp_pct/100) if direction == 'BUY' else price * (1 - tp_pct/100)
        else:
            hit_tp = (price >= tp) if direction == 'BUY' else (price <= tp)
            hit_sl = (price <= sl) if direction == 'BUY' else (price >= sl)

            if hit_tp or hit_sl:
                if direction == 'BUY':
                    pnl = (price - entry_price) / entry_price * amount
                else:
                    pnl = (entry_price - price) / entry_price * amount

                equity += pnl
                outcome = 'WIN' if pnl > 0 else 'LOSS'
                wins   += 1 if pnl > 0 else 0
                losses += 1 if pnl <= 0 else 0

                trade_log.append({
                    'i':        i,
                    'symbol':   symbol,
                    'direction': direction,
                    'entry':    round(entry_price, 6),
                    'exit':     round(price, 6),
                    'pnl':      round(pnl, 2),
                    'outcome':  outcome,
                })
                equity_curve.append({'i': i, 'equity': round(equity, 2)})
                in_trade = False

    total_trades = wins + losses
    win_rate     = round(wins / total_trades * 100, 1) if total_trades else 0
    total_pnl    = round(equity - balance, 2)
    pnl_pct      = round((equity - balance) / balance * 100, 2)

    return jsonify({
        'symbol':       symbol,
        'market':       market,
        'total_trades': total_trades,
        'wins':         wins,
        'losses':       losses,
        'win_rate':     win_rate,
        'total_pnl':    total_pnl,
        'pnl_pct':      pnl_pct,
        'final_equity': round(equity, 2),
        'equity_curve': equity_curve[-100:],  # last 100 points
        'trade_log':    trade_log[-30:],       # last 30 trades
    })
