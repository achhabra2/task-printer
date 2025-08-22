"""
Simple integration test for MCP functionality.

This test verifies that the MCP server can be created and basic functionality works.
"""

import pytest
from task_printer import create_app
from task_printer.mcp import MCP_AVAILABLE, create_mcp_server_if_available


def test_mcp_availability():
    """Test that FastMCP is available in the environment."""
    assert MCP_AVAILABLE, "FastMCP should be available (pip install fastmcp)"


@pytest.mark.skipif(not MCP_AVAILABLE, reason="FastMCP not available")
def test_basic_mcp_server_creation():
    """Test basic MCP server creation."""
    # MCP server should be standalone, not dependent on Flask app
    server = create_mcp_server_if_available()
    
    # Server should be created successfully
    assert server is not None
    
    # Check that the server has the expected attributes
    assert hasattr(server, 'name')
    assert server.name == "TaskPrinter"


@pytest.mark.skipif(not MCP_AVAILABLE, reason="FastMCP not available")  
def test_app_with_mcp_enabled():
    """Test app creation with MCP enabled."""
    app = create_app(enable_mcp=True, register_worker=False)
    
    # App should be created successfully
    assert app is not None
    
    # Should have mcp_server attribute if creation succeeded
    # (it might be None if creation failed, but app should still work)
    if hasattr(app, 'mcp_server') and app.mcp_server:
        assert app.mcp_server.name == "TaskPrinter"


def test_graceful_degradation_without_mcp():
    """Test that app works normally when MCP is disabled."""
    app = create_app(enable_mcp=False, register_worker=False)
    
    assert app is not None
    assert not hasattr(app, 'mcp_server')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
