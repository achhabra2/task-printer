"""
MCP tools for Task Printer operations.

This module implements MCP tools that expose task-printer functionality
for job submission, status checking, and template management.
"""

from __future__ import annotations

import logging
import os
from typing import Any, List

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

# Import existing schemas to avoid duplication
from task_printer.web.schemas import (
    Task, Section, Options, JobSubmitRequest,
    TemplateSection, TemplateCreateRequest, TemplateListItem
)


# Get logger for this module
logger = logging.getLogger(__name__)


# Only keep response models that are specific to MCP tools
class JobResult(BaseModel):
    """Result of submitting a print job via MCP."""
    job_id: str = Field(description="Unique identifier for the submitted print job")
    status: str = Field(description="Current job status", examples=["queued", "processing", "completed", "error"])
    message: str = Field(description="Human-readable status message", examples=["Job submitted successfully", "Job completed", "Job failed: printer offline"])


class JobStatus(BaseModel):
    """Detailed status information for a print job."""
    id: str | None = Field(default=None, description="Unique job identifier")
    type: str | None = Field(default=None, description="Job type identifier")
    status: str | None = Field(default=None, description="Current job status", examples=["queued", "running", "success", "error"])
    created_at: str | None = Field(default=None, description="ISO timestamp when job was created")
    updated_at: str | None = Field(default=None, description="ISO timestamp when job was last updated")
    total: int | None = Field(default=None, description="Total number of tasks in the job", ge=0)
    origin: str | None = Field(default=None, description="Source that created the job", examples=["web", "mcp", "api"])


class TemplateResult(BaseModel):
    """Result of creating a new template via MCP."""
    template_id: int = Field(description="Unique identifier for the created template", ge=1)
    name: str = Field(description="Name of the created template")
    message: str = Field(description="Success message", examples=["Template created successfully"])


class PrintTemplateResult(BaseModel):
    """Result of submitting a template print job via MCP."""
    job_id: str = Field(description="Unique identifier for the submitted print job")
    template_id: int = Field(description="ID of the template that was printed", ge=1)
    status: str = Field(description="Current job status", examples=["queued", "processing"])
    message: str = Field(description="Success message", examples=["Template print job submitted successfully"])


class HealthStatus(BaseModel):
    """System health status information."""
    overall_status: str | None = Field(default=None, description="Overall system health", examples=["healthy", "degraded", "unhealthy"])
    config: dict[str, str] | None = Field(default=None, description="Configuration status information")
    worker: dict[str, str | int] | None = Field(default=None, description="Background worker status and queue information")
    printer: dict[str, str] | None = Field(default=None, description="Printer connectivity status")
    reason: str | None = Field(default=None, description="Reason for degraded status, if applicable")

class SubmitJobRequest(BaseModel):
    """Request model for submitting a print job."""
    sections: List[Section]
    options: Options | None = None


class CreateTemplateRequest(BaseModel):
    """Request model for creating a new print template."""
    name: str = Field(description="Name of the template")
    sections: List[TemplateSection] = Field(description="Sections to include in the template")
    notes: str | None = Field(default=None, description="Optional notes about the template")


class UpdateTemplateRequest(BaseModel):
    """Request model for updating an existing print template."""
    template_id: int = Field(description="ID of the template to update", ge=1)
    name: str | None = Field(default=None, description="New name for the template")
    sections: List[TemplateSection] | None = Field(default=None, description="New sections for the template")
    notes: str | None = Field(default=None, description="New notes for the template")

def register_tools(server: FastMCP) -> None:
    """
    Register all MCP tools with the server.
    
    Args:
        server: FastMCP server instance to register tools with.
    """
    # Job Management Tools
    _register_job_tools(server)
    
    # Template Management Tools  
    _register_template_tools(server)
    
    # System Management Tools
    # _register_system_tools(server)


def _register_job_tools(server: FastMCP) -> None:
    """Register job management tools."""
    
    @server.tool()
    def submit_job(
        request: SubmitJobRequest
    ) -> JobResult:
        """
        Submit a print job to the Task Printer.
        
        Example request:
        {
            "sections": [
                {
                    "category": "Work Tasks",
                    "tasks": [
                        {
                            "text": "Review quarterly budget report",
                            "flair_type": "emoji",
                            "flair_value": "📊",
                            "metadata": {
                                "priority": "high",
                                "assignee": "John Doe",
                                "due": "2025-08-30",
                                "assigned": "2025-08-24"
                            }
                        },
                        {
                            "text": "Schedule team meeting",
                            "flair_type": "none",
                            "flair_value": null
                        }
                    ]
                },
                {
                    "category": "Personal",
                    "tasks": [
                        {
                            "text": "Buy groceries",
                            "flair_type": "icon",
                            "flair_value": "errands"
                        }
                    ]
                }
            ],
            "options": {
                "tear_delay_seconds": 5.0
            }
        }
        """
        try:
            # Import here to avoid circular imports
            from task_printer.printing.worker import ensure_worker, enqueue_tasks
            from task_printer.core.config import load_config
            
            # Validate configuration exists
            try:
                cfg = load_config()
            except Exception:
                cfg = None
            if not cfg:
                raise ToolError("Service not configured. Complete setup first.")
            
            # Validate request using existing schema
            payload = {"sections": request.sections}
            if request.options:
                payload["options"] = request.options
                
            # Get environment limits for validation context
            limits = _get_env_limits()
            req = JobSubmitRequest.model_validate(payload, context={"limits": limits})
            
            # Convert to worker format
            subtitle_tasks = _convert_to_worker_format(req)
            
            if not subtitle_tasks:
                raise ToolError("No valid tasks to print.")
            
            # Prepare options for worker
            worker_options = None
            if req.options and req.options.tear_delay_seconds:
                worker_options = {"tear_delay_seconds": req.options.tear_delay_seconds}
            
            # Ensure worker is running and enqueue job
            ensure_worker()
            try:
                job_id = enqueue_tasks(subtitle_tasks, options=worker_options)
            except TypeError:
                # Backward compatibility for older worker signature
                job_id = enqueue_tasks(subtitle_tasks)
            
            return {
                "job_id": str(job_id),
                "status": "queued",
                "message": "Job submitted successfully"
            }
            
        except ToolError:
            raise  # Re-raise ToolError as-is
        except Exception as e:
            logger.error(f"MCP submit_job failed: {e}")
            raise ToolError(f"Failed to submit job: {str(e)}")
    
    @server.tool()
    def get_job_status(
        job_id: str = Field(description="The unique ID of the print job to check status for", min_length=1)
    ) -> JobStatus: 
        """
        Get the status of a print job.
        """
        try:
            from task_printer.printing.worker import get_job
            
            # Try to get live job status first
            job = get_job(job_id)
            if job:
                return job
            
            # Try to get from database if available
            try:
                from task_printer.core import db as dbh
                db_job = dbh.get_job_db(job_id)
                if db_job:
                    return {
                        "id": db_job.get("id"),
                        "type": db_job.get("type"), 
                        "status": db_job.get("status"),
                        "created_at": db_job.get("created_at"),
                        "updated_at": db_job.get("updated_at"),
                        "total": db_job.get("total"),
                        "origin": db_job.get("origin"),
                    }
            except Exception:
                pass
            
            raise ToolError(f"Job {job_id} not found")
            
        except ToolError:
            raise  # Re-raise ToolError as-is
        except Exception as e:
            logger.error(f"MCP get_job_status failed: {e}")
            raise ToolError(f"Failed to get job status: {str(e)}")


def _register_template_tools(server: FastMCP) -> None:
    """Register template management tools."""
    
    @server.tool()
    def list_templates() -> List[TemplateListItem]:
        """
        List all available templates.
        """
        try:
            from task_printer.core import db as dbh
            templates = dbh.list_templates()
            return templates
        except Exception as e:
            logger.error(f"MCP list_templates failed: {e}")
            raise ToolError(f"Failed to list templates: {str(e)}")
    
    @server.tool()
    def get_template(
        template_id: int = Field(description="The unique ID of the template to retrieve", ge=1)
    ) -> dict[str, Any]:
        """
        Get a specific template by ID.
        """
        try:
            from task_printer.core import db as dbh
            template = dbh.get_template(template_id)
            if not template:
                raise ToolError(f"Template {template_id} not found")
            return template
        except ToolError:
            raise  # Re-raise ToolError as-is
        except Exception as e:
            logger.error(f"MCP get_template failed: {e}")
            raise ToolError(f"Failed to get template: {str(e)}")
    
    @server.tool()
    def create_template(request: CreateTemplateRequest) -> TemplateResult: 
        """
        Create a new template.
        
        Example request:
        {
            "name": "Weekly Planning Template",
            "notes": "Template for weekly task planning and review",
            "sections": [
                {
                    "category": "This Week's Goals",
                    "tasks": [
                        {
                            "text": "Complete project milestone",
                            "flair_type": "emoji",
                            "flair_value": "🎯",
                            "metadata": {
                                "priority": "high",
                                "assignee": "Team Lead"
                            }
                        },
                        {
                            "text": "Review team performance",
                            "flair_type": "icon",
                            "flair_value": "working"
                        }
                    ]
                },
                {
                    "category": "Personal Tasks",
                    "tasks": [
                        {
                            "text": "Exercise 3 times",
                            "flair_type": "icon",
                            "flair_value": "fitness",
                            "metadata": {
                                "priority": "medium"
                            }
                        },
                        {
                            "text": "Meal prep for the week",
                            "flair_type": "icon",
                            "flair_value": "cooking"
                        }
                    ]
                }
            ]
        }
        """
        try:
            from task_printer.core import db as dbh
            
            # Validate using existing schema
            limits = _get_env_limits()
            payload = {"name": request.name, "sections": request.sections}
            if request.notes:
                payload["notes"] = request.notes
                
            req = TemplateCreateRequest.model_validate(payload, context={"limits": limits})
            
            # Convert to DB format
            db_sections = _convert_template_to_db_format(req.sections)
            
            # Create template
            template_id = dbh.create_template(req.name, req.notes, db_sections)
            
            return {
                "template_id": template_id,
                "name": req.name,
                "message": "Template created successfully"
            }
            
        except ToolError:
            raise  # Re-raise ToolError as-is
        except Exception as e:
            logger.error(f"MCP create_template failed: {e}")
            raise ToolError(f"Failed to create template: {str(e)}")
    
    @server.tool()
    def update_template(request: UpdateTemplateRequest) -> TemplateResult:
        """
        Update an existing template.
        
        Example request:
        {
            "template_id": 1,
            "name": "Updated Weekly Planning Template",
            "notes": "Updated template with new sections and improved organization",
            "sections": [
                {
                    "category": "Priority Goals",
                    "tasks": [
                        {
                            "text": "Complete critical project deliverable",
                            "flair_type": "emoji",
                            "flair_value": "🚀",
                            "metadata": {
                                "priority": "urgent",
                                "assignee": "Project Manager"
                            }
                        }
                    ]
                },
                {
                    "category": "Daily Habits",
                    "tasks": [
                        {
                            "text": "Morning workout",
                            "flair_type": "icon",
                            "flair_value": "fitness"
                        },
                        {
                            "text": "Review daily priorities",
                            "flair_type": "emoji",
                            "flair_value": "📋"
                        }
                    ]
                }
            ]
        }
        """
        try:
            from task_printer.core import db as dbh
            
            # Check if template exists
            existing_template = dbh.get_template(request.template_id)
            if not existing_template:
                raise ToolError(f"Template {request.template_id} not found")
            
            # Prepare update data - use existing values for fields not provided
            update_name = request.name if request.name is not None else existing_template["name"]
            update_notes = request.notes if request.notes is not None else existing_template.get("notes")
            
            if request.sections is not None:
                # Validate new sections using existing schema
                limits = _get_env_limits()
                temp_payload = {"name": update_name, "sections": request.sections}
                validated_req = TemplateCreateRequest.model_validate(temp_payload, context={"limits": limits})
                # Convert TemplateSection objects to dictionaries for db.update_template
                update_sections = []
                for sec in validated_req.sections:
                    section_data = {
                        "category": sec.category,
                        "tasks": []
                    }
                    for task in sec.tasks:
                        task_data = {
                            "text": task.text,
                            "flair_type": task.flair_type,
                            "flair_value": task.flair_value,
                            "flair_size": task.flair_size
                        }
                        # Add metadata if present
                        if task.metadata:
                            metadata_dict = {}
                            if task.metadata.priority:
                                metadata_dict["priority"] = task.metadata.priority
                            if task.metadata.assignee:
                                metadata_dict["assignee"] = task.metadata.assignee
                            if metadata_dict:
                                task_data["metadata"] = metadata_dict
                        section_data["tasks"].append(task_data)
                    update_sections.append(section_data)
            else:
                # Convert existing sections back to the format expected by update_template
                update_sections = []
                for sec in existing_template.get("sections", []):
                    section_data = {
                        "category": sec.get("category"),
                        "tasks": []
                    }
                    for task in sec.get("tasks", []):
                        task_data = {
                            "text": task.get("text"),
                            "flair_type": task.get("flair_type", "none"),
                            "flair_value": task.get("flair_value"),
                            "flair_size": task.get("flair_size")
                        }
                        # Add metadata if present
                        metadata = task.get("metadata", {})
                        if metadata and any(metadata.get(k) for k in ["assigned", "due", "priority", "assignee"]):
                            task_data["metadata"] = {k: v for k, v in metadata.items() if v}
                        section_data["tasks"].append(task_data)
                    update_sections.append(section_data)
            
            # Update template with the complete data
            success = dbh.update_template(request.template_id, update_name, update_notes, update_sections)
            if not success:
                raise ToolError(f"Failed to update template {request.template_id}")
            
            return {
                "template_id": request.template_id,
                "name": update_name,
                "message": "Template updated successfully"
            }
            
        except ToolError:
            raise  # Re-raise ToolError as-is
        except Exception as e:
            logger.error(f"MCP update_template failed: {e}")
            raise ToolError(f"Failed to update template: {str(e)}")
    
    @server.tool()
    def print_template(
        template_id: int = Field(description="ID of the template to print", ge=1),
        tear_delay_seconds: float | None = Field(
            description="Optional override for tear-off delay in seconds (0-60)", 
            ge=0.0, 
            le=60.0,
            default=None
        )
    ) -> PrintTemplateResult: 
        """
        Print from an existing template.
        
        Args:
            template_id: ID of template to print.
            tear_delay_seconds: Optional override for tear-off delay.
            
        Returns:
            Dict with job ID and status.
        """
        try:
            from task_printer.core import db as dbh
            from task_printer.printing import worker
            from task_printer.core.config import load_config, get_config_path
            
            # Get template
            template = dbh.get_template(template_id)
            if not template:
                raise ToolError(f"Template {template_id} not found")
            
            # Convert to print payload
            payload = _template_to_print_payload(template)
            if not payload:
                raise ToolError("Template contains no printable tasks")
            
            # Determine options
            options = None
            if tear_delay_seconds is not None:
                # Clamp the value
                delay = max(0.0, min(60.0, float(tear_delay_seconds)))
                if delay > 0:
                    options = {"tear_delay_seconds": delay}
            else:
                # Use global default if available
                try:
                    cfg = load_config(get_config_path())
                    default_delay = float((cfg or {}).get("default_tear_delay_seconds", 0))
                    default_delay = max(0.0, min(60.0, default_delay))
                    if default_delay > 0:
                        options = {"tear_delay_seconds": default_delay}
                except Exception:
                    options = None
            
            # Submit job
            worker.ensure_worker()
            try:
                job_id = worker.enqueue_tasks(payload, options=options)
            except TypeError:
                job_id = worker.enqueue_tasks(payload)
            
            # Update last used timestamp
            dbh.touch_template_last_used(template_id)
            
            return {
                "job_id": str(job_id),
                "template_id": template_id,
                "status": "queued",
                "message": "Template print job submitted successfully"
            }
            
        except ToolError:
            raise  # Re-raise ToolError as-is
        except Exception as e:
            logger.error(f"MCP print_template failed: {e}")
            raise ToolError(f"Failed to print template: {str(e)}")


def _register_system_tools(server: FastMCP) -> None:
    """Register system management tools."""
    
    @server.tool()
    def get_health_status() -> HealthStatus:
        """
        Get system health status.
        
        Returns:
            Dict containing health information for various components.
        """
        try:
            from task_printer.web.health import healthz
            result, status_code = healthz()
            
            # Transform the Flask response into MCP format
            health_status = {
                "overall_status": "healthy" if result.get("status") == "ok" else "degraded",
                "config": {
                    "status": "configured" if result.get("status") != "degraded" or result.get("reason") != "no_config" else "not_configured"
                },
                "worker": {
                    "status": "running" if result.get("worker_running", False) else "stopped",
                    "queue_size": result.get("queue_size", 0)
                },
                "printer": {
                    "status": "connected" if result.get("printer_ok", False) else "disconnected"
                }
            }
            
            if result.get("reason"):
                health_status["reason"] = result["reason"]
                
            return health_status
        except Exception as e:
            logger.error(f"MCP get_health_status failed: {e}")
            raise ToolError(f"Failed to get health status: {str(e)}")
    
    @server.tool()
    def test_print() -> JobResult:
        """
        Submit a test print job.
        """
        try:
            from task_printer.printing.worker import ensure_worker, enqueue_tasks
            from task_printer.core.config import load_config
            
            # Validate configuration
            try:
                cfg = load_config()
            except Exception:
                cfg = None
            if not cfg:
                raise ToolError("Service not configured. Complete setup first.")
            
            # Create test payload
            test_payload = [{
                "category": "MCP Test Print",
                "task": "This is a test print from the MCP server",
                "flair": None,
                "meta": None
            }]
            
            # Submit job
            ensure_worker()
            job_id = enqueue_tasks(test_payload)
            
            return {
                "job_id": str(job_id),
                "status": "queued",
                "message": "Test print job submitted successfully"
            }
            
        except ToolError:
            raise  # Re-raise ToolError as-is
        except Exception as e:
            logger.error(f"MCP test_print failed: {e}")
            raise ToolError(f"Failed to submit test print: {str(e)}")


def _get_env_limits() -> dict[str, int]:
    """Get environment-driven limits for validation."""
    def _env_int(name: str, default: int) -> int:
        try:
            return int(os.environ.get(name, default))
        except Exception:
            return default
    
    return {
        "MAX_SECTIONS": _env_int("TASKPRINTER_MAX_SECTIONS", 50),
        "MAX_TASKS_PER_SECTION": _env_int("TASKPRINTER_MAX_TASKS_PER_SECTION", 50),
        "MAX_TASK_LEN": _env_int("TASKPRINTER_MAX_TASK_LEN", 200),
        "MAX_CATEGORY_LEN": _env_int("TASKPRINTER_MAX_CATEGORY_LEN", 
                                    _env_int("TASKPRINTER_MAX_SUBTITLE_LEN", 100)),
    }


def _convert_to_worker_format(req: Any) -> List[Task]:
    """Convert validated request to worker format."""
    subtitle_tasks = []
    
    for sec in req.sections:
        category = sec.category
        for task in sec.tasks:
            text = (task.text or "").strip()
            if not text:
                continue
            
            # Handle flair
            flair = None
            if task.flair_type != "none" and task.flair_value:
                flair = {
                    "type": task.flair_type,
                    "value": task.flair_value
                }
            
            # Handle metadata
            meta = None
            if task.metadata:
                meta_fields = {}
                for field in ["assigned", "due", "priority", "assignee"]:
                    value = getattr(task.metadata, field, None)
                    if value and str(value).strip():
                        meta_fields[field] = str(value).strip()
                if meta_fields:
                    meta = meta_fields
            
            subtitle_tasks.append({
                "category": category,
                "task": text,  # Worker format uses 'task' field
                "flair": flair,
                "meta": meta
            })
    
    return subtitle_tasks


def _convert_template_to_db_format(sections: List[TemplateSection]) -> List[dict[str, Any]]:
    """Convert template sections to database format."""
    db_sections = []
    
    for sec in sections:
        db_sec = {
            "category": sec.category,
            "tasks": []
        }
        
        for task in sec.tasks:
            db_task = {
                "text": task.text,
                "flair_type": task.flair_type,
                "flair_value": task.flair_value,
            }
            
            if hasattr(task, 'flair_size') and task.flair_size is not None:
                db_task["flair_size"] = task.flair_size
            
            if task.metadata and (task.metadata.priority or task.metadata.assignee):
                db_task["metadata"] = {}
                if task.metadata.priority:
                    db_task["metadata"]["priority"] = task.metadata.priority
                if task.metadata.assignee:
                    db_task["metadata"]["assignee"] = task.metadata.assignee
            
            db_sec["tasks"].append(db_task)
        
        db_sections.append(db_sec)
    
    return db_sections


def _template_to_print_payload(template: dict[str, Any]) -> List[Task]:
    """Convert template to print worker payload format."""
    payload = []
    
    for sec in template.get("sections", []):
        if not isinstance(sec, dict):
            continue
            
        category = (sec.get("category") or sec.get("subtitle") or "").strip()
        
        for task in sec.get("tasks", []):
            if not isinstance(task, dict):
                continue
                
            text = (task.get("text") or "").strip()
            if not text:
                continue
            
            # Handle flair
            flair = None
            ftype = (task.get("flair_type") or "none").strip().lower()
            fval = task.get("flair_value")
            if ftype and ftype != "none" and fval:
                flair = {"type": ftype, "value": fval}
                fsize = task.get("flair_size")
                if fsize is not None:
                    flair["size"] = fsize
            
            # Handle metadata
            meta = None
            task_meta = task.get("metadata")
            if isinstance(task_meta, dict):
                priority = (task_meta.get("priority") or "").strip()
                assignee = (task_meta.get("assignee") or "").strip()
                if priority or assignee:
                    meta = {}
                    if priority:
                        meta["priority"] = priority
                    if assignee:
                        meta["assignee"] = assignee
            
            payload.append({
                "category": category,
                "task": text,  # Worker format uses 'task' field
                "flair": flair,
                "meta": meta
            })
    
    return payload
