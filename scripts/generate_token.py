#!/usr/bin/env python3
"""
Generate JWT authentication tokens for TaskPrinter MCP server.

This script creates JWT tokens that can be used to authenticate with
the TaskPrinter MCP server when authentication is enabled.

Usage:
    python scripts/generate_token.py [username]
    
Examples:
    python scripts/generate_token.py
    python scripts/generate_token.py myusername
"""

import sys
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from task_printer.mcp.auth import generate_token_cli

if __name__ == "__main__":
    generate_token_cli()
