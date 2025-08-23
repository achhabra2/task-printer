from __future__ import annotations

"""
Pydantic schemas for the Task Printer API (v1).

These models validate incoming job submissions and provide a typed structure
for downstream processing. Limits are applied via the validation context
passed at runtime, allowing env-driven constraints without circular imports.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator, model_validator


def _has_control_chars(s: str) -> bool:
    return any((ord(c) < 32 and c not in "\n\r\t") or ord(c) == 127 for c in s)


def _valid_date_str(s: str) -> bool:
    if not s:
        return True
    try:
        s = str(s).strip()
        if not s:
            return True
        import re

        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            y, m, d = s.split("-")
            mi, di = int(m), int(d)
            return 1 <= mi <= 12 and 1 <= di <= 31
        if re.match(r"^\d{2}-\d{2}$", s) or re.match(r"^\d{2}/\d{2}$", s):
            parts = s.replace("/", "-").split("-")
            mi, di = int(parts[0]), int(parts[1])
            return 1 <= mi <= 12 and 1 <= di <= 31
        return False
    except Exception:
        return False


class Metadata(BaseModel):
    """Task metadata for additional context and organization."""
    assigned: Optional[str] = Field(
        default=None,
        description="Date/time assigned in YYYY-MM-DD, MM-DD, or MM/DD format",
        max_length=30,
        examples=["2024-12-25", "12-25", "12/25"]
    )
    due: Optional[str] = Field(
        default=None,
        description="Due date/time in YYYY-MM-DD, MM-DD, or MM/DD format",
        max_length=30,
        examples=["2024-12-31", "12-31", "12/31"]
    )
    priority: Optional[str] = Field(
        default=None,
        description="Task priority level (e.g., 'high', 'medium', 'low')",
        max_length=20,
        examples=["high", "medium", "low"]
    )
    assignee: Optional[str] = Field(
        default=None,
        description="Person assigned to complete this task",
        max_length=60,
        examples=["John Smith", "Team Lead", "jane@company.com"]
    )

    @field_validator("assigned", "due")
    @classmethod
    def _validate_dates(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not v:
            return ""
        if not _valid_date_str(v):
            raise ValueError("invalid date format")
        return v

    @field_validator("priority")
    @classmethod
    def _priority_len(cls, v: Optional[str]) -> Optional[str]:
        return (v or "").strip()

    @field_validator("assignee")
    @classmethod
    def _assignee_len(cls, v: Optional[str]) -> Optional[str]:
        return (v or "").strip()

    @model_validator(mode="after")
    def _enforce_lengths(self) -> "Metadata":
        assigned = self.assigned or ""
        due = self.due or ""
        priority = self.priority or ""
        assignee = self.assignee or ""
        # Mirror legacy caps
        if len(assigned) > 30 or len(due) > 30 or len(priority) > 20 or len(assignee) > 60:
            raise ValueError("metadata fields too long")
        return self


class Task(BaseModel):
    """A single task item with optional flair decoration and metadata."""
    text: str = Field(
        description="The task description or action to be performed. Empty text is allowed but will be filtered out during processing.",
        examples=["Buy groceries", "Call dentist", "Review quarterly reports", ""]
    )
    flair_type: str = Field(
        default="none",
        description="Type of visual decoration for the task. Options: 'none' (no decoration), 'icon' (predefined icon), 'image' (custom image), 'qr' (QR code), 'emoji' (Unicode emoji)",
        examples=["none", "icon", "emoji", "qr", "image"]
    )
    flair_value: Optional[str] = Field(
        default=None,
        description="Content for the flair decoration. Required when flair_type is not 'none'. For 'icon': icon name, 'emoji': Unicode emoji, 'qr': text to encode, 'image': image path/URL",
        examples=["📝", "shopping_cart", "https://example.com", "/path/to/image.png"]
    )
    metadata: Optional[Metadata] = Field(
        default=None,
        description="Additional task metadata like priority, assignee, and dates"
    )

    @field_validator("text")
    @classmethod
    def _text_rules(cls, v: str, info: ValidationInfo) -> str:
        v = (v or "").strip()
        # Allow empty text (UI skips these later) but enforce max/control characters
        limits = (info.context or {}).get("limits", {})
        max_len = int(limits.get("MAX_TASK_LEN", 200))
        if len(v) > max_len:
            raise ValueError(f"task too long (max {max_len})")
        if _has_control_chars(v):
            raise ValueError("control characters not allowed")
        return v

    @field_validator("flair_type")
    @classmethod
    def _flair_type_norm(cls, v: str) -> str:
        v = (v or "none").strip().lower()
        allowed = {"none", "icon", "image", "qr", "emoji"}
        if v not in allowed:
            raise ValueError(f"invalid flair_type: {v}")
        return v

    @model_validator(mode="after")
    def _validate_flair(self) -> "Task":
        ft = self.flair_type
        fv = self.flair_value
        # Nothing to validate if none
        if ft == "none" or fv in (None, ""):
            return self

        # Limits via context
        # Pydantic v2 supplies context via ValidationInfo in field validators,
        # but for model-level we can’t access it directly. We keep only shape checks here;
        # route-layer can do IO (file size) validations.
        if ft == "emoji":
            s = str(fv).strip()
            if not s:
                raise ValueError("emoji value required")
            if len(s) > 16 or _has_control_chars(s):
                raise ValueError("emoji value invalid")
        elif ft == "qr":
            s = str(fv)
            if _has_control_chars(s):
                raise ValueError("qr value invalid")
        elif ft == "icon":
            if not isinstance(fv, str) or not fv.strip():
                raise ValueError("icon value required")
        elif ft == "image":
            if not isinstance(fv, str) or not fv.strip():
                raise ValueError("image path required")
        return self


class Section(BaseModel):
    """A group of related tasks organized under a category header."""
    category: str = Field(
        description="Section title or category name that groups related tasks",
        min_length=1,
        examples=["Morning Routine", "Work Tasks", "Errands", "Shopping List"]
    )
    tasks: List[Task] = Field(
        description="List of tasks belonging to this section",
        min_length=1,
        examples=[[{"text": "Brush teeth", "flair_type": "emoji", "flair_value": "🦷"}]]
    )

    @field_validator("category")
    @classmethod
    def _category_rules(cls, v: str, info: ValidationInfo) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("category required")
        limits = (info.context or {}).get("limits", {})
        max_len = int(limits.get("MAX_CATEGORY_LEN", 100))
        if len(v) > max_len:
            raise ValueError(f"category too long (max {max_len})")
        if _has_control_chars(v):
            raise ValueError("control characters not allowed")
        return v

    @field_validator("tasks")
    @classmethod
    def _tasks_rules(cls, v: List[Task], info: ValidationInfo) -> List[Task]:
        if not isinstance(v, list) or len(v) == 0:
            raise ValueError("tasks must be a non-empty list")
        limits = (info.context or {}).get("limits", {})
        max_tasks = int(limits.get("MAX_TASKS_PER_SECTION", 50))
        if len(v) > max_tasks:
            raise ValueError(f"too many tasks (max {max_tasks})")
        return v


class Options(BaseModel):
    """Print job configuration options."""
    tear_delay_seconds: Optional[float] = Field(
        default=None,
        description="Delay in seconds between tasks when using manual tear-off mode (0-60 seconds). Set to 0 for no delay, negative values are ignored, values > 60 are clamped to 60, or omit to use system default",
        examples=[0, 2.5, 5.0, 10.0]
    )

    @field_validator("tear_delay_seconds")
    @classmethod
    def _clamp_delay(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        try:
            f = float(v)
        except Exception:
            return None
        if f < 0:
            return None
        if f > 60:
            f = 60.0
        return f if f > 0 else None


class JobSubmitRequest(BaseModel):
    """Request to submit a new print job with sections of tasks."""
    sections: List[Section] = Field(
        description="List of task sections to print. Each section groups related tasks under a category",
        min_length=1,
        examples=[[{"category": "Morning Tasks", "tasks": [{"text": "Make coffee", "flair_type": "emoji", "flair_value": "☕"}]}]]
    )
    options: Optional[Options] = Field(
        default=None,
        description="Optional print job configuration settings"
    )

    @field_validator("sections")
    @classmethod
    def _sections_rules(cls, v: List[Section], info: ValidationInfo) -> List[Section]:
        if not isinstance(v, list) or len(v) == 0:
            raise ValueError("sections must be a non-empty list")
        limits = (info.context or {}).get("limits", {})
        max_sections = int(limits.get("MAX_SECTIONS", 50))
        if len(v) > max_sections:
            raise ValueError(f"too many sections (max {max_sections})")
        return v


class Links(BaseModel):
    """Hypermedia links for API navigation."""
    self: str = Field(description="Link to this resource")
    job: str = Field(description="Link to the job status endpoint")


class JobAcceptedResponse(BaseModel):
    """Response when a print job is successfully accepted."""
    id: str = Field(description="Unique identifier for the submitted job")
    status: str = Field(description="Current job status", examples=["queued", "processing", "completed"])
    links: Links = Field(description="Related resource links")


# ----- Templates API Schemas -------------------------------------------------


class TemplateTaskMeta(BaseModel):
    """Metadata for template tasks with simplified structure."""
    priority: Optional[str] = Field(
        default=None,
        description="Task priority level (e.g., 'high', 'medium', 'low')",
        max_length=20,
        examples=["high", "medium", "low"]
    )
    assignee: Optional[str] = Field(
        default=None,
        description="Person assigned to complete this task",
        max_length=60,
        examples=["John Smith", "Team Lead", "jane@company.com"]
    )

    @field_validator("priority", "assignee")
    @classmethod
    def _trim(cls, v: Optional[str]) -> Optional[str]:
        return (v or "").strip() or None


class TemplateTask(BaseModel):
    """A task within a template with optional flair and metadata."""
    text: str = Field(
        description="The task description or action to be performed",
        min_length=1,
        examples=["Buy groceries", "Call dentist", "Review quarterly reports"]
    )
    flair_type: str = Field(
        default="none",
        description="Type of visual decoration. Options: 'none', 'icon', 'image', 'qr', 'barcode', 'emoji'",
        examples=["none", "icon", "emoji", "qr", "barcode", "image"]
    )
    flair_value: Optional[str] = Field(
        default=None,
        description="Content for the flair decoration. Required when flair_type is not 'none'",
        examples=["📝", "shopping_cart", "https://example.com", "TEXT_TO_ENCODE"]
    )
    flair_size: Optional[int] = Field(
        default=None,
        description="Optional size modifier for flair (1-100, where 100 is largest)",
        ge=1,
        le=100,
        examples=[25, 50, 75, 100]
    )
    metadata: Optional[TemplateTaskMeta] = Field(
        default=None,
        description="Additional task metadata like priority and assignee"
    )

    @field_validator("text")
    @classmethod
    def _text_rules(cls, v: str, info: ValidationInfo) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("task text required")
        limits = (info.context or {}).get("limits", {})
        max_len = int(limits.get("MAX_TASK_LEN", 200))
        if len(v) > max_len:
            raise ValueError(f"task too long (max {max_len})")
        if _has_control_chars(v):
            raise ValueError("control characters not allowed")
        return v

    @field_validator("flair_type")
    @classmethod
    def _flair_type_norm(cls, v: str) -> str:
        v = (v or "none").strip().lower()
        allowed = {"none", "icon", "image", "qr", "barcode", "emoji"}
        if v not in allowed:
            raise ValueError(f"invalid flair_type: {v}")
        return v

    @model_validator(mode="after")
    def _validate_flair(self) -> "TemplateTask":
        ft = self.flair_type
        fv = self.flair_value
        if ft in ("none",) or fv in (None, ""):
            return self
        if ft == "qr":
            s = str(fv)
            if _has_control_chars(s):
                raise ValueError("qr value invalid")
        elif ft in ("icon", "emoji", "barcode", "image"):
            s = str(fv).strip()
            if not s:
                raise ValueError(f"{ft} value required")
        return self


class TemplateSection(BaseModel):
    """A section within a template containing grouped tasks."""
    category: str = Field(
        description="Section title or category name that groups related tasks",
        min_length=1,
        examples=["Morning Routine", "Work Tasks", "Errands", "Shopping List"]
    )
    tasks: List[TemplateTask] = Field(
        description="List of template tasks belonging to this section",
        min_length=1
    )

    @field_validator("category")
    @classmethod
    def _category_rules(cls, v: str, info: ValidationInfo) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("category required")
        limits = (info.context or {}).get("limits", {})
        max_len = int(limits.get("MAX_CATEGORY_LEN", 100))
        if len(v) > max_len:
            raise ValueError(f"category too long (max {max_len})")
        if _has_control_chars(v):
            raise ValueError("control characters not allowed")
        return v

    @field_validator("tasks")
    @classmethod
    def _tasks_rules(cls, v: List[TemplateTask], info: ValidationInfo) -> List[TemplateTask]:
        if not isinstance(v, list) or len(v) == 0:
            raise ValueError("tasks must be a non-empty list")
        limits = (info.context or {}).get("limits", {})
        max_tasks = int(limits.get("MAX_TASKS_PER_SECTION", 50))
        if len(v) > max_tasks:
            raise ValueError(f"too many tasks (max {max_tasks})")
        return v


class TemplateCreateRequest(BaseModel):
    """Request to create a new reusable template."""
    name: str = Field(
        description="Unique name for the template",
        min_length=1,
        max_length=100,
        examples=["Daily Routine", "Weekly Shopping", "Project Checklist"]
    )
    notes: Optional[str] = Field(
        default=None,
        description="Optional notes or description about the template",
        max_length=500,
        examples=["My standard morning routine", "Shopping list template for weekly groceries"]
    )
    sections: List[TemplateSection] = Field(
        description="List of template sections containing grouped tasks",
        min_length=1
    )

    @field_validator("name")
    @classmethod
    def _name_rules(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("name required")
        if _has_control_chars(v):
            raise ValueError("control characters not allowed")
        return v

    @field_validator("sections")
    @classmethod
    def _sections_rules(cls, v: List[TemplateSection], info: ValidationInfo) -> List[TemplateSection]:
        if not isinstance(v, list) or len(v) == 0:
            raise ValueError("sections must be a non-empty list")
        limits = (info.context or {}).get("limits", {})
        max_sections = int(limits.get("MAX_SECTIONS", 50))
        if len(v) > max_sections:
            raise ValueError(f"too many sections (max {max_sections})")
        return v


class TemplateUpdateRequest(TemplateCreateRequest):
    pass


class TemplateListItem(BaseModel):
    """Summary information for a template in list views."""
    id: int = Field(description="Unique template identifier")
    name: str = Field(description="Template name")
    notes: Optional[str] = Field(default=None, description="Template notes or description")
    created_at: str = Field(description="ISO timestamp when template was created")
    updated_at: str = Field(description="ISO timestamp when template was last modified")
    last_used_at: Optional[str] = Field(default=None, description="ISO timestamp when template was last used for printing")
    sections_count: int = Field(description="Number of sections in this template", ge=0)
    tasks_count: int = Field(description="Total number of tasks across all sections", ge=0)


class TemplateTaskOut(BaseModel):
    """Template task information for detailed views."""
    id: Optional[int] = Field(default=None, description="Task database ID")
    text: str = Field(description="Task description")
    position: int = Field(description="Display order within the section", ge=0)
    flair_type: str = Field(description="Type of visual decoration")
    flair_value: Optional[str] = Field(default=None, description="Flair content")
    flair_size: Optional[int] = Field(default=None, description="Flair size modifier")
    metadata: Optional[TemplateTaskMeta] = Field(default=None, description="Task metadata")


class TemplateSectionOut(BaseModel):
    """Template section information for detailed views."""
    id: Optional[int] = Field(default=None, description="Section database ID")
    category: str = Field(description="Section category name")
    position: int = Field(description="Display order within the template", ge=0)
    tasks: List[TemplateTaskOut] = Field(description="Tasks in this section")


class TemplateResponse(BaseModel):
    """Complete template information."""
    id: int = Field(description="Unique template identifier")
    name: str = Field(description="Template name")
    notes: Optional[str] = Field(default=None, description="Template notes or description")
    created_at: str = Field(description="ISO timestamp when template was created")
    updated_at: str = Field(description="ISO timestamp when template was last modified")
    last_used_at: Optional[str] = Field(default=None, description="ISO timestamp when template was last used")
    sections: List[TemplateSectionOut] = Field(description="Template sections and tasks")


class TemplatePrintRequest(BaseModel):
    """Request to print from an existing template."""
    options: Optional[Options] = Field(
        default=None,
        description="Optional print configuration overrides. When absent, server uses template or system defaults"
    )


class TemplatePrintResponse(BaseModel):
    """Response when template print job is submitted."""
    job_id: str = Field(description="Unique identifier for the submitted print job")
