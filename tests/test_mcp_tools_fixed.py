"""
Updated MCP tools tests that work with the actual FastMCP API.
"""

import pytest
from unittest.mock import patch

from task_printer import create_app
from task_printer.mcp import MCP_AVAILABLE, create_mcp_server_if_available
from task_printer.mcp.server import create_mcp_server


@pytest.fixture
def app_context():
    """Create a test Flask app."""
    app = create_app()
    with app.app_context():
        yield app


class TestMCPToolsActual:
    """Test MCP tools with actual FastMCP API."""

    def test_mcp_available(self):
        """Test that MCP is available."""
        assert MCP_AVAILABLE is True

    def test_mcp_server_creation(self, app_context):
        """Test that MCP server can be created."""
        # MCP server should be standalone, not dependent on Flask app
        server = create_mcp_server_if_available()
        assert server is not None

    @pytest.mark.asyncio
    async def test_tools_registered(self, app_context):
        """Test that all expected tools are registered."""
        # MCP server should be standalone, not dependent on Flask app
        server = create_mcp_server()
        tools = await server.get_tools()
        
        expected_tools = {
            'submit_job', 'get_job_status', 'list_templates', 'get_template',
            'create_template', 'print_template', 'get_health_status', 'test_print'
        }
        
        actual_tools = set(tools.keys()) if isinstance(tools, dict) else set(tools)
        assert expected_tools.issubset(actual_tools)

    @pytest.mark.asyncio 
    async def test_resources_registered(self, app_context):
        """Test that all expected resources are registered."""
        # MCP server should be standalone, not dependent on Flask app
        server = create_mcp_server()
        resources = await server.get_resources()
        
        expected_resources = {
            'resource://taskprinter/config',
            'resource://taskprinter/health',
            'resource://taskprinter/templates', 
            'resource://taskprinter/jobs/recent'
        }
        
        actual_resources = set(resources.keys()) if isinstance(resources, dict) else set(resources)
        assert expected_resources.issubset(actual_resources)

    @pytest.mark.asyncio
    async def test_prompts_registered(self, app_context):
        """Test that all expected prompts are registered."""
        # MCP server should be standalone, not dependent on Flask app
        server = create_mcp_server()
        prompts = await server.get_prompts()
        
        expected_prompts = {
            'create_task_list', 'optimize_for_printing', 'template_from_description',
            'print_job_assistant', 'troubleshooting_guide'
        }
        
        actual_prompts = set(prompts.keys()) if isinstance(prompts, dict) else set(prompts)
        assert expected_prompts.issubset(actual_prompts)

    @pytest.mark.asyncio
    async def test_tool_count(self, app_context):
        """Test that we have the expected number of tools, resources, and prompts."""
        # MCP server should be standalone, not dependent on Flask app
        server = create_mcp_server()
        
        tools = await server.get_tools()
        resources = await server.get_resources()
        prompts = await server.get_prompts()
        
        # Check we have the expected counts
        assert len(tools) == 8, f"Expected 8 tools, got {len(tools)}"
        assert len(resources) == 4, f"Expected 4 resources, got {len(resources)}" 
        assert len(prompts) == 5, f"Expected 5 prompts, got {len(prompts)}"


class TestMCPGracefulDegradation:
    """Test graceful degradation scenarios."""

    def test_mcp_server_creation_when_available(self, app_context):
        """Test server creation when MCP is available."""
        # MCP server should be standalone, not dependent on Flask app
        server = create_mcp_server_if_available()
        assert server is not None

    def test_app_creation_with_mcp_enabled(self, app_context):
        """Test that app creation works with MCP enabled."""
        # App should create successfully even with MCP
        assert app_context is not None
        assert hasattr(app_context, 'config')

    @patch('task_printer.mcp.MCP_AVAILABLE', False)
    def test_app_creation_with_mcp_disabled(self):
        """Test that app creation works with MCP disabled."""
        app = create_app()
        assert app is not None
        
        # MCP server should be standalone, not dependent on Flask app
        server = create_mcp_server_if_available()
        assert server is None