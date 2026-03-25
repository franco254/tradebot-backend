import os
import pandas as pd
from datetime import datetime, timedelta
import requests

from services.persistence import load as _load_state, save as _save_state

# ── State — loaded from disk on startup ───────────────────────────────────────
_state = _load_state()

_portfolio     = _state['portfolio']
_active_trades = _state['active_trades']
_trade_history = _state['trade_history']
_equity_curve  = _state['equity_curve']

# ── Price / OHLCV cache ───────────────────────────────────────────────────────
_ohlcv_cache      = {}
_ohlcv_cache_time = {}
CACHE_SECONDS     = 28


def _persist():
    """Save full broker state to disk."""
    _save_state({
        'active_trades':   _active_trades,
        'trade_history':   _trade_history,
        'equity_curve':    _equity_curve,
        'portfolio':       _portfolio,
        'bot_enabled':     True,
        'strategy_config': {},
    })


# ── PRICE DATA ────────────────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str, market: str, limit: int = 100) -> pd.DataFrame:
    market = market.upper()
    cache_key = f"{symbol}:{limit}"
    now = datetime.utcnow()
    if cache_key in _ohlcv_cache_time:
        if (now - _ohlcv_cache_time[cache_key]).total_seconds() < CACHE_SECONDS:
            return _ohlcv_cache[cache_key]
    try:
        if market == 'CRYPTO':
            df = _fetch_crypto_ohlcv(symbol, limit)
        elif market == 'FOREX':
            df = _fetch_forex_ohlcv(symbol, limit)
        elif market == 'STOCKS':
            df = _fetch_stocks_ohlcv(symbol, limit)
        else:
            df = None
        if df is not None and len(df) > 0:
            _ohlcv_cache[cache_key] = df
            _ohlcv_cache_time[cache_key] = now
            return df
    except Exception as e:
        print(f"[broker] fetch_ohlcv failed ({symbol}): {e} — using synthetic data")

    # Synthetic fallback with realistic prices
    bases = {'BTC': 85000, 'ETH': 2000, 'SOL': 135,
             'EUR': 1.08,  'GBP': 1.26, 'AAPL': 210, 'TSLA': 250}
    vols  = {'BTC': 800,   'ETH': 40,   'SOL': 3,
             'EUR': 0.003, 'GBP': 0.004,'AAPL': 3,   'TSLA': 8}
    key  = next((k for k in bases if k in symbol), None)
    return _synthetic_ohlcv(symbol, limit,
                            base=bases.get(key, 100),
                            volatility=vols.get(key, 1))


def _fetch_crypto_ohlcv(symbol: str, limit: int) -> pd.DataFrame:
    try:
        return _fetch_kraken_ohlcv(symbol, limit)
    except Exception as e:
        print(f"[broker] Kraken failed for {symbol}: {e}, trying KuCoin...")
    return _fetch_kucoin_ohlcv(symbol, limit)


def _fetch_kraken_ohlcv(symbol: str, limit: int) -> pd.DataFrame:
    kraken_map = {'BTC/USDT': 'XBTUSD', 'ETH/USDT': 'ETHUSD', 'SOL/USDT': 'SOLUSD'}
    pair = kraken_map.get(symbol)
    if not pair:
        raise ValueError(f"No Kraken mapping for {symbol}")
    url = 'https://api.kraken.com/0/public/OHLC'
    r = requests.get(url, params={'pair': pair, 'interval': 60}, timeout=10)
    r.raise_for_status()
    data = r.json()
    if data.get('error'):
        raise ValueError(f"Kraken error: {data['error']}")
    result_key = next(k for k in data['result'] if k != 'last')
    candles = data['result'][result_key]
    rows = []
    for c in candles[-limit:]:
        rows.append({'timestamp': pd.to_datetime(int(c[0]), unit='s'),
                     'open': float(c[1]), 'high': float(c[2]),
                     'low':  float(c[3]), 'close': float(c[4]), 'volume': float(c[6])})
    return pd.DataFrame(rows).set_index('timestamp')


def _fetch_kucoin_ohlcv(symbol: str, limit: int) -> pd.DataFrame:
    kucoin_map = {'BTC/USDT': 'BTC-USDT', 'ETH/USDT': 'ETH-USDT', 'SOL/USDT': 'SOL-USDT'}
    pair = kucoin_map.get(symbol)
    if not pair:
        raise ValueError(f"No KuCoin mapping for {symbol}")
    r = requests.get('https://api.kucoin.com/api/v1/market/candles',
                     params={'type': '1hour', 'symbol': pair}, timeout=10)
    r.raise_for_status()
    data = r.json().get('data', [])
    rows = []
    for c in reversed(data[:limit]):
        rows.append({'timestamp': pd.to_datetime(int(c[0]), unit='s'),
                     'open': float(c[1]), 'high': float(c[3]),
                     'low':  float(c[4]), 'close': float(c[2]), 'volume': float(c[5])})
    return pd.DataFrame(rows).set_index('timestamp')


def _fetch_forex_ohlcv(symbol: str, limit: int) -> pd.DataFrame:
    api_key = os.getenv('OANDA_API_KEY')
    if api_key:
        return _fetch_oanda_ohlcv(symbol, limit, api_key)
    bases = {'EUR/USD': 1.08, 'GBP/USD': 1.26}
    return _synthetic_ohlcv(symbol, limit, base=bases.get(symbol, 1.10), volatility=0.003)


def _fetch_oanda_ohlcv(symbol: str, limit: int, api_key: str) -> pd.DataFrame:
    oanda_symbol = symbol.replace('/', '_')
    account_type = os.getenv('OANDA_ACCOUNT_TYPE', 'practice')
    base_url = ('https://api-fxtrade.oanda.com' if account_type == 'live'
                else 'https://api-fxpractice.oanda.com')
    r = requests.get(f"{base_url}/v3/instruments/{oanda_symbol}/candles",
                     headers={'Authorization': f'Bearer {api_key}'},
                     params={'count': limit, 'granularity': 'H1', 'price': 'M'}, timeout=10)
    r.raise_for_status()
    rows = []
    for c in r.json()['candles']:
        mid = c['mid']
        rows.append({'timestamp': pd.to_datetime(c['time']),
                     'open': float(mid['o']), 'high': float(mid['h']),
                     'low':  float(mid['l']), 'close': float(mid['c']),
                     'volume': float(c.get('volume', 0))})
    return pd.DataFrame(rows).set_index('timestamp')


def _fetch_stocks_ohlcv(symbol: str, limit: int) -> pd.DataFrame:
    api_key = os.getenv('ALPACA_API_KEY')
    api_secret = os.getenv('ALPACA_SECRET_KEY')
    if api_key and api_secret:
        return _fetch_alpaca_ohlcv(symbol, limit, api_key, api_secret)
    bases = {'AAPL': 210, 'TSLA': 250}
    return _synthetic_ohlcv(symbol, limit, base=bases.get(symbol, 150), volatility=3.0)


def _fetch_alpaca_ohlcv(symbol, limit, api_key, api_secret) -> pd.DataFrame:
    end   = datetime.utcnow()
    start = end - timedelta(hours=limit)
    r = requests.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
                     headers={'APCA-API-KEY-ID': api_key, 'APCA-API-SECRET-KEY': api_secret},
                     params={'timeframe': '1Hour',
                             'start': start.strftime('%Y-%m-%dT%H:%M:%SZ'),
                             'end':   end.strftime('%Y-%m-%dT%H:%M:%SZ'),
                             'limit': limit}, timeout=10)
    r.raise_for_status()
    bars = r.json().get('bars', [])
    rows = [{'timestamp': pd.to_datetime(b['t']), 'open': b['o'],
             'high': b['h'], 'low': b['l'], 'close': b['c'], 'volume': b['v']} for b in bars]
    return pd.DataFrame(rows).set_index('timestamp')


def _synthetic_ohlcv(symbol: str, limit: int, base: float, volatility: float) -> pd.DataFrame:
    import numpy as np
    seed = abs(hash(symbol)) % 9999 + (datetime.utcnow().hour * 7)
    np.random.seed(seed % 2**32)
    closes = [base]
    for _ in range(limit - 1):
        closes.append(max(closes[-1] * (1 + np.random.normal(0, volatility / base)), 0.0001))
    timestamps = [datetime.utcnow() - timedelta(hours=limit - i) for i in range(limit)]
    rows = []
    for i, (ts, c) in enumerate(zip(timestamps, closes)):
        o = closes[i-1] if i > 0 else c
        h = max(o, c) * (1 + abs(np.random.normal(0, (volatility / base) * 0.5)))
        l = min(o, c) * (1 - abs(np.random.normal(0, (volatility / base) * 0.5)))
        rows.append({'timestamp': ts, 'open': o, 'high': h, 'low': l,
                     'close': c, 'volume': np.random.uniform(1000, 50000)})
    return pd.DataFrame(rows).set_index('timestamp')


# ── ORDER EXECUTION ───────────────────────────────────────────────────────────

def place_order(symbol: str, market: str, direction: str,
                amount_usd: float, sl_pct: float, tp_pct: float) -> dict:
    price = get_current_price(symbol, market)
    if not price:
        return {'success': False, 'error': 'Could not fetch price'}

    sl = price * (1 - sl_pct/100) if direction == 'BUY' else price * (1 + sl_pct/100)
    tp = price * (1 + tp_pct/100) if direction == 'BUY' else price * (1 - tp_pct/100)

    trade = {
        'id':         f"{symbol.replace('/', '')}_{int(datetime.utcnow().timestamp())}",
        'symbol':     symbol,
        'market':     market,
        'direction':  direction,
        'entry':      round(price, 6),
        'sl':         round(sl, 6),
        'tp':         round(tp, 6),
        'amount_usd': amount_usd,
        'pnl':        0.0,
        'opened_at':  datetime.utcnow().isoformat(),
        'status':     'open',
    }
    _active_trades.append(trade)
    _update_portfolio()
    _persist()
    return {'success': True, 'trade': trade}


def close_trade(trade_id: str) -> dict:
    global _active_trades
    for t in _active_trades:
        if t['id'] == trade_id:
            price = get_current_price(t['symbol'], t['market']) or t['entry']
            if t['direction'] == 'BUY':
                t['pnl'] = round((price - t['entry']) / t['entry'] * t['amount_usd'], 2)
            else:
                t['pnl'] = round((t['entry'] - price) / t['entry'] * t['amount_usd'], 2)
            t['exit']      = round(price, 6)
            t['closed_at'] = datetime.utcnow().isoformat()
            t['status']    = 'closed'
            _trade_history.insert(0, t)
            _active_trades = [x for x in _active_trades if x['id'] != trade_id]
            _update_portfolio()
            _persist()
            return {'success': True, 'trade': t}
    return {'success': False, 'error': 'Trade not found'}


def close_all_trades() -> dict:
    ids = [t['id'] for t in list(_active_trades)]
    for tid in ids:
        close_trade(tid)
    return {'success': True, 'closed': len(ids)}


def get_current_price(symbol: str, market: str) -> float:
    try:
        if market.upper() == 'CRYPTO':
            kraken_map = {'BTC/USDT': 'XBTUSD', 'ETH/USDT': 'ETHUSD', 'SOL/USDT': 'SOLUSD'}
            pair = kraken_map.get(symbol)
            if pair:
                r = requests.get('https://api.kraken.com/0/public/Ticker',
                                 params={'pair': pair}, timeout=8)
                result_key = next(k for k in r.json()['result'] if k != 'last')
                return float(r.json()['result'][result_key]['c'][0])
    except Exception:
        pass
    df = fetch_ohlcv(symbol, market, limit=2)
    return float(df['close'].iloc[-1]) if df is not None and len(df) else None


# ── PORTFOLIO ─────────────────────────────────────────────────────────────────

def get_portfolio() -> dict:
    _update_portfolio()
    return _portfolio.copy()


def get_active_trades() -> list:
    for t in _active_trades:
        price = get_current_price(t['symbol'], t['market'])
        if price:
            if t['direction'] == 'BUY':
                t['pnl'] = round((price - t['entry']) / t['entry'] * t['amount_usd'], 2)
            else:
                t['pnl'] = round((t['entry'] - price) / t['entry'] * t['amount_usd'], 2)
    return _active_trades


def get_trade_history() -> list:
    return _trade_history[:50]


def get_equity_curve() -> list:
    return _equity_curve[-30:]


def _update_portfolio():
    open_pnl   = sum(t.get('pnl', 0) for t in _active_trades)
    closed_pnl = sum(t.get('pnl', 0) for t in _trade_history)
    wins       = [t for t in _trade_history if t.get('pnl', 0) > 0]
    win_rate   = round(len(wins) / len(_trade_history) * 100, 1) if _trade_history else 0.0
    today_pnl  = sum(t.get('pnl', 0) for t in _trade_history
                     if t.get('closed_at', '')[:10] == datetime.utcnow().strftime('%Y-%m-%d'))
    _portfolio.update({
        'equity':      round(10000.0 + closed_pnl + open_pnl, 2),
        'today_pnl':   round(today_pnl, 2),
        'total_pnl':   round(closed_pnl + open_pnl, 2),
        'win_rate':    win_rate,
        'open_trades': len(_active_trades),
    })
    _equity_curve.append({
        'date':   datetime.utcnow().strftime('%Y-%m-%d %H:%M'),
        'equity': _portfolio['equity']
    })
    # Cap equity curve at 500 points
    if len(_equity_curve) > 500:
        del _equity_curve[:-500]
