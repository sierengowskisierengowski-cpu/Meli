"""Meli web frontend server.

FastAPI service that:
- Serves the React UI (built from meli/webui/) as static files at /
- Exposes /api/* endpoints backed by the existing Meli SQLAlchemy
  models for the React dashboard to consume

Launched by ``meli-web`` (see meli/meli/webapi/__main__.py).
"""
