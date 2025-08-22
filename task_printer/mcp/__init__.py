"""
MCP (Model Context Protocol) server for Task Printer.

This module provides MCP server functionality that exposes task-printer's
capabilities as tools, resources, and prompts for AI assistants and other
MCP clients.
"""

from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

try:
    from fastmcp import FastMCP
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    FastMCP = None

__all__ = ["create_mcp_server_if_available", "MCP_AVAILABLE"]


def create_mcp_server_if_available(flask_app = None):
    """
    Create MCP server if FastMCP is available, otherwise return None.
    This provides graceful degradation when MCP dependencies aren't installed.
    """
    if not MCP_AVAILABLE:
        if flask_app:
            flask_app.logger.debug("FastMCP not available, skipping MCP server creation")
        return None
    
    try:
        # Import here to avoid circular imports and handle missing modules gracefully
        from .server import create_mcp_server
        return create_mcp_server(flask_app)
    except Exception as e:
        if flask_app:
            flask_app.logger.error(f"Failed to create MCP server: {e}")
        else:
            logging.error(f"Failed to create MCP server: {e}")
        return None
