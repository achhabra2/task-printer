"""
Web module for Task Printer.

Exposes blueprints for:
- Main UI routes: web_bp
- Jobs endpoints: jobs_bp
- Setup and restart: setup_bp
- Health endpoint: health_bp
"""

from .health import health_bp
from .jobs import jobs_bp
from .routes import web_bp
from .setup import setup_bp

__all__ = ["health_bp", "jobs_bp", "setup_bp", "web_bp"]
