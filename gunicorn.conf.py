# gunicorn.conf.py
# Gunicorn configuration for TradeBot on Render.com
#
# The critical fix: start_background_services() is called in post_fork,
# which runs INSIDE the worker process after gunicorn forks it.
# This ensures APScheduler threads and the analysis loop survive the fork.
# Previously they were started in the master process and silently died.

import os

workers = 1
bind = f"0.0.0.0:{os.environ.get('PORT', 5000)}"
timeout = 300
preload_app = True        # Load app code once in master (fast), then fork
worker_class = "sync"


def post_fork(server, worker):
    """Called in the worker process right after forking from master."""
    server.log.info(f"[gunicorn] Worker forked (pid={worker.pid}) — starting background services")
    from app import start_background_services
    start_background_services()
