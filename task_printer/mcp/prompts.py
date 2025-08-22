"""
MCP prompts for Task Printer.

This module implements MCP prompts that provide AI assistants with
structured templates for creating tasks and interacting with the printer.
"""

from __future__ import annotations

try:
    from fastmcp import FastMCP
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    FastMCP = None


def register_prompts(server) -> None:
    """
    Register all MCP prompts with the server.
    
    Args:
        server: FastMCP server instance to register prompts with.
    """
    # Task creation and optimization prompts
    _register_task_creation_prompts(server)
    
    # Template-related prompts
    _register_template_prompts(server)
    
    # System and troubleshooting prompts
    _register_system_prompts(server)


def _register_task_creation_prompts(server) -> None:
    """Register prompts for task creation and structuring."""
    
    @server.prompt()
    def create_task_list(
        description: str,
        max_sections: int = 5,
        max_tasks_per_section: int = 10,
        include_flair: bool = False,
        include_metadata: bool = False
    ) -> str:
        """
        Generate a structured task list from a natural language description.
        
        Args:
            description: Natural language description of tasks to be organized
            max_sections: Maximum number of sections to create (default: 5)
            max_tasks_per_section: Maximum tasks per section (default: 10)
            include_flair: Whether to suggest flair (icons, QR codes) for tasks
            include_metadata: Whether to include metadata fields (priority, assignee, etc.)
        
        Returns:
            Structured prompt for creating organized task lists.
        """
        
        prompt = f"""# Task List Creation Assistant

You are helping to create a structured task list for thermal receipt printing. Based on the following description, organize the tasks into logical sections with clear categories.

## Input Description:
{description}

## Guidelines:
- Create up to {max_sections} logical sections
- Each section should have a clear category name (max 100 characters)
- Include up to {max_tasks_per_section} tasks per section
- Each task should be concise and actionable (max 200 characters)
- Tasks should be specific and clear for printing on small receipt paper

## Output Format:
Provide the response as a JSON structure following this format:

```json
{{
  "sections": [
    {{
      "category": "Section Name",
      "tasks": [
        {{
          "text": "Task description"{"," if include_flair or include_metadata else ""}
          {"\"flair_type\": \"none|icon|qr|emoji\"," if include_flair else ""}
          {"\"flair_value\": \"value for flair\"," if include_flair else ""}
          {"\"metadata\": {{" if include_metadata else ""}
            {"\"priority\": \"high|medium|low\"," if include_metadata else ""}
            {"\"assignee\": \"person name\"," if include_metadata else ""}
            {"\"due\": \"YYYY-MM-DD\"," if include_metadata else ""}
            {"\"assigned\": \"YYYY-MM-DD\"" if include_metadata else ""}
          {"}} " if include_metadata else ""}
        }}
      ]
    }}
  ]
}}
```

{"## Flair Options:" if include_flair else ""}
{"- icon: Use predefined icons (working, cleaning, errands, etc.)" if include_flair else ""}
{"- qr: Generate QR codes for URLs, contact info, or reference data" if include_flair else ""}
{"- emoji: Use single emoji characters for visual appeal" if include_flair else ""}

{"## Metadata Fields:" if include_metadata else ""}
{"- priority: high, medium, or low priority" if include_metadata else ""}
{"- assignee: Person responsible for the task" if include_metadata else ""}
{"- due: Due date in YYYY-MM-DD format" if include_metadata else ""}
{"- assigned: Date assigned in YYYY-MM-DD format" if include_metadata else ""}

## Focus Areas:
- Group related tasks together logically
- Use clear, action-oriented language
- Consider the physical constraints of receipt paper (narrow width)
- Prioritize readability and scannability
"""
        
        return prompt
    
    @server.prompt()
    def optimize_for_printing(
        task_structure: str,
        printer_width: str = "58mm"
    ) -> str:
        """
        Optimize task structure for thermal receipt printing.
        
        Args:
            task_structure: JSON or text structure of tasks
            printer_width: Target printer width (default: 58mm)
            
        Returns:
            Prompt for optimizing task layout for printing.
        """
        
        return f"""# Task Printing Optimization

You are optimizing a task list for thermal receipt printing on {printer_width} paper. Consider the physical constraints and readability requirements.

## Current Task Structure:
{task_structure}

## Optimization Guidelines:

### Text Constraints:
- Category names: Maximum 100 characters, should fit on one line
- Task text: Maximum 200 characters, may wrap to multiple lines
- Keep lines readable on narrow paper (typically 32-48 characters wide)

### Layout Considerations:
- Use clear section breaks between categories
- Consider visual hierarchy with different text sizes
- Account for flair elements (icons, QR codes) taking vertical space
- Ensure adequate spacing between tasks for easy reading

### Printing Efficiency:
- Group related tasks to minimize paper waste
- Consider tear-off points between logical groups
- Balance information density with readability

## Recommendations:
Provide specific suggestions for:
1. Text length optimization
2. Section organization
3. Flair usage recommendations
4. Printing sequence optimization

## Output:
Return the optimized structure with explanations for changes made.
"""


def _register_template_prompts(server) -> None:
    """Register prompts for template creation and management."""
    
    @server.prompt()
    def template_from_description(
        description: str,
        template_name: str,
        reusable_elements: bool = True
    ) -> str:
        """
        Create a reusable template from a task description.
        
        Args:
            description: Description of the template purpose and structure
            template_name: Name for the template
            reusable_elements: Whether to identify reusable/variable elements
            
        Returns:
            Prompt for creating structured templates.
        """
        
        return f"""# Template Creation Assistant

Create a reusable template named "{template_name}" based on the following description.

## Template Description:
{description}

## Template Design Goals:
- Create a structure that can be reused for similar scenarios
- Identify common patterns and standard tasks
- {"Consider which elements should be variable/customizable" if reusable_elements else "Create a fixed structure"}
- Design for efficiency and consistency

## Template Structure Requirements:
- Organize tasks into logical sections
- Use clear, descriptive category names
- Include standard tasks that apply to this template type
- {"Mark variable elements that users might want to customize" if reusable_elements else ""}

## Output Format:
```json
{{
  "name": "{template_name}",
  "notes": "Description of when and how to use this template",
  "sections": [
    {{
      "category": "Section Name",
      "tasks": [
        {{
          "text": "Task description",
          "flair_type": "none|icon|qr|emoji",
          "flair_value": "appropriate value",
          "metadata": {{
            "priority": "suggested priority level"
          }}
        }}
      ]
    }}
  ]
}}
```

## Additional Considerations:
- Think about common use cases for this template type
- Consider seasonal or contextual variations
- Include helpful defaults while allowing customization
- {"Suggest areas where users might want to add their own tasks" if reusable_elements else ""}

Focus on creating a practical, reusable template that saves time and ensures consistency.
"""


def _register_system_prompts(server) -> None:
    """Register prompts for system assistance and guidance."""
    
    @server.prompt()
    def print_job_assistant(
        user_goal: str,
        current_context: str = ""
    ) -> str:
        """
        Conversational assistant for print job creation and management.
        
        Args:
            user_goal: What the user wants to accomplish
            current_context: Current system state or previous interactions
            
        Returns:
            Prompt for guiding users through print job creation.
        """
        
        return f"""# Task Printer Assistant

I'm here to help you create and manage print jobs for your thermal receipt printer. Let me understand what you're trying to accomplish and guide you through the process.

## Your Goal:
{user_goal}

{"## Current Context:" if current_context else ""}
{current_context if current_context else ""}

## Available Capabilities:

### Job Submission:
- Create structured task lists with categories and individual tasks
- Add visual elements (icons, QR codes, emoji) to tasks
- Include metadata (priorities, assignees, due dates)
- Configure print options (tear-off delays, spacing)

### Template Management:
- Create reusable templates for common task types
- Save frequently used structures
- Print from existing templates
- Modify and update templates

### System Features:
- Check printer status and connectivity
- Monitor job progress and history
- Test printing functionality
- Configure printer settings

## Common Use Cases:
- Daily task lists and to-do items
- Work assignments and project tasks
- Shopping lists and errands
- Event planning and checklists
- Meeting agendas and action items

## Next Steps:
Based on your goal, I can help you:
1. Structure your tasks into printable format
2. Choose appropriate visual elements
3. Set up reusable templates
4. Optimize for your printer and paper size
5. Troubleshoot any printing issues

What would you like to work on first?
"""
    
    @server.prompt()
    def troubleshooting_guide(
        issue_description: str,
        system_status: str = ""
    ) -> str:
        """
        Provide troubleshooting guidance for Task Printer issues.
        
        Args:
            issue_description: Description of the problem or issue
            system_status: Current system health status if available
            
        Returns:
            Prompt for troubleshooting assistance.
        """
        
        return f"""# Task Printer Troubleshooting Guide

Let me help you resolve the issue you're experiencing with the Task Printer.

## Issue Description:
{issue_description}

{"## Current System Status:" if system_status else ""}
{system_status if system_status else ""}

## Common Issues and Solutions:

### Printer Connectivity:
- **USB Printer**: Check device path, permissions, and USB connection
- **Network Printer**: Verify IP address, port, and network connectivity
- **Serial Printer**: Confirm serial port settings and device availability

### Print Quality Issues:
- Check paper loading and alignment
- Verify printer head cleanliness
- Ensure adequate power supply
- Check for paper jams or obstructions

### Configuration Problems:
- Complete initial setup if not configured
- Verify printer type selection matches hardware
- Check environment variables and paths
- Validate configuration file format

### Job and Queue Issues:
- Monitor worker process status
- Check job queue for stuck or failed jobs
- Verify adequate system resources
- Review error logs for specific failures

## Diagnostic Steps:
1. Check system health status
2. Test basic printer connectivity
3. Submit a simple test print job
4. Review recent job history and errors
5. Verify configuration settings

## Next Actions:
Based on the issue description, I recommend:
- Specific diagnostic commands to run
- Configuration changes to try
- Hardware checks to perform
- When to contact support

Would you like me to walk through any of these troubleshooting steps in detail?
"""
