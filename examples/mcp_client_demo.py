#!/usr/bin/env python3
"""
Example MCP client for Task Printer.

This script demonstrates how to use the Task Printer MCP server
from an AI assistant or other MCP client application.

Usage:
    python mcp_client_demo.py [--server-url http://localhost:8000]

Prerequisites:
    1. Task Printer MCP server must be running (python mcp_server.py)
    2. FastMCP must be installed (pip install fastmcp)
    3. Task Printer must be configured and have a working printer
"""

import argparse
import asyncio
import json
import logging
import sys
from typing import Any, Dict

try:
    from fastmcp import Client
except ImportError:
    print("FastMCP is required for this example. Install with: pip install fastmcp")
    sys.exit(1)


def setup_logging(debug: bool = False):
    """Setup logging for the demo."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S"
    )


def extract_tool_result(result) -> Dict[str, Any]:
    """Extract data from FastMCP tool result."""
    try:
        if hasattr(result, 'content') and result.content:
            # Content is typically a list of TextContent objects
            content_data = result.content[0]
            if hasattr(content_data, 'text'):
                import json
                return json.loads(content_data.text)
            else:
                return content_data
        else:
            # Fallback - assume it's already the data
            return result
    except (json.JSONDecodeError, AttributeError, IndexError):
        # If we can't parse it, return as-is
        return result


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="MCP Client Demo for Task Printer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "--server-url",
        default="http://localhost:8000/mcp/",
        help="MCP server URL (default: http://localhost:8000)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    return parser.parse_args()


async def demonstrate_health_check(client: Client) -> Dict[str, Any]:
    """Demonstrate health status checking."""
    print("🏥 Checking system health...")
    
    try:
        # Use the get_health_status tool
        health_result = await client.call_tool("get_health_status")
        health_data = extract_tool_result(health_result)
            
        print(f"   Overall Status: {health_data.get('overall_status', 'unknown')}")
        
        # Show component status
        for component in ['config', 'worker', 'printer']:
            if component in health_data:
                status = health_data[component].get('status', 'unknown')
                print(f"   {component.title()}: {status}")
        
        return health_data
        
    except Exception as e:
        print(f"   ❌ Health check failed: {e}")
        return {"overall_status": "error", "error": str(e)}


async def demonstrate_resources(client: Client) -> None:
    """Demonstrate reading MCP resources."""
    print("\n📄 Reading system resources...")
    
    try:
        # Read configuration
        config_content = await client.read_resource("resource://taskprinter/config")
        config_data = json.loads(config_content[0].text)
        print(f"   Configuration: {'✅ Configured' if config_data.get('configured') else '❌ Not configured'}")
        
        if config_data.get('configured'):
            print(f"   Printer Type: {config_data.get('printer_type', 'unknown')}")
        
        # Read templates list
        templates_content = await client.read_resource("resource://taskprinter/templates")
        templates_data = json.loads(templates_content[0].text)
        template_count = templates_data.get('total_templates', 0)
        print(f"   Templates: {template_count} available")
        
        if template_count > 0:
            most_recent = templates_data.get('most_recently_used')
            if most_recent:
                print(f"   Most recent: {most_recent.get('name')}")
        
    except Exception as e:
        print(f"   ❌ Failed to read resources: {e}")


async def demonstrate_simple_job(client: Client) -> str:
    """Demonstrate submitting a simple print job."""
    print("\n🖨️  Submitting a simple print job...")
    
    try:
        # Create a simple task list
        sections = [
            {
                "category": "MCP Demo Tasks",
                "tasks": [
                    {
                        "text": "Test MCP integration",
                        "flair_type": "icon",
                        "flair_value": "working"
                    },
                    {
                        "text": "Verify printer connectivity",
                        "flair_type": "none"
                    },
                    {
                        "text": "Check task completion",
                        "flair_type": "emoji",
                        "flair_value": "✅"
                    }
                ]
            }
        ]
        
        # Submit the job
        job_result = await client.call_tool("submit_job", {
            "sections": sections,
            "options": {"tear_delay_seconds": 1.0}
        })
        
        job_data = extract_tool_result(job_result)
        job_id = job_data.get('job_id')
        print(f"   ✅ Job submitted: {job_id}")
        print(f"   Status: {job_data.get('status')}")
        
        return job_id
        
    except Exception as e:
        print(f"   ❌ Job submission failed: {e}")
        return ""


async def demonstrate_job_monitoring(client: Client, job_id: str) -> None:
    """Demonstrate monitoring a print job."""
    if not job_id:
        return
    
    print(f"\n👀 Monitoring job {job_id}...")
    
    try:
        # Check job status
        status_result = await client.call_tool("get_job_status", {"job_id": job_id})
        status_data = extract_tool_result(status_result)
        
        print(f"   Job ID: {status_data.get('id')}")
        print(f"   Status: {status_data.get('status')}")
        
        if 'progress' in status_data:
            print(f"   Progress: {status_data.get('progress')}%")
        
        if 'created_at' in status_data:
            print(f"   Created: {status_data.get('created_at')}")
            
    except Exception as e:
        print(f"   ❌ Status check failed: {e}")


async def demonstrate_template_creation(client: Client) -> int:
    """Demonstrate creating a template."""
    print("\n📝 Creating a template...")
    
    try:
        # Create a reusable template
        template_data = {
            "name": "MCP Demo Template",
            "notes": "Template created via MCP client demo",
            "sections": [
                {
                    "category": "Daily Standup",
                    "tasks": [
                        {
                            "text": "What did I do yesterday?",
                            "flair_type": "emoji",
                            "flair_value": "📅"
                        },
                        {
                            "text": "What will I do today?",
                            "flair_type": "emoji", 
                            "flair_value": "🎯"
                        },
                        {
                            "text": "Any blockers?",
                            "flair_type": "emoji",
                            "flair_value": "⚠️"
                        }
                    ]
                }
            ]
        }
        
        create_result = await client.call_tool("create_template", template_data)
        create_data = extract_tool_result(create_result)
        
        template_id = create_data.get('template_id')
        print(f"   ✅ Template created: ID {template_id}")
        print(f"   Name: {create_data.get('name')}")
        
        return template_id
        
    except Exception as e:
        print(f"   ❌ Template creation failed: {e}")
        return 0


async def demonstrate_template_printing(client: Client, template_id: int) -> None:
    """Demonstrate printing from a template."""
    if not template_id:
        return
    
    print(f"\n🖨️  Printing from template {template_id}...")
    
    try:
        # Print from the template
        print_result = await client.call_tool("print_template", {
            "template_id": template_id,
            "tear_delay_seconds": 2.0
        })
        
        print_data = extract_tool_result(print_result)
        job_id = print_data.get('job_id')
        print(f"   ✅ Print job submitted: {job_id}")
        print(f"   Template ID: {print_data.get('template_id')}")
        print(f"   Status: {print_data.get('status')}")
        
        # Monitor the template print job
        await demonstrate_job_monitoring(client, job_id)
        
    except Exception as e:
        print(f"   ❌ Template printing failed: {e}")


async def demonstrate_prompts(client: Client) -> None:
    """Demonstrate using MCP prompts."""
    print("\n💭 Demonstrating prompt usage...")
    
    try:
        # Get a task creation prompt
        prompt_result = await client.get_prompt("create_task_list", {
            "description": "Plan a team retrospective meeting",
            "max_sections": 3,
            "max_tasks_per_section": 4,
            "include_flair": True,
            "include_metadata": True
        })
        
        print("   ✅ Generated task creation prompt:")
        # Show first few lines of the prompt
        # FastMCP prompt results have a messages attribute
        if hasattr(prompt_result, 'messages') and prompt_result.messages:
            # Get the content from the first message
            message_content = prompt_result.messages[0]
            if hasattr(message_content, 'content'):
                if hasattr(message_content.content, 'text'):
                    prompt_text = message_content.content.text
                else:
                    prompt_text = str(message_content.content)
            else:
                prompt_text = str(message_content)
        else:
            prompt_text = str(prompt_result)
            
        lines = prompt_text.split('\n')
        for i, line in enumerate(lines[:5]):
            print(f"   {line}")
        if len(lines) > 5:
            print(f"   ... ({len(lines) - 5} more lines)")
            
    except Exception as e:
        print(f"   ❌ Prompt generation failed: {e}")


async def demonstrate_error_handling(client: Client) -> None:
    """Demonstrate error handling."""
    print("\n⚠️  Demonstrating error handling...")
    
    try:
        # Try to get a non-existent template
        await client.call_tool("get_template", {"template_id": 99999})
        print("   ❌ Expected error but none occurred")
        
    except Exception as e:
        print(f"   ✅ Properly handled error: {e}")
    
    try:
        # Try to submit an invalid job
        await client.call_tool("submit_job", {"sections": []})
        print("   ❌ Expected validation error but none occurred")
        
    except Exception as e:
        print(f"   ✅ Properly handled validation error: {e}")


async def main():
    """Main demo function."""
    args = parse_args()
    setup_logging(args.debug)
    
    logger = logging.getLogger(__name__)
    
    print("🚀 Task Printer MCP Client Demo")
    print(f"   Server URL: {args.server_url}")
    print()
    
    try:
        # Connect to the MCP server
        async with Client(args.server_url) as client:
            print("✅ Connected to MCP server")
            
            # Demonstrate various capabilities
            health_result = await demonstrate_health_check(client)
            
            # Only proceed if system is healthy
            if health_result.get('overall_status') != 'healthy':
                print("\n⚠️  System not healthy, some demos may fail")
            
            await demonstrate_resources(client)
            
            # Job submission and monitoring
            job_id = await demonstrate_simple_job(client)
            await demonstrate_job_monitoring(client, job_id)
            
            # Template creation and usage
            template_id = await demonstrate_template_creation(client)
            await demonstrate_template_printing(client, template_id)
            
            # Prompt demonstration
            await demonstrate_prompts(client)
            
            # Error handling
            await demonstrate_error_handling(client)
            
            print("\n🎉 Demo completed successfully!")
            
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        if args.debug:
            logger.exception("Full traceback:")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Demo interrupted by user")
    except Exception as e:
        print(f"\n💥 Fatal error: {e}")
        sys.exit(1)
