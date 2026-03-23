import os
import json
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime

from services.ta_engine import TAEngine
from services.broker import (
    fetch_ohlcv, place_order, get_active_trades,
    close_trade, get_current_price
)

# ── Watched symbols ───────────────────────────────────────────────────────────
WATCHLIST = [
    {'symbol': 'BTC/USDT', 'market': 'CRYPTO'},
    {'symbol': 'ETH/USDT', 'market': 'CRYPTO'},
    {'symbol': 'SOL/USDT', 'market': 'CRYPTO'},
    {'symbol': 'EUR/USD',  'market': 'FOREX'},
    {'symbol': 'GBP/USD',  'market': 'FOREX'},
    {'symbol': 'AAPL',     'market': 'STOCKS'},
    {'symbol': 'TSLA',     'market': 'STOCKS'},
]

# ── Shared signals cache (read by /signals endpoint) ─────────────────────────
_signals_cache   = {}
_pending_alerts  = []
_bot_enabled     = True
_strategy_config = {}

scheduler = BackgroundScheduler(timezone='UTC')


def start_scheduler():
    interval = int(os.getenv('POLL_INTERVAL_SECONDS', 30))
    scheduler.add_job(
        run_analysis,
        trigger=IntervalTrigger(seconds=interval),
        id='ta_analysis',
        replace_existing=True,
    )
    scheduler.add_job(
        check_sl_tp,
        trigger=IntervalTrigger(seconds=15),
        id='sl_tp_check',
        replace_existing=True,
    )
    scheduler.start()
    print(f"[scheduler] Started — analysis every {interval}s")
    # Run immediately on startup so signals are ready right away
    import threading
    threading.Thread(target=run_analysis, daemon=True).start()


# ── MAIN ANALYSIS LOOP ────────────────────────────────────────────────────────

def run_analysis():
    if not _bot_enabled:
        return

    ta = TAEngine(_strategy_config)
    max_trades  = _strategy_config.get('max_open_trades', 3)
    amount_pct  = _strategy_config.get('trade_amount_pct', 2)
    sl_pct      = _strategy_config.get('stop_loss_pct', 1.5)
    tp_pct      = _strategy_config.get('take_profit_pct', 3.0)
    balance     = 10000.0  # TODO: fetch from portfolio
    amount_usd  = balance * (amount_pct / 100)

    open_trades = get_active_trades()
    open_symbols = {t['symbol'] for t in open_trades}

    for item in WATCHLIST:
        symbol = item['symbol']
        market = item['market']

        try:
            df     = fetch_ohlcv(symbol, market, limit=60)
            result = ta.analyze(df)
            signal = result['signal']
            conf   = result['confidence']

            # Cache signal for /signals endpoint
            _signals_cache[symbol] = {
                'symbol':     symbol,
                'market':     market,
                'signal':     signal,
                'confidence': conf,
                'price':      result['price'],
                'indicators': result['indicators'],
                'updated_at': datetime.utcnow().isoformat(),
            }

            # Auto-trade: only if confident + slot available + not already open
            if (signal in ('BUY', 'SELL')
                    and conf >= 70
                    and len(open_trades) < max_trades
                    and symbol not in open_symbols):

                order = place_order(symbol, market, signal, amount_usd, sl_pct, tp_pct)
                if order['success']:
                    msg = f"{signal} {symbol} @ {result['price']} (conf: {conf}%)"
                    _push_alert('trade', msg)
                    open_symbols.add(symbol)
                    open_trades = get_active_trades()

        except Exception as e:
            print(f"[scheduler] Error analyzing {symbol}: {e}")


# ── SL/TP MONITOR ─────────────────────────────────────────────────────────────

def check_sl_tp():
    """Check if any open trade has hit its stop loss or take profit."""
    trades = get_active_trades()
    for trade in trades:
        try:
            price = get_current_price(trade['symbol'], trade['market'])
            if not price:
                continue

            hit_tp = hit_sl = False
            if trade['direction'] == 'BUY':
                hit_tp = price >= trade['tp']
                hit_sl = price <= trade['sl']
            else:
                hit_tp = price <= trade['tp']
                hit_sl = price >= trade['sl']

            if hit_tp:
                close_trade(trade['id'])
                _push_alert('tp', f"TP hit: {trade['symbol']} @ {price:.4f} ✓")
            elif hit_sl:
                close_trade(trade['id'])
                _push_alert('sl', f"SL hit: {trade['symbol']} @ {price:.4f} ✗")

        except Exception as e:
            print(f"[scheduler] SL/TP check error: {e}")


# ── PUBLIC ACCESSORS ──────────────────────────────────────────────────────────

def get_signals_cache() -> dict:
    return _signals_cache


def get_pending_alerts() -> list:
    alerts = _pending_alerts.copy()
    _pending_alerts.clear()
    return alerts


def set_bot_enabled(enabled: bool):
    global _bot_enabled
    _bot_enabled = enabled
    print(f"[scheduler] Bot {'enabled' if enabled else 'disabled'}")


def update_strategy_config(config: dict):
    global _strategy_config
    _strategy_config = config


def _push_alert(alert_type: str, message: str):
    _pending_alerts.append({
        'type':    alert_type,
        'message': message,
        'time':    datetime.utcnow().isoformat(),
    })
    print(f"[alert] {message}")