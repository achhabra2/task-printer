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
    assigned: Optional[str] = Field(default=None)
    due: Optional[str] = Field(default=None)
    priority: Optional[str] = Field(default=None)
    assignee: Optional[str] = Field(default=None)

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
    text: str
    flair_type: str = Field(default="none")  # none|icon|image|qr|emoji
    flair_value: Optional[str] = Field(default=None)
    metadata: Optional[Metadata] = Field(default=None)

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
    category: str
    tasks: List[Task]

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
    tear_delay_seconds: Optional[float] = Field(default=None)

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
    sections: List[Section]
    options: Optional[Options] = Field(default=None)

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
    self: str
    job: str


class JobAcceptedResponse(BaseModel):
    id: str
    status: str
    links: Links


# ----- Templates API Schemas -------------------------------------------------


class TemplateTaskMeta(BaseModel):
    priority: Optional[str] = None
    assignee: Optional[str] = None

    @field_validator("priority", "assignee")
    @classmethod
    def _trim(cls, v: Optional[str]) -> Optional[str]:
        return (v or "").strip() or None


class TemplateTask(BaseModel):
    text: str
    flair_type: str = Field(default="none")  # none|icon|image|qr|barcode|emoji
    flair_value: Optional[str] = None
    flair_size: Optional[int] = None
    metadata: Optional[TemplateTaskMeta] = None

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
    category: str
    tasks: List[TemplateTask]

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
    name: str
    notes: Optional[str] = None
    sections: List[TemplateSection]

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
    id: int
    name: str
    notes: Optional[str] = None
    created_at: str
    updated_at: str
    last_used_at: Optional[str] = None
    sections_count: int
    tasks_count: int


class TemplateTaskOut(BaseModel):
    id: Optional[int] = None
    text: str
    position: int
    flair_type: str
    flair_value: Optional[str] = None
    flair_size: Optional[int] = None
    metadata: Optional[TemplateTaskMeta] = None


class TemplateSectionOut(BaseModel):
    id: Optional[int] = None
    category: str
    position: int
    tasks: List[TemplateTaskOut]


class TemplateResponse(BaseModel):
    id: int
    name: str
    notes: Optional[str] = None
    created_at: str
    updated_at: str
    last_used_at: Optional[str] = None
    sections: List[TemplateSectionOut]


class TemplatePrintRequest(BaseModel):
    # Optional override for tear-off delay; when absent, server may use config default.
    options: Optional[Options] = None


class TemplatePrintResponse(BaseModel):
    job_id: str
