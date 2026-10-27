"""Application root entrypoint for Google Cloud Run / ASGI container deployment.

Usage:
    uvicorn app:app --host 0.0.0.0 --port 8080
"""

from agent.server import app

__all__ = ["app"]
