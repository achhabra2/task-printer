"""
Main MCP server implementation for Task Printer.

This module creates and configures the FastMCP server with task-printer
capabilities including tools, resources, and prompts.
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

from .tools import register_tools
from .resources import register_resources
from .prompts import register_prompts


def create_mcp_server(flask_app = None):
    """
    Create and configure MCP server with task-printer capabilities.
    
    Args:
        flask_app: Optional Flask application instance for accessing
                  configuration and logging context.
    
    Returns:
        Configured FastMCP server instance.
        
    Raises:
        ImportError: If FastMCP is not available.
        Exception: If server creation fails.
    """
    if not MCP_AVAILABLE or FastMCP is None:
        raise ImportError("FastMCP is not available. Install with: pip install fastmcp")
    
    # Create server instance with basic configuration
    server = FastMCP("TaskPrinter")
    
    # Register components
    try:
        register_tools(server, flask_app)
        register_resources(server, flask_app)
        register_prompts(server, flask_app)
        
        if flask_app:
            flask_app.logger.info("MCP server created successfully with all components registered")
        else:
            logging.info("MCP server created successfully with all components registered")
            
    except Exception as e:
        if flask_app:
            flask_app.logger.error(f"Failed to register MCP components: {e}")
        else:
            logging.error(f"Failed to register MCP components: {e}")
        raise
    
    return server
