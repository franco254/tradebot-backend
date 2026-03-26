"""
persistence.py — Redis-based state persistence via Upstash.

All trade state is saved to Redis on every write and restored on startup.
Survives Render redeploys, restarts, and free tier container wipes.

Requires env var: REDIS_URL
"""
import os
import json
import threading
from datetime import datetime

_lock = threading.Lock()

REDIS_URL = os.getenv(
    'REDIS_URL',
    'redis://default:gQAAAAAAAQn6AAIncDIxMWMwNzU5OGFkMWU0YjUxYWRjNDA4OWI0OGViNzhlZHAyNjgwOTA@close-dingo-68090.upstash.io:6379'
)
STATE_KEY = 'tradebot:state'

_DEFAULTS = {
    'active_trades':    [],
    'trade_history':    [],
    'equity_curve':     [],
    'portfolio': {
        'balance':        10000.0,
        'equity':         10000.0,
        'today_pnl':      0.0,
        'total_pnl':      0.0,
        'realised_pnl':   0.0,
        'unrealised_pnl': 0.0,
        'win_rate':       0.0,
        'open_trades':    0,
    },
    'bot_enabled':      True,
    'strategy_config':  {},
}

_redis_client = None


def _get_client():
    global _redis_client
    if _redis_client is None:
        import redis
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5)
    return _redis_client


def load() -> dict:
    """Load state from Redis. Returns defaults if key missing or error."""
    try:
        r = _get_client()
        raw = r.get(STATE_KEY)
        if raw:
            data   = json.loads(raw)
            merged = dict(_DEFAULTS)
            merged.update(data)
            # Make sure nested portfolio has all keys
            for k, v in _DEFAULTS['portfolio'].items():
                merged['portfolio'].setdefault(k, v)
            print(f"[persistence] Loaded from Redis: "
                  f"{len(merged['active_trades'])} active trades, "
                  f"{len(merged['trade_history'])} history, "
                  f"balance=${merged['portfolio']['balance']}")
            return merged
    except Exception as e:
        print(f"[persistence] Redis load failed ({e}), using defaults")
    return dict(_DEFAULTS)


def save(state: dict):
    """Save state to Redis atomically."""
    with _lock:
        try:
            r   = _get_client()
            raw = json.dumps(state, default=str)
            r.set(STATE_KEY, raw)
        except Exception as e:
            print(f"[persistence] Redis save failed: {e}")


def clear():
    """Wipe state (useful for reset). Called manually if needed."""
    try:
        _get_client().delete(STATE_KEY)
        print("[persistence] State cleared from Redis")
    except Exception as e:
        print(f"[persistence] Clear failed: {e}")
