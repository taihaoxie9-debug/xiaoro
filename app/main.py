"""Compatibility export for the Guide-only runtime."""

from app.guide_runtime.app import app, create_app

__all__ = ["app", "create_app"]
