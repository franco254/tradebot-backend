"""
persistence.py — JSON file-based state persistence.

Saves trades, portfolio, and bot config to /tmp/tradebot_state.json
on every write. On startup, reloads state so trades survive restarts.

Render's /tmp is ephemeral per-instance but survives normal restarts
within the same running instance. For full persistence across deploys,
set the DATA_DIR env var to a Render Disk mount path (/data).
"""
import os
import json
import threading
from datetime import datetime

_lock      = threading.Lock()
DATA_DIR   = os.getenv('DATA_DIR', '/tmp')
STATE_FILE = os.path.join(DATA_DIR, 'tradebot_state.json')

_DEFAULTS = {
    'active_trades':   [],
    'trade_history':   [],
    'equity_curve':    [],
    'portfolio': {
        'balance':    10000.0,
        'equity':     10000.0,
        'today_pnl':  0.0,
        'total_pnl':  0.0,
        'win_rate':   0.0,
        'open_trades': 0,
    },
    'bot_enabled':     True,
    'strategy_config': {},
}


def load() -> dict:
    """Load state from disk. Returns defaults if file missing or corrupt."""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
            # Merge with defaults so new keys always exist
            merged = dict(_DEFAULTS)
            merged.update(data)
            print(f"[persistence] Loaded state: "
                  f"{len(merged['active_trades'])} active trades, "
                  f"{len(merged['trade_history'])} history")
            return merged
    except Exception as e:
        print(f"[persistence] Load failed ({e}), using defaults")
    return dict(_DEFAULTS)


def save(state: dict):
    """Write state to disk atomically."""
    with _lock:
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = STATE_FILE + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(state, f, default=str, indent=2)
            os.replace(tmp, STATE_FILE)
        except Exception as e:
            print(f"[persistence] Save failed: {e}")


def get_state_path() -> str:
    return STATE_FILE
