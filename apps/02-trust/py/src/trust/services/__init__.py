"""M0..M6 service entrypoints — one FastAPI app per allocated port.

All services are thin HTTP shells over the libraries; tests exercise the
libraries directly (and the scorer app end-to-end via TestClient), so no
service requires Ollama, Postgres or MinIO to run.
"""
