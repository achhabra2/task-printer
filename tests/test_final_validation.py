#!/usr/bin/env python3
"""
Final test to ensure our consolidated models work with the original failing payloads.
"""

def test_original_payloads():
    """Test the original payloads that were causing validation errors."""
    from task_printer.mcp.tools import _get_env_limits
    from task_printer.web.schemas import JobSubmitRequest
    
    # Original payload 1 that was failing
    payload1 = {
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
    
    # Original payload 2
    payload2 = {
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
        "options": {}
    }
    
    # Get environment limits for validation context
    limits = _get_env_limits()
    
    # Test validation
    try:
        req1 = JobSubmitRequest.model_validate(payload1, context={"limits": limits})
        print("✅ Original payload 1 validation successful!")
        print(f"   Section: {req1.sections[0].category}")
        print(f"   Task: {req1.sections[0].tasks[0].text}")
        print(f"   Flair: {req1.sections[0].tasks[0].flair_type} = {req1.sections[0].tasks[0].flair_value}")
    except Exception as e:
        print(f"❌ Original payload 1 validation failed: {e}")
    
    try:
        req2 = JobSubmitRequest.model_validate(payload2, context={"limits": limits})
        print("✅ Original payload 2 validation successful!")
        print(f"   Section: {req2.sections[0].category}")
        print(f"   Task: {req2.sections[0].tasks[0].text}")
        print(f"   Flair: {req2.sections[0].tasks[0].flair_type} = {req2.sections[0].tasks[0].flair_value}")
    except Exception as e:
        print(f"❌ Original payload 2 validation failed: {e}")

    # Test enhanced models have good documentation
    from task_printer.mcp.tools import JobResult, TemplateResult, HealthStatus
    
    print("\n📋 Enhanced model field documentation:")
    print(f"JobResult fields: {list(JobResult.model_fields.keys())}")
    print(f"TemplateResult fields: {list(TemplateResult.model_fields.keys())}")
    print(f"HealthStatus fields: {list(HealthStatus.model_fields.keys())}")

if __name__ == "__main__":
    test_original_payloads()
