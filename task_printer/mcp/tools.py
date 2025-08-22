"""
MCP tools for Task Printer operations.

This module implements MCP tools that expose task-printer functionality
for job submission, status checking, and template management.

Type Definitions:
- FlairData: Structured flair information with specific types and optional sizing
- TaskMetadata: Rich metadata for tasks including priority, assignee, dates, etc.
- Task: Unified task representation for both API input and worker processing
- SectionData: Collection of tasks grouped by category
"""

from __future__ import annotations

import logging
import os
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field


# Get logger for this module
logger = logging.getLogger(__name__)


# Pydantic models for better schema generation
class FlairData(BaseModel):
    """Structured flair data for task decoration."""
    type: Literal["none", "icon", "image", "qr", "emoji"]
    value: str  # The actual flair content (icon name, image path, QR data, emoji)
    size: int | None = None  # Optional size modifier


class TaskMetadata(BaseModel):
    """Structured metadata for tasks."""
    priority: Literal["low", "medium", "high"] | str | None = None
    assignee: str | None = None
    assigned: str | None = None  # Date/time assigned 
    due: str | None = None  # Due date/time
    tags: list[str] | None = None
    notes: str | None = None


class Task(BaseModel):
    """Unified task representation for both API input and worker processing."""
    # Core task data
    text: str  # Task text content
    
    # Flair - supports both input formats
    flair_type: Literal["none", "icon", "image", "qr", "emoji"] = "none"  # API input format
    flair_value: str | None = None  # API input format
    
    # Metadata - supports both formats
    metadata: TaskMetadata | None = None  # API input format


class SectionData(BaseModel):
    """A section containing a category and list of tasks."""
    category: str = Field(description="Section category/title")
    tasks: list[Task] = Field(description="List of tasks in this section")


# Type definitions for better annotation specificity
class JobResult(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatus(BaseModel):
    id: str | None = None
    type: str | None = None
    status: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    total: int | None = None
    origin: str | None = None


class TemplateMetadata(BaseModel):
    id: int | None = None
    name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    last_used: str | None = None
    notes: str | None = None


class TemplateResult(BaseModel):
    template_id: int
    name: str
    message: str


class PrintTemplateResult(BaseModel):
    job_id: str
    template_id: int
    status: str
    message: str


class HealthStatus(BaseModel):
    overall_status: str | None = None
    config: dict[str, str] | None = None
    worker: dict[str, str | int] | None = None
    printer: dict[str, str] | None = None
    reason: str | None = None


# Legacy Task class for backwards compatibility - remove after updating
# class Task(BaseModel):
#     """Unified task representation for both API input and worker processing."""
#     # Core task data
#     text: str | None = None  # Task text content
#     task: str | None = None  # Alias for text (for worker compatibility)
#     
#     # Category/grouping (optional for input, required for worker)
#     category: str | None = None
#     
#     # Flair - supports both input formats
#     flair_type: Literal["none", "icon", "image", "qr", "emoji"] | None = None  # API input format
#     flair_value: str | None = None  # API input format
#     flair: FlairData | None = None  # Worker format (structured)
#     
#     # Metadata - supports both formats
#     metadata: TaskMetadata | None = None  # API input format
#     meta: TaskMetadata | None = None  # Worker format (alias)


# Legacy SectionData - remove this duplicate
# class SectionData(BaseModel):
#     category: str
#     tasks: list[Task]


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
    _register_system_tools(server)


def _register_job_tools(server: FastMCP) -> None:
    """Register job management tools."""
    
    @server.tool(
        name="submit_job",
        description="Submit a print job to the Task Printer with sections and tasks",
        annotations={
            "title": "Submit Print Job",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True
        }
    )
    def submit_job(
        sections: Annotated[
        list[SectionData],
        Field(
            description="List of sections, each containing a category (str) and tasks (list). "
            "Each task should have: text (str), flair_type ('none'|'icon'|'image'|'qr'|'emoji'), "
            "optional flair_value (str), and optional metadata with priority, assignee, due date, etc.",
            min_length=1,
            max_length=50
        )
    ],
        options: Annotated[
            dict[str, Any] | None,
            Field(
                description="Optional print options. Currently supports: "
                "tear_delay_seconds (float, 0-60) for delay between tasks during manual tear",
                default=None
            )
        ] = None
    ) -> JobResult:
        """
        Submit a print job to the Task Printer.
        
        Args:
            sections: List of sections, each containing:
                - category (str): Section category/title
                - tasks (List[Task]): List of tasks, each with:
                  - text (str): Task text
                  - flair_type (str): "none", "icon", "image", "qr", "emoji"
                  - flair_value (str, optional): Value for flair
                  - metadata (TaskMetadata, optional): Structured task metadata
            options: Optional print options:
                - tear_delay_seconds (float): Delay between tasks for manual tear
        
        Returns:
            Dict containing job_id, status, and message.
            
        Raises:
            ToolError: If job submission fails.
        """
        try:
            # Import here to avoid circular imports
            from task_printer.web.schemas import JobSubmitRequest
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
            payload = {"sections": sections}
            if options:
                payload["options"] = options
                
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
    
    @server.tool(
        name="get_job_status", 
        description="Get the status of a print job by ID",
        annotations={
            "title": "Get Job Status",
            "readOnlyHint": True,
            "openWorldHint": False
        }
    )
    def get_job_status(
        job_id: Annotated[
            str, 
            Field(description="The unique ID of the print job to check status for", min_length=1)
        ]
    ) -> JobStatus: 
        """
        Get the status of a print job.
        
        Args:
            job_id: The ID of the job to check.
            
        Returns:
            Dict containing job status information.
            
        Raises:
            ToolError: If job not found or status check fails.
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
    
    @server.tool(
        name="list_templates",
        description="List all available templates with metadata",
        annotations={
            "title": "List Templates",
            "readOnlyHint": True,
            "openWorldHint": False
        }
    )
    def list_templates() -> list[TemplateMetadata]:
        """
        List all available templates.
        
        Returns:
            List of template metadata dictionaries.
        """
        try:
            from task_printer.core import db as dbh
            templates = dbh.list_templates()
            return templates
        except Exception as e:
            logger.error(f"MCP list_templates failed: {e}")
            raise ToolError(f"Failed to list templates: {str(e)}")
    
    @server.tool(
        name="get_template",
        description="Get a specific template by ID with full details",
        annotations={
            "title": "Get Template",
            "readOnlyHint": True,
            "openWorldHint": False
        }
    )
    def get_template(
        template_id: Annotated[
            int, 
            Field(description="The unique ID of the template to retrieve", ge=1)
        ]
    ) -> dict[str, Any]:
        """
        Get a specific template by ID.
        
        Args:
            template_id: The ID of the template to retrieve.
            
        Returns:
            Template data including sections and tasks.
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
    
    @server.tool(
        name="create_template",
        description="Create a new template with sections and tasks. Sections have same format as submit_job. Notes are optional (max 500 chars).",
        annotations={
            "title": "Create Template",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    def create_template(
        name: Annotated[
            str, 
            Field(description="Name for the new template", min_length=1, max_length=100)
        ],
        sections: Annotated[
            list[SectionData],
            Field(
                description="Template sections structure. Same format as submit_job: list of sections "
                "with category and tasks. Each task supports structured flair and metadata.",
                min_length=1,
                max_length=50
            )
        ],
        options: Annotated[
            dict[str, Any] | None,
            Field(
                description="Optional template options (reserved for future use)", 
                default=None
            )
        ] = None,
        notes: Annotated[
            str | None,
            Field(
                description="Optional notes about the template (max 500 characters)",
                max_length=500,
                default=None
            )
        ] = None
    ) -> TemplateResult: 
        """
        Create a new template.
        
        Args:
            name: Template name.
            sections: Template sections structure.
            options: Optional template options.
            notes: Optional notes about the template.
            
        Returns:
            Dict with template ID and confirmation.
        """
        try:
            from task_printer.web.schemas import TemplateCreateRequest
            from task_printer.core import db as dbh
            
            # Validate using existing schema
            limits = _get_env_limits()
            payload = {"name": name, "sections": sections}
            if notes:
                payload["notes"] = notes
                
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
    
    @server.tool(
        name="print_template",
        description="Print from an existing template by ID. Optional tear_delay_seconds (0-60) for tear-off delay.",
        annotations={
            "title": "Print Template",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True
        }
    )
    def print_template(
        template_id: Annotated[
            int, 
            Field(description="ID of the template to print", ge=1)
        ],
        tear_delay_seconds: Annotated[
            float | None,
            Field(
                description="Optional override for tear-off delay in seconds (0-60)", 
                ge=0.0, 
                le=60.0,
                default=None
            )
        ] = None
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
    
    @server.tool(
        name="get_health_status",
        description="Get system health status for all components",
        annotations={
            "title": "Get Health Status",
            "readOnlyHint": True,
            "openWorldHint": True
        }
    )
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
    
    @server.tool(
        name="test_print",
        description="Submit a test print job to verify printer functionality", 
        annotations={
            "title": "Test Print",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True
        }
    )
    def test_print() -> JobResult:
        """
        Submit a test print job.
        
        Returns:
            Dict with job ID and status.
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


def _convert_to_worker_format(req: Any) -> list[Task]:
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


def _convert_template_to_db_format(sections: list[SectionData]) -> list[dict[str, Any]]:
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


def _template_to_print_payload(template: dict[str, Any]) -> list[Task]:
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
