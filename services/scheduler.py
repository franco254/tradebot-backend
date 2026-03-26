import os
import time
import threading
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime

from services.ta_engine import TAEngine
from services.broker import (
    fetch_ohlcv, place_order, get_active_trades,
    close_trade, get_current_price
)
from services.persistence import load as _load_state, save as _save_state

# ── Watched symbols ───────────────────────────────────────────────────────────
WATCHLIST = [
    # Crypto
    {'symbol': 'BTC/USDT', 'market': 'CRYPTO'},
    {'symbol': 'ETH/USDT', 'market': 'CRYPTO'},
    {'symbol': 'SOL/USDT', 'market': 'CRYPTO'},
    # Major Forex pairs
    {'symbol': 'EUR/USD',  'market': 'FOREX'},
    {'symbol': 'GBP/USD',  'market': 'FOREX'},
    {'symbol': 'USD/JPY',  'market': 'FOREX'},
    {'symbol': 'USD/CHF',  'market': 'FOREX'},
    {'symbol': 'AUD/USD',  'market': 'FOREX'},
    {'symbol': 'USD/CAD',  'market': 'FOREX'},
    {'symbol': 'NZD/USD',  'market': 'FOREX'},
    {'symbol': 'EUR/GBP',  'market': 'FOREX'},
    {'symbol': 'EUR/JPY',  'market': 'FOREX'},
    {'symbol': 'GBP/JPY',  'market': 'FOREX'},
    # Gold
    {'symbol': 'XAU/USD',  'market': 'COMMODITY'},
    # Stocks
    {'symbol': 'AAPL',     'market': 'STOCKS'},
    {'symbol': 'TSLA',     'market': 'STOCKS'},
]

# ── State — restored from disk on startup ────────────────────────────────────
_boot_state      = _load_state()
_signals_cache   = {}
_pending_alerts  = []
_bot_enabled     = _boot_state.get('bot_enabled', True)
_strategy_config = _boot_state.get('strategy_config', {})

scheduler = BackgroundScheduler(timezone='UTC')


def start_scheduler():
    interval = int(os.getenv('POLL_INTERVAL_SECONDS', 30))

    from datetime import timedelta

    # Single recurring job — starts 5s after boot, then every interval.
    # No separate startup job to avoid overlapping cycles.
    scheduler.add_job(run_analysis,
        trigger=IntervalTrigger(seconds=interval,
                                start_date=datetime.utcnow() + timedelta(seconds=5)),
        id='ta_analysis', replace_existing=True)

    # SL/TP monitor every 15s
    scheduler.add_job(check_sl_tp,
        trigger=IntervalTrigger(seconds=15),
        id='sl_tp_check', replace_existing=True)

    # Self-ping every 10 minutes to prevent Render free tier spin-down
    scheduler.add_job(_self_ping,
        trigger=IntervalTrigger(minutes=10),
        id='keep_alive', replace_existing=True)

    scheduler.start()
    print(f"[scheduler] Started — analysis every {interval}s, keep-alive every 10min")


# ── KEEP-ALIVE ────────────────────────────────────────────────────────────────

def _self_ping():
    """
    Pings our own health endpoint every 10 minutes.
    Render free tier spins down after 15 minutes of no inbound traffic.
    This keeps the instance awake 24/7 so the bot never stops trading.
    """
    try:
        port = os.getenv('PORT', '10000')
        url  = f"http://localhost:{port}/"
        r = requests.get(url, timeout=5)
        print(f"[keep-alive] Self-ping OK ({r.status_code})")
    except Exception as e:
        print(f"[keep-alive] Self-ping failed: {e}")


# ── MAIN ANALYSIS LOOP ────────────────────────────────────────────────────────

def run_analysis():
    if not _bot_enabled:
        print("[scheduler] Bot disabled, skipping analysis")
        return

    print(f"[scheduler] Starting analysis of {len(WATCHLIST)} symbols...")
    ta          = TAEngine(_strategy_config)
    max_trades  = int(_strategy_config.get('max_open_trades', 3))
    amount_pct  = float(_strategy_config.get('trade_amount_pct', 2))
    sl_pct      = float(_strategy_config.get('stop_loss_pct', 1.5))
    tp_pct      = float(_strategy_config.get('take_profit_pct', 3.0))
    min_conf    = int(_strategy_config.get('min_confidence', 55))
    balance     = 10000.0
    amount_usd  = balance * (amount_pct / 100)

    open_trades  = get_active_trades()
    open_symbols = {t['symbol'] for t in open_trades}

    for item in WATCHLIST:
        symbol = item['symbol']
        market = item['market']
        try:
            df = fetch_ohlcv(symbol, market, limit=250)
            if df is None or len(df) == 0:
                print(f"[scheduler] No data for {symbol}, skipping")
                continue

            result = ta.analyze(df)
            signal = result['signal']
            conf   = result['confidence']
            print(f"[scheduler] {symbol}: {signal} @ {result['price']} (conf:{conf}%)")

            _signals_cache[symbol] = {
                'symbol':     symbol,
                'market':     market,
                'signal':     signal,
                'confidence': conf,
                'price':      result['price'],
                'indicators': result['indicators'],
                'votes':      result.get('votes', {}),
                'updated_at': datetime.utcnow().isoformat(),
            }

            # Auto-trade: fire if signal strong enough + room for new trade
            if (signal in ('BUY', 'SELL')
                    and conf >= min_conf
                    and len(open_trades) < max_trades
                    and symbol not in open_symbols):
                order = place_order(symbol, market, signal, amount_usd, sl_pct, tp_pct)
                if order['success']:
                    msg = f"{signal} {symbol} @ {result['price']} (conf:{conf}%)"
                    _push_alert('trade', msg)
                    print(f"[scheduler] ✅ Trade opened: {msg}")
                    open_symbols.add(symbol)
                    open_trades = get_active_trades()

        except Exception as e:
            import traceback
            print(f"[scheduler] ERROR analyzing {symbol}: {e}")
            print(traceback.format_exc())
        finally:
            time.sleep(1)  # rate limit buffer between symbols

    print(f"[scheduler] Analysis complete. Cache: {len(_signals_cache)} signals, "
          f"{len(open_trades)} open trades.")


# ── SL/TP MONITOR ─────────────────────────────────────────────────────────────

def check_sl_tp():
    """Check every 15s if any open trade has hit SL or TP."""
    trades = get_active_trades()
    for trade in trades:
        try:
            price = get_current_price(trade['symbol'], trade['market'])
            if not price:
                continue

            if trade['direction'] == 'BUY':
                hit_tp = price >= trade['tp']
                hit_sl = price <= trade['sl']
            else:
                hit_tp = price <= trade['tp']
                hit_sl = price >= trade['sl']

            if hit_tp:
                result = close_trade(trade['id'])
                pnl = result['trade']['pnl'] if result['success'] else 0
                _push_alert('tp', f"✅ TP hit: {trade['symbol']} @ {price:.4f} | PnL: ${pnl:+.2f}")
            elif hit_sl:
                result = close_trade(trade['id'])
                pnl = result['trade']['pnl'] if result['success'] else 0
                _push_alert('sl', f"❌ SL hit: {trade['symbol']} @ {price:.4f} | PnL: ${pnl:+.2f}")

        except Exception as e:
            print(f"[scheduler] SL/TP check error for {trade.get('symbol')}: {e}")


# ── PUBLIC ACCESSORS ──────────────────────────────────────────────────────────

def get_signals_cache() -> dict:
    return _signals_cache


def get_pending_alerts() -> list:
    alerts = list(_pending_alerts)
    _pending_alerts.clear()
    return alerts


def set_bot_enabled(enabled: bool):
    global _bot_enabled
    _bot_enabled = enabled
    # Persist so bot state survives restarts
    state = _load_state()
    state['bot_enabled'] = enabled
    _save_state(state)
    print(f"[scheduler] Bot {'ENABLED ✅' if enabled else 'DISABLED ⏸'}")


def update_strategy_config(config: dict):
    global _strategy_config
    _strategy_config = config
    # Persist so config survives restarts
    state = _load_state()
    state['strategy_config'] = config
    _save_state(state)
    print(f"[scheduler] Strategy config updated and saved")


def _push_alert(alert_type: str, message: str):
    _pending_alerts.append({
        'type':    alert_type,
        'message': message,
        'time':    datetime.utcnow().isoformat(),
    })
    print(f"[alert] {message}")