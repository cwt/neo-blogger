"""Gunicorn configuration (tech-req §15): bind, worker recycling, uvicorn.

Every value honors an environment override and falls back to the
documented default, so container tuning never drifts from ``config.py``
silently (trusted proxies mirror ``[proxy] trusted_proxies``).
"""

import os

bind = os.environ.get("NEOBLOGGER_BIND", "0.0.0.0:8000")
worker_class = "uvicorn.workers.UvicornWorker"
workers = int(os.environ.get("NEOBLOGGER_WORKERS", "2"))
# Bounded worker recycling with jitter keeps memory in check (spec §19.1).
max_requests = int(os.environ.get("NEOBLOGGER_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.environ.get("NEOBLOGGER_MAX_REQUESTS_JITTER", "100"))
timeout = int(os.environ.get("NEOBLOGGER_TIMEOUT", "60"))
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("NEOBLOGGER_LOG_LEVEL", "info")
forwarded_allow_ips = os.environ.get(
    "NEOBLOGGER_TRUSTED_PROXIES", "127.0.0.1,::1"
)
