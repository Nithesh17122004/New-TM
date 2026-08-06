# Gunicorn Configuration — Thooku Madurai Backend
# IMPORTANT: This app uses Flask-SocketIO with async_mode='eventlet' and has NO
# Socket.IO message queue (e.g. Redis) configured. Running multiple OS workers
# splits WebSocket connections across processes, so socketio.emit() from an HTTP
# request only reaches riders/clients connected to the SAME worker — riders on
# other workers silently miss delivery offers and accept/reject updates.
# Solution: exactly ONE eventlet worker (eventlet is async; it handles thousands
# of concurrent sockets per process, so a single worker is not a throughput limit).
bind = "0.0.0.0:8000"
workers = 1
worker_class = "eventlet"
worker_connections = 1000
timeout = 120
keepalive = 5
max_requests = 0
max_requests_jitter = 0
loglevel = "info"
accesslog = "-"
errorlog = "-"