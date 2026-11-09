"""Vercel serves this module. Paths stay intact, so /api/brief still reaches FastAPI."""

from server.app import app  # noqa: F401
