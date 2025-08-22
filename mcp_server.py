#!/usr/bin/env python3
"""
Standalone MCP server for Task Printer.

This is a completely independent MCP server that doesn't depend on Flask.
It directly imports and uses the core task-printer functionality.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

try:
    from fastmcp import FastMCP
    from fastmcp.server.auth import AuthProvider, AccessToken
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    FastMCP = None

# Import our core functionality directly (no Flask needed)
from task_printer.core.logging import configure_logging
from task_printer.mcp.auth import SimpleJWTAuth


def create_standalone_mcp_server():
    """Create a standalone MCP server without Flask dependency."""
    if not MCP_AVAILABLE:
        raise ImportError("FastMCP is not available. Install with: pip install fastmcp")
    
    # Setup authentication if enabled
    auth_provider = None
    if os.environ.get("TASKPRINTER_AUTH_ENABLED", "true").lower() == "true":
        try:
            auth_provider = create_auth_provider()
            logging.info("JWT authentication enabled for MCP server")
        except Exception as e:
            logging.warning(f"Failed to setup authentication: {e}")
    
    # Create server instance
    server = FastMCP("TaskPrinter", auth=auth_provider)
    
    # Register components - no longer need flask_app parameter
    from task_printer.mcp.tools import register_tools
    from task_printer.mcp.resources import register_resources  
    from task_printer.mcp.prompts import register_prompts
    
    register_tools(server)
    register_resources(server)
    register_prompts(server)
    
    auth_status = "with JWT authentication" if auth_provider else "without authentication"
    logging.info(f"MCP server created successfully {auth_status} - all components registered")
    
    return server


def create_auth_provider():
    """Create JWT authentication provider for the MCP server."""
    auth_system = SimpleJWTAuth()
    
    class TaskPrinterJWTAuth(AuthProvider):
        """Custom JWT authentication provider for TaskPrinter MCP server."""
        
        def __init__(self, auth_system: SimpleJWTAuth):
            self.auth_system = auth_system
            super().__init__()
        
        async def verify_token(self, token: str):
            """Verify JWT token and return AccessToken object."""
            claims = self.auth_system.verify_token(token)
            if not claims:
                raise ValueError("Invalid or expired JWT token")
            
            return AccessToken(
                token=token,
                client_id=claims.get("sub", "unknown"),
                scopes=[],
                expires_at=claims.get("exp"),
                resource=None,
                claims=claims
            )
        
        def get_routes(self) -> list:
            return []
        
        def get_resource_metadata_url(self) -> str | None:
            return None
    
    return TaskPrinterJWTAuth(auth_system)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Standalone Task Printer MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--host",
        default=os.environ.get("TASKPRINTER_MCP_HOST", "localhost"),
        help="Host to bind to (default: localhost)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("TASKPRINTER_MCP_PORT", "5002")),
        help="Port to bind to (default: 5002)"
    )
    
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default=os.environ.get("TASKPRINTER_MCP_TRANSPORT", "http"),
        help="Transport protocol (default: http)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    return parser.parse_args()


async def main():
    """Main entry point for the standalone MCP server."""
    args = parse_args()
    
    # Configure logging using our existing system
    configure_logging()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    logger = logging.getLogger(__name__)
    
    # Check if MCP is enabled
    if os.environ.get("TASKPRINTER_MCP_ENABLED", "true").lower() == "false":
        logger.error("MCP server is disabled via TASKPRINTER_MCP_ENABLED=false")
        sys.exit(1)
    
    # Check if FastMCP is available
    if not MCP_AVAILABLE:
        logger.error("FastMCP is not available. Install with: pip install fastmcp")
        sys.exit(1)
    
    try:
        logger.info("Creating standalone MCP server...")
        server = create_standalone_mcp_server()
        
        # Log startup info
        auth_enabled = os.environ.get("TASKPRINTER_AUTH_ENABLED", "true").lower() == "true"
        if auth_enabled:
            logger.info("🔒 JWT Authentication: ENABLED")
            logger.info("   Generate tokens with: python scripts/generate_token.py")
        else:
            logger.warning("🔓 JWT Authentication: DISABLED")
        
        logger.info("Available tools: submit_job, get_job_status, list_templates, get_template, create_template, print_template, get_health_status, test_print")
        logger.info("Available resources: config, health, templates, jobs/recent")
        logger.info("Available prompts: create_task_list, optimize_for_printing, template_from_description, print_job_assistant, troubleshooting_guide")
        
        # Start the server
        if args.transport == "stdio":
            logger.info("Starting MCP server with STDIO transport")
            await server.run_async(transport="stdio")
        else:
            logger.info(f"Starting MCP server on {args.host}:{args.port} with {args.transport} transport")
            await server.run_async(
                transport=args.transport, 
                host=args.host, 
                port=args.port
            )
        
    except KeyboardInterrupt:
        logger.info("Shutting down MCP server...")
    except Exception as e:
        logger.error(f"Error running MCP server: {e}")
        if args.debug:
            logger.exception("Full traceback:")
        sys.exit(1)
    finally:
        logger.info("MCP server shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
