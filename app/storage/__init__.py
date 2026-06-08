"""Storage helpers (SQLite schema / migrations) for the history layer."""

from app.storage.migrations import connect, ensure_schema

__all__ = ["connect", "ensure_schema"]
