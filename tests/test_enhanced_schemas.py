#!/usr/bin/env python3
"""
Test the enhanced schemas to ensure they work correctly.
"""

def test_enhanced_schemas():
    """Test that our enhanced schemas work with the original payloads."""
    from task_printer.mcp.tools import _get_env_limits
    from task_printer.web.schemas import JobSubmitRequest
    
    # Test the original payload that was failing
    payload = {
        "sections": [
            {
                "category": "Morning Routine",
                "tasks": [
                    {
                        "text": "Brew coffee",
                        "flair_type": "emoji",
                        "flair_value": "☕"
                    }
                ]
            }
        ],
        "options": None
    }
    
    # Test with metadata
    payload_with_metadata = {
        "sections": [
            {
                "category": "Work Tasks",
                "tasks": [
                    {
                        "text": "Review quarterly reports",
                        "flair_type": "icon",
                        "flair_value": "document",
                        "metadata": {
                            "priority": "high",
                            "assignee": "John Smith",
                            "due": "2024-12-31"
                        }
                    }
                ]
            }
        ],
        "options": {
            "tear_delay_seconds": 5.0
        }
    }
    
    # Get environment limits for validation context
    limits = _get_env_limits()
    
    # Test validation
    try:
        req1 = JobSubmitRequest.model_validate(payload, context={"limits": limits})
        print("✅ Basic payload validation successful!")
        print(f"   Section: {req1.sections[0].category}")
        print(f"   Task: {req1.sections[0].tasks[0].text}")
        print(f"   Flair: {req1.sections[0].tasks[0].flair_type} = {req1.sections[0].tasks[0].flair_value}")
    except Exception as e:
        print(f"❌ Basic payload validation failed: {e}")
    
    try:
        req2 = JobSubmitRequest.model_validate(payload_with_metadata, context={"limits": limits})
        print("✅ Metadata payload validation successful!")
        print(f"   Section: {req2.sections[0].category}")
        print(f"   Task: {req2.sections[0].tasks[0].text}")
        print(f"   Priority: {req2.sections[0].tasks[0].metadata.priority}")
        print(f"   Assignee: {req2.sections[0].tasks[0].metadata.assignee}")
        print(f"   Due: {req2.sections[0].tasks[0].metadata.due}")
        print(f"   Options: tear_delay = {req2.options.tear_delay_seconds}s")
    except Exception as e:
        print(f"❌ Metadata payload validation failed: {e}")
    
    # Test template creation
    try:
        from task_printer.web.schemas import TemplateCreateRequest
        
        template_payload = {
            "name": "Morning Routine Template",
            "notes": "My daily morning checklist",
            "sections": [
                {
                    "category": "Personal Care",
                    "tasks": [
                        {
                            "text": "Brush teeth",
                            "flair_type": "emoji",
                            "flair_value": "🦷",
                            "flair_size": 50
                        }
                    ]
                }
            ]
        }
        
        template_req = TemplateCreateRequest.model_validate(template_payload, context={"limits": limits})
        print("✅ Template creation validation successful!")
        print(f"   Template: {template_req.name}")
        print(f"   Notes: {template_req.notes}")
        print(f"   Task: {template_req.sections[0].tasks[0].text}")
        print(f"   Flair size: {template_req.sections[0].tasks[0].flair_size}")
        
    except Exception as e:
        print(f"❌ Template validation failed: {e}")

if __name__ == "__main__":
    test_enhanced_schemas()
