#!/usr/bin/env python3
"""
Standalone MCP server for Task Printer.

This script runs a standalone Model Context Protocol server that exposes
Task Printer functionality to AI assistants and other MCP clients.

Usage:
    python mcp_server.py [--host localhost] [--port 8000]
    
Environment Variables:
    TASKPRINTER_MCP_HOST: Host to bind to (default: localhost)
    TASKPRINTER_MCP_PORT: Port to bind to (default: 8000)
    TASKPRINTER_MCP_ENABLED: Enable MCP server (default: true)
    TASKPRINTER_AUTH_ENABLED: Enable JWT authentication (default: true)
    TASKPRINTER_JWT_SECRET: JWT signing secret (auto-generated if not set)
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Add the project root to Python path so we can import task_printer
sys.path.insert(0, str(Path(__file__).parent))

try:
    from task_printer import create_app
    from task_printer.mcp import create_mcp_server_if_available, MCP_AVAILABLE
except ImportError as e:
    print(f"Failed to import task_printer modules: {e}")
    print("Make sure you're running from the project root and dependencies are installed.")
    sys.exit(1)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Task Printer MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "--host",
        default=os.environ.get("TASKPRINTER_MCP_HOST", "localhost"),
        help="Host to bind to (default: localhost)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("TASKPRINTER_MCP_PORT", "8000")),
        help="Port to bind to (default: 8000)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    return parser.parse_args()


def setup_logging(debug: bool = False):
    """Configure logging for the MCP server."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


async def main():
    """Main entry point for the MCP server."""
    args = parse_args()
    setup_logging(args.debug)
    
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
        # Create Flask app for context (without starting the web server)
        logger.info("Creating Flask application context...")
        app = create_app(register_worker=True)
        
        # Create MCP server
        logger.info("Creating MCP server...")
        server = create_mcp_server_if_available(app)
        
        if server is None:
            logger.error("Failed to create MCP server")
            sys.exit(1)
        
        logger.info(f"Starting MCP server on {args.host}:{args.port}")
        
        # Check authentication status
        auth_enabled = os.environ.get("TASKPRINTER_AUTH_ENABLED", "true").lower() == "true"
        if auth_enabled:
            logger.info("🔒 JWT Authentication: ENABLED")
            logger.info("   Generate tokens with: python scripts/generate_token.py")
            logger.info("   Use tokens with: Authorization: Bearer <token>")
        else:
            logger.warning("🔓 JWT Authentication: DISABLED (set TASKPRINTER_AUTH_ENABLED=true to enable)")
        
        logger.info("Available tools: submit_job, get_job_status, list_templates, get_template, create_template, print_template, get_health_status, test_print")
        logger.info("Available resources: config, health, templates, jobs/recent")
        logger.info("Available prompts: create_task_list, optimize_for_printing, template_from_description, print_job_assistant, troubleshooting_guide")
        
        # Start the server using run_async() since we're in an async context
        # According to FastMCP docs, run_async() should be used inside async functions
        await server.run_async(transport="http", host=args.host, port=args.port)
        
    except KeyboardInterrupt:
        logger.info("Shutting down MCP server...")
    except Exception as e:
        logger.error(f"Error running MCP server: {e}")
        if args.debug:
            logger.exception("Full traceback:")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
