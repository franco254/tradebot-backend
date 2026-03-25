from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv
import os

from routes.signals import signals_bp
from routes.trades import trades_bp
from routes.portfolio import portfolio_bp
from routes.backtest import backtest_bp
from routes.alerts import alerts_bp
from routes.config import config_bp

load_dotenv()

app = Flask(__name__)
CORS(app)

# ── Register Blueprints ──
app.register_blueprint(signals_bp,   url_prefix='/signals')
app.register_blueprint(trades_bp,    url_prefix='/trades')
app.register_blueprint(portfolio_bp, url_prefix='/portfolio')
app.register_blueprint(backtest_bp,  url_prefix='/backtest')
app.register_blueprint(alerts_bp,    url_prefix='/alerts')
app.register_blueprint(config_bp,    url_prefix='/config')

# ── Health check ──
@app.route('/')
def health():
    return {'status': 'ok', 'service': 'TradeBot Backend'}


def start_background_services():
    """
    Start the scheduler + analysis loop.
    Must be called AFTER gunicorn forks a worker, not in the master process.
    With --preload, threads started in the master are killed on fork.
    Called from gunicorn.conf.py post_fork hook, and directly for local dev.
    """
    import threading
    import time
    from services.scheduler import start_scheduler, run_analysis

    start_scheduler()

    def _analysis_loop():
        print(f"[app] Analysis loop started in worker pid={os.getpid()}", flush=True)
        time.sleep(5)
        while True:
            try:
                run_analysis()
            except Exception as e:
                print(f"[app] Analysis error: {e}", flush=True)
            time.sleep(30)

    t = threading.Thread(target=_analysis_loop, daemon=True)
    t.start()
    print(f"[app] Background thread started (pid={os.getpid()})", flush=True)


# ── Local dev only ──
if __name__ == '__main__':
    start_background_services()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
