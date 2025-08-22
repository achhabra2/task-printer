"""
Main MCP server implementation for Task Printer.

This module creates and configures the FastMCP server with task-printer
capabilities including tools, resources, and prompts.
"""

from __future__ import annotations

import logging
import os

try:
    from fastmcp import FastMCP
    from fastmcp.server.auth.providers.jwt import JWTVerifier
    from fastmcp.server.auth import AuthProvider, AccessToken
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    FastMCP = None
    JWTVerifier = None
    AuthProvider = None
    AccessToken = None

from .tools import register_tools
from .resources import register_resources
from .prompts import register_prompts
from .auth import SimpleJWTAuth


# Module logger
logger = logging.getLogger(__name__)


def create_mcp_server():
    """
    Create and configure MCP server with task-printer capabilities.
    
    Returns:
        Configured FastMCP server instance.
        
    Raises:
        ImportError: If FastMCP is not available.
        Exception: If server creation fails.
    """
    if not MCP_AVAILABLE or FastMCP is None:
        raise ImportError("FastMCP is not available. Install with: pip install fastmcp")
    
    # Setup authentication if enabled
    auth_provider = None
    if os.environ.get("TASKPRINTER_AUTH_ENABLED", "true").lower() == "true":
        try:
            auth_provider = create_auth_provider()
            logger.info("JWT authentication enabled for MCP server")
        except Exception as e:
            logger.warning(f"Failed to setup authentication: {e}")
    
    # Create server instance with authentication
    server = FastMCP("TaskPrinter", auth=auth_provider)
    
    # Register components
    try:
        register_tools(server)
        register_resources(server)
        register_prompts(server)
        
        auth_status = "with JWT authentication" if auth_provider else "without authentication"
        logger.info(f"MCP server created successfully {auth_status} - all components registered")
            
    except Exception as e:
        logger.error(f"Failed to register MCP components: {e}")
        raise
    
    return server


def create_auth_provider():
    """
    Create JWT authentication provider for the MCP server.
        
    Returns:
        Custom JWT authentication provider instance.
        
    Raises:
        Exception: If authentication setup fails.
    """
    if not AuthProvider:
        raise ImportError("FastMCP AuthProvider not available")
    
    # Initialize our JWT auth system
    auth_system = SimpleJWTAuth()
    
    class TaskPrinterJWTAuth(AuthProvider):
        """Custom JWT authentication provider for TaskPrinter MCP server."""
        
        def __init__(self, auth_system: SimpleJWTAuth):
            self.auth_system = auth_system
            super().__init__()
        
        async def verify_token(self, token: str):
            """
            Verify JWT token and return AccessToken object.
            
            Args:
                token: JWT token string
                
            Returns:
                AccessToken object if valid
                
            Raises:
                ValueError: If token is invalid or expired
            """
            claims = self.auth_system.verify_token(token)
            if not claims:
                raise ValueError("Invalid or expired JWT token")
            
            # Create AccessToken object with the required fields
            return AccessToken(
                token=token,
                client_id=claims.get("sub", "unknown"),  # Use subject as client ID
                scopes=[],  # No scopes for simple JWT auth
                expires_at=claims.get("exp"),  # Unix timestamp from JWT
                resource=None,  # No specific resource
                claims=claims  # Include all JWT claims
            )
        
        def get_routes(self) -> list:
            """
            Get additional routes for authentication endpoints.
            
            Returns:
                Empty list (no additional routes needed for JWT verification)
            """
            return []
        
        def get_resource_metadata_url(self) -> str | None:
            """
            Get OAuth resource metadata URL.
            
            Returns:
                None (no OAuth metadata needed for simple JWT verification)
            """
            return None
    
    provider = TaskPrinterJWTAuth(auth_system)
    logger.info("Custom JWT authentication provider created successfully")
    
    return provider
