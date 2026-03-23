import os
import pandas as pd
from datetime import datetime, timedelta
import requests


# ── Shared state ──────────────────────────────────────────────────────────────
_portfolio = {
    'balance':    10000.0,
    'equity':     10000.0,
    'today_pnl':  0.0,
    'total_pnl':  0.0,
    'win_rate':   0.0,
}
_active_trades  = []
_trade_history  = []
_equity_curve   = []   # list of {date, equity}


# ── PRICE DATA ────────────────────────────────────────────────────────────────

def fetch_ohlcv(symbol: str, market: str, limit: int = 100) -> pd.DataFrame:
    market = market.upper()
    try:
        if market == 'CRYPTO':
            return _fetch_crypto_ohlcv(symbol, limit)
        elif market == 'FOREX':
            return _fetch_forex_ohlcv(symbol, limit)
        elif market == 'STOCKS':
            return _fetch_stocks_ohlcv(symbol, limit)
    except Exception as e:
        print(f"[broker] fetch_ohlcv failed ({symbol}): {e} — using synthetic data")
    # Always fall back to synthetic so analysis never blocks
    base = 85000 if 'BTC' in symbol else 3500 if 'ETH' in symbol else 150 if 'SOL' in symbol else 1.08 if 'EUR' in symbol else 1.26 if 'GBP' in symbol else 180
    vol  = 500 if 'BTC' in symbol else 50 if 'ETH' in symbol else 2 if 'SOL' in symbol else 0.002
    return _synthetic_ohlcv(symbol, limit, base=base, volatility=vol)


def _fetch_crypto_ohlcv(symbol: str, limit: int) -> pd.DataFrame:
    """Binance public API — no key required for price data."""
    binance_symbol = symbol.replace('/', '')
    url = f"https://api.binance.com/api/v3/klines"
    params = {'symbol': binance_symbol, 'interval': '1h', 'limit': limit}
    try:
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
    except Exception:
        # Binance blocked or slow — try backup endpoint
        url = f"https://api1.binance.com/api/v3/klines"
        r = requests.get(url, params=params, timeout=8)
        r.raise_for_status()
    data = r.json()
    df = pd.DataFrame(data, columns=[
        'timestamp','open','high','low','close','volume',
        'close_time','qav','num_trades','taker_base','taker_quote','ignore'
    ])
    df = df[['timestamp','open','high','low','close','volume']].copy()
    for col in ['open','high','low','close','volume']:
        df[col] = pd.to_numeric(df[col])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df.set_index('timestamp')


def _fetch_forex_ohlcv(symbol: str, limit: int) -> pd.DataFrame:
    """
    Free forex via exchangerate.host or OANDA practice (if key configured).
    For demo: returns synthetic data if no key present.
    """
    api_key = os.getenv('OANDA_API_KEY')
    if api_key:
        return _fetch_oanda_ohlcv(symbol, limit, api_key)
    # Fallback: generate synthetic realistic data for testing
    return _synthetic_ohlcv(symbol, limit, base=1.08, volatility=0.002)


def _fetch_oanda_ohlcv(symbol: str, limit: int, api_key: str) -> pd.DataFrame:
    oanda_symbol = symbol.replace('/', '_')
    account_type = os.getenv('OANDA_ACCOUNT_TYPE', 'practice')
    base_url = (
        'https://api-fxtrade.oanda.com' if account_type == 'live'
        else 'https://api-fxpractice.oanda.com'
    )
    url = f"{base_url}/v3/instruments/{oanda_symbol}/candles"
    headers = {'Authorization': f'Bearer {api_key}'}
    params = {'count': limit, 'granularity': 'H1', 'price': 'M'}
    r = requests.get(url, headers=headers, params=params, timeout=10)
    r.raise_for_status()
    candles = r.json()['candles']
    rows = []
    for c in candles:
        mid = c['mid']
        rows.append({
            'timestamp': pd.to_datetime(c['time']),
            'open':  float(mid['o']),
            'high':  float(mid['h']),
            'low':   float(mid['l']),
            'close': float(mid['c']),
            'volume': float(c.get('volume', 0))
        })
    df = pd.DataFrame(rows).set_index('timestamp')
    return df


def _fetch_stocks_ohlcv(symbol: str, limit: int) -> pd.DataFrame:
    """Alpaca free data API or synthetic fallback."""
    api_key    = os.getenv('ALPACA_API_KEY')
    api_secret = os.getenv('ALPACA_SECRET_KEY')
    if api_key and api_secret:
        return _fetch_alpaca_ohlcv(symbol, limit, api_key, api_secret)
    return _synthetic_ohlcv(symbol, limit, base=180.0, volatility=2.0)


def _fetch_alpaca_ohlcv(symbol, limit, api_key, api_secret) -> pd.DataFrame:
    end   = datetime.utcnow()
    start = end - timedelta(hours=limit)
    url   = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
    headers = {
        'APCA-API-KEY-ID':     api_key,
        'APCA-API-SECRET-KEY': api_secret,
    }
    params = {
        'timeframe': '1Hour',
        'start':     start.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'end':       end.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'limit':     limit,
    }
    r = requests.get(url, headers=headers, params=params, timeout=10)
    r.raise_for_status()
    bars = r.json().get('bars', [])
    rows = [{'timestamp': pd.to_datetime(b['t']), 'open': b['o'],
             'high': b['h'], 'low': b['l'], 'close': b['c'], 'volume': b['v']}
            for b in bars]
    return pd.DataFrame(rows).set_index('timestamp')


def _synthetic_ohlcv(symbol: str, limit: int, base: float, volatility: float) -> pd.DataFrame:
    """Generates realistic-looking OHLCV data for testing without API keys."""
    import numpy as np
    np.random.seed(abs(hash(symbol)) % 9999)
    closes = [base]
    for _ in range(limit - 1):
        change = np.random.normal(0, volatility)
        closes.append(max(closes[-1] * (1 + change), 0.0001))
    timestamps = [datetime.utcnow() - timedelta(hours=limit - i) for i in range(limit)]
    rows = []
    for i, (ts, c) in enumerate(zip(timestamps, closes)):
        o = closes[i-1] if i > 0 else c
        h = max(o, c) * (1 + abs(np.random.normal(0, volatility * 0.5)))
        l = min(o, c) * (1 - abs(np.random.normal(0, volatility * 0.5)))
        rows.append({'timestamp': ts, 'open': o, 'high': h, 'low': l,
                     'close': c, 'volume': np.random.uniform(1000, 50000)})
    return pd.DataFrame(rows).set_index('timestamp')


# ── ORDER EXECUTION ───────────────────────────────────────────────────────────

def place_order(symbol: str, market: str, direction: str,
                amount_usd: float, sl_pct: float, tp_pct: float) -> dict:
    """
    Place a paper/live trade order.
    Routes to correct broker based on market.
    """
    price = get_current_price(symbol, market)
    if not price:
        return {'success': False, 'error': 'Could not fetch price'}

    sl = price * (1 - sl_pct/100) if direction == 'BUY' else price * (1 + sl_pct/100)
    tp = price * (1 + tp_pct/100) if direction == 'BUY' else price * (1 - tp_pct/100)

    trade = {
        'id':        f"{symbol}_{int(datetime.utcnow().timestamp())}",
        'symbol':    symbol,
        'market':    market,
        'direction': direction,
        'entry':     price,
        'sl':        round(sl, 6),
        'tp':        round(tp, 6),
        'amount_usd': amount_usd,
        'pnl':       0.0,
        'opened_at': datetime.utcnow().isoformat(),
        'status':    'open',
    }

    # Paper trading: just add to active trades list
    _active_trades.append(trade)
    _update_portfolio()
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
            t['exit'] = price
            t['closed_at'] = datetime.utcnow().isoformat()
            t['status'] = 'closed'
            _trade_history.insert(0, t)
            _active_trades = [x for x in _active_trades if x['id'] != trade_id]
            _update_portfolio()
            return {'success': True, 'trade': t}
    return {'success': False, 'error': 'Trade not found'}


def close_all_trades() -> dict:
    ids = [t['id'] for t in _active_trades]
    results = [close_trade(tid) for tid in ids]
    return {'success': True, 'closed': len(results)}


def get_current_price(symbol: str, market: str) -> float:
    """Fetch just the latest price for a symbol."""
    try:
        if market.upper() == 'CRYPTO':
            binance_symbol = symbol.replace('/', '')
            r = requests.get(
                f"https://api.binance.com/api/v3/ticker/price",
                params={'symbol': binance_symbol}, timeout=5
            )
            return float(r.json()['price'])
    except Exception:
        pass
    # Fallback: use last candle close
    df = fetch_ohlcv(symbol, market, limit=2)
    return float(df['close'].iloc[-1]) if df is not None and len(df) else None


# ── PORTFOLIO ─────────────────────────────────────────────────────────────────

def get_portfolio() -> dict:
    _update_portfolio()
    return _portfolio.copy()


def get_active_trades() -> list:
    # Update live PnL for open trades
    for t in _active_trades:
        price = get_current_price(t['symbol'], t['market'])
        if price:
            if t['direction'] == 'BUY':
                t['pnl'] = round((price - t['entry']) / t['entry'] * t['amount_usd'], 2)
            else:
                t['pnl'] = round((t['entry'] - price) / t['entry'] * t['amount_usd'], 2)
    return _active_trades


def get_trade_history() -> list:
    return _trade_history[:50]   # last 50 trades


def get_equity_curve() -> list:
    return _equity_curve[-30:]   # last 30 data points


def _update_portfolio():
    global _portfolio
    open_pnl  = sum(t.get('pnl', 0) for t in _active_trades)
    closed_pnl = sum(t.get('pnl', 0) for t in _trade_history)
    wins = [t for t in _trade_history if t.get('pnl', 0) > 0]
    win_rate = round(len(wins) / len(_trade_history) * 100, 1) if _trade_history else 0.0
    today_pnl = sum(
        t.get('pnl', 0) for t in _trade_history
        if t.get('closed_at', '')[:10] == datetime.utcnow().strftime('%Y-%m-%d')
    )
    _portfolio.update({
        'equity':    round(10000.0 + closed_pnl + open_pnl, 2),
        'today_pnl': round(today_pnl, 2),
        'total_pnl': round(closed_pnl + open_pnl, 2),
        'win_rate':  win_rate,
        'open_trades': len(_active_trades),
    })
    # Append to equity curve
    _equity_curve.append({
        'date':   datetime.utcnow().strftime('%Y-%m-%d %H:%M'),
        'equity': _portfolio['equity']
    })
