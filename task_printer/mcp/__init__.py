"""
MCP (Model Context Protocol) server for Task Printer.

This module provides MCP server functionality that exposes task-printer's
capabilities as tools, resources, and prompts for AI assistants and other
MCP clients.
"""

from __future__ import annotations

import logging

try:
    from fastmcp import FastMCP
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    FastMCP = None

__all__ = ["create_mcp_server_if_available", "MCP_AVAILABLE"]


# Module logger
logger = logging.getLogger(__name__)


def create_mcp_server_if_available():
    """
    Create MCP server if FastMCP is available, otherwise return None.
    This provides graceful degradation when MCP dependencies aren't installed.
    
    Returns:
        FastMCP server instance if available, None otherwise.
    """
    if not MCP_AVAILABLE:
        logger.debug("FastMCP not available, skipping MCP server creation")
        return None
    
    try:
        # Import here to avoid circular imports and handle missing modules gracefully
        from .server import create_mcp_server
        return create_mcp_server()
    except Exception as e:
        logger.error(f"Failed to create MCP server: {e}")
        return None
