"""Gunicorn configuration (tech-req §15): bind, worker recycling, uvicorn."""

bind = "0.0.0.0:8000"
worker_class = "uvicorn.workers.UvicornWorker"
workers = 2
# Bounded worker recycling with jitter keeps memory in check (spec §19.1).
max_requests = 1000
max_requests_jitter = 100
timeout = 60
accesslog = "-"
errorlog = "-"
loglevel = "info"
forwarded_allow_ips = "127.0.0.1,::1"
