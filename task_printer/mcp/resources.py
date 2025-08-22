"""
MCP resources for Task Printer.

This module implements MCP resources that provide access to configuration,
health status, templates, and job information.
"""

from __future__ import annotations

try:
    from fastmcp import FastMCP
    from fastmcp.exceptions import ResourceError
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    FastMCP = None
    ResourceError = Exception  # Fallback for type hints


def register_resources(server) -> None:
    """
    Register all MCP resources with the server.
    
    Args:
        server: FastMCP server instance to register resources with.
    """
    # Core system resources - configuration and health
    _register_system_resources(server)
    
    # Template resources for template management
    _register_template_resources(server)
    
    # Job resources for job management
    _register_job_resources(server)


def _register_system_resources(server) -> None:
    """Register system configuration and status resources."""
    
    @server.resource(
        "resource://taskprinter/config",
        name="Task Printer Configuration",
        description="Current printer configuration and settings",
        mime_type="application/json",
        tags={"config", "system"},
        annotations={
            "readOnlyHint": True,
            "idempotentHint": True
        }
    )
    def get_config() -> dict:
        """
        Get current Task Printer configuration.
        
        Returns:
            Dict containing printer configuration and settings.
        """
        try:
            from task_printer.core.config import load_config, get_config_path
            
            try:
                config = load_config(get_config_path())
                if not config:
                    return {
                        "configured": False,
                        "message": "Task Printer not configured. Complete setup first."
                    }
                
                # Return sanitized config (remove sensitive data)
                sanitized_config = {
                    "configured": True,
                    "printer_type": config.get("printer_type"),
                    "device_path": config.get("device_path", "").replace("/dev/", "[device]/") if config.get("device_path") else None,
                    "network_host": config.get("network_host"),
                    "network_port": config.get("network_port"),
                    "default_tear_delay_seconds": config.get("default_tear_delay_seconds", 0),
                    "emoji_font_path": config.get("emoji_font_path"),
                    "last_updated": config.get("last_updated")
                }
                
                return sanitized_config
                
            except Exception as e:
                return {
                    "configured": False,
                    "error": f"Failed to load configuration: {str(e)}"
                }
                
        except Exception as e:
            return {
                "error": f"Failed to access configuration: {str(e)}"
            }
    
    @server.resource(
        "resource://taskprinter/health",
        name="System Health Status",
        description="Current health status for all system components",
        mime_type="application/json",
        tags={"health", "monitoring", "system"},
        annotations={
            "readOnlyHint": True,
            "idempotentHint": False  # Health status can change between calls
        }
    )
    async def get_health() -> dict:
        """
        Get current system health status.
        
        Returns:
            Dict containing health status for all components.
        """
        try:
            from task_printer.web.health import _get_health_status
            
            health_data = _get_health_status()
            return health_data
            
        except Exception as e:
            return {
                "error": f"Failed to get health status: {str(e)}",
                "overall_status": "error"
            }


def _register_template_resources(server) -> None:
    """Register template-related resources."""
    
    @server.resource(
        "resource://taskprinter/templates",
        name="Templates List",
        description="List of all templates with metadata and statistics",
        mime_type="application/json",
        tags={"templates", "list"},
        annotations={
            "readOnlyHint": True,
            "idempotentHint": True
        }
    )
    def get_templates_list() -> dict:
        """
        Get list of all templates with metadata.
        
        Returns:
            Dict containing template list with statistics.
        """
        try:
            from task_printer.core import db as dbh
            
            templates = dbh.list_templates()
            
            # Add summary statistics
            result = {
                "total_templates": len(templates),
                "templates": templates
            }
            
            if templates:
                # Calculate usage statistics
                used_templates = [t for t in templates if t.get("last_used_at")]
                result["templates_with_usage"] = len(used_templates)
                
                # Most recently used
                if used_templates:
                    most_recent = max(used_templates, key=lambda t: t.get("last_used_at", ""))
                    result["most_recently_used"] = {
                        "id": most_recent.get("id"),
                        "name": most_recent.get("name"),
                        "last_used_at": most_recent.get("last_used_at")
                    }
            
            return result
            
        except Exception as e:
            return {
                "error": f"Failed to get templates: {str(e)}",
                "total_templates": 0,
                "templates": []
            }
    
    @server.resource(
        "resource://taskprinter/templates/{template_id}",
        name="Template Detail",
        description="Detailed information about a specific template",
        mime_type="application/json",
        tags={"templates", "detail"},
        annotations={
            "readOnlyHint": True,
            "idempotentHint": True
        }
    )
    def get_template_detail(template_id: str) -> dict:
        """
        Get detailed information about a specific template.
        
        Args:
            template_id: ID of the template to retrieve.
            
        Returns:
            Dict containing full template structure.
        """
        try:
            from task_printer.core import db as dbh
            
            try:
                tid = int(template_id)
            except ValueError:
                raise ResourceError(f"Invalid template ID: {template_id}")
            
            template = dbh.get_template(tid)
            if not template:
                raise ResourceError(f"Template {template_id} not found")
            
            return template
            
        except ResourceError:
            raise  # Re-raise ResourceError as-is
        except Exception as e:
            return {
                "error": f"Failed to get template {template_id}: {str(e)}"
            }


def _register_job_resources(server) -> None:
    """Register job-related resources."""
    
    @server.resource(
        "resource://taskprinter/jobs/recent",
        name="Recent Jobs",
        description="Recent job history with statistics and worker status",
        mime_type="application/json",
        tags={"jobs", "history", "monitoring"},
        annotations={
            "readOnlyHint": True,
            "idempotentHint": False  # Job list changes over time
        }
    )
    def get_recent_jobs() -> dict:
        """
        Get recent job history.
        
        Returns:
            Dict containing recent jobs and summary.
        """
        try:
            # Try to get recent jobs from database if available
            try:
                from task_printer.core import db as dbh
                recent_jobs = dbh.get_recent_jobs(limit=20)  # Get last 20 jobs
            except Exception:
                recent_jobs = []
            
            # Get current worker queue status
            try:
                from task_printer.printing.worker import get_worker_status
                worker_status = get_worker_status()
            except Exception:
                worker_status = {"status": "unknown"}
            
            result = {
                "recent_jobs_count": len(recent_jobs),
                "recent_jobs": recent_jobs,
                "worker_status": worker_status
            }
            
            # Add job statistics
            if recent_jobs:
                completed_jobs = [j for j in recent_jobs if j.get("status") == "completed"]
                failed_jobs = [j for j in recent_jobs if j.get("status") == "failed"]
                
                result["statistics"] = {
                    "completed": len(completed_jobs),
                    "failed": len(failed_jobs),
                    "success_rate": len(completed_jobs) / len(recent_jobs) if recent_jobs else 0
                }
            
            return result
            
        except Exception as e:
            return {
                "error": f"Failed to get recent jobs: {str(e)}",
                "recent_jobs_count": 0,
                "recent_jobs": []
            }
    
    @server.resource(
        "resource://taskprinter/jobs/{job_id}",
        name="Job Detail",
        description="Detailed information about a specific job",
        mime_type="application/json",
        tags={"jobs", "detail", "monitoring"},
        annotations={
            "readOnlyHint": True,
            "idempotentHint": True
        }
    )
    def get_job_detail(job_id: str) -> dict:
        """
        Get detailed information about a specific job.
        
        Args:
            job_id: ID of the job to retrieve.
            
        Returns:
            Dict containing job details and status.
        """
        try:
            from task_printer.printing.worker import get_job
            
            # Try live worker first
            job = get_job(job_id)
            if job:
                return job
            
            # Try database if available
            try:
                from task_printer.core import db as dbh
                db_job = dbh.get_job_db(job_id)
                if db_job:
                    return db_job
            except Exception:
                pass
            
            raise ResourceError(f"Job {job_id} not found")
            
        except ResourceError:
            raise  # Re-raise ResourceError as-is
        except Exception as e:
            return {
                "error": f"Failed to get job {job_id}: {str(e)}"
            }
