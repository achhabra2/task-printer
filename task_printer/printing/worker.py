"""
Background worker, job state, and print orchestration for Task Printer.

This module owns:
- A thread-backed job queue
- In-memory job registry with basic lifecycle (queued -> running -> success/error)
- Print orchestration against ESC/POS printers using python-escpos
- Public helpers to enqueue jobs and query their status

It is deliberately Flask-agnostic so it can be used from both web routes and
CLI contexts. Logging integrates with the application's configured logging.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import uuid
from collections.abc import Iterable, Mapping
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from task_printer.core.assets import resolve_icon_path
from task_printer.core.config import load_config
from task_printer.printing.render import render_large_text_image, render_task_with_flair_image, resolve_font

# Types
SubtitleTask = Union[
    Tuple[str, str],
    Mapping[str, Any],  # expects keys: "subtitle", "task", optional "flair"
]

# Globals
logger = logging.getLogger(__name__)

JOB_QUEUE: queue.Queue[Dict[str, Any]] = queue.Queue()
JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.RLock()
JOBS_MAX = int(os.environ.get("TASKPRINTER_JOBS_MAX", "200"))

WORKER_THREAD: Optional[threading.Thread] = None
WORKER_STARTED = False


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prune_jobs_if_needed() -> None:
    # Use a reentrant lock to avoid deadlock if called while already holding JOBS_LOCK.
    with JOBS_LOCK:
        if len(JOBS) <= JOBS_MAX:
            return
        try:
            oldest_id = sorted(JOBS.values(), key=lambda j: j.get("created_at", ""))[0]["id"]
            JOBS.pop(oldest_id, None)
        except Exception:
            # If anything goes wrong, fall back to a simple pop of an arbitrary item
            try:
                JOBS.pop(next(iter(JOBS)))
            except Exception:
                pass


def _create_job(kind: str, meta: Optional[Dict[str, Any]] = None) -> str:
    job_id = uuid.uuid4().hex
    now = _utc_now_iso()
    job = {
        "id": job_id,
        "type": kind,
        "status": "queued",
        "created_at": now,
        "updated_at": now,
    }
    if meta:
        job.update(meta)
    with JOBS_LOCK:
        _prune_jobs_if_needed()
        JOBS[job_id] = job
    return job_id


def _update_job(job_id: Optional[str], **updates: Any) -> None:
    if not job_id:
        return
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = _utc_now_iso()


def _generate_icon_placeholder(key: str, width: int):
    """
    Fallback placeholder image when a named icon is not found.
    Draws a circle with the first letter of the key in the center.
    """
    try:
        from PIL import Image as _Image
        from PIL import ImageDraw as _ImageDraw

        # Size proportional to receipt width, clamped to reasonable bounds
        size = min(192, max(96, width // 4))
        img = _Image.new("L", (size, size), 255)
        d = _ImageDraw.Draw(img)

        # Draw a circle
        r = size // 2 - 6
        center = (size // 2, size // 2)
        d.ellipse([center[0] - r, center[1] - r, center[0] + r, center[1] + r], outline=0, width=4)

        # Draw a letter
        letter = (str(key)[:1] or "?").upper()
        try:
            font = resolve_font({"font_path": None}, size // 2)
        except Exception:
            from PIL import ImageFont as _ImageFont

            font = _ImageFont.load_default()
        bbox = font.getbbox(letter)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        d.text((center[0] - tw // 2, center[1] - th // 2), letter, fill=0, font=font)
        return img
    except Exception as e:
        logger.debug(f"Icon placeholder generation failed: {e}")
        return None


def _connect_printer(config: Mapping[str, Any]):
    """
    Create and return an ESC/POS printer instance based on the provided config.
    Supports USB, Network, and Serial with optional 'printer_profile'.
    """
    profile = config.get("printer_profile") or None
    ptype = str(config.get("printer_type", "usb")).lower()

    if ptype == "usb":
        from escpos.printer import Usb

        vendor = int(str(config.get("usb_vendor_id", "0x04b8")), 16)
        product = int(str(config.get("usb_product_id", "0x0e28")), 16)
        if profile:
            return Usb(vendor, product, profile=profile)
        return Usb(vendor, product)
    if ptype == "network":
        from escpos.printer import Network

        ip = str(config.get("network_ip", ""))
        port = int(str(config.get("network_port", "9100")))
        if profile:
            return Network(ip, port, profile=profile)
        return Network(ip, port)
    if ptype == "serial":
        from escpos.printer import Serial

        port = str(config.get("serial_port", ""))
        baud = int(str(config.get("serial_baudrate", "19200")))
        if profile:
            return Serial(port, baudrate=baud, profile=profile)
        return Serial(port, baudrate=baud)
    raise RuntimeError(f"Unsupported printer type: {ptype}")


def _print_subtitle_task_item(
    p,
    idx: int,
    item: SubtitleTask,
    config: Mapping[str, Any],
    *,
    cut: bool = True,
) -> None:
    """
    Print a single subtitle/task item using the given printer instance.
    Handles optional flair (icon/image/qr), separators, and cutting lines.
    """
    # Normalize input
    if isinstance(item, (list, tuple)):
        subtitle, task = (item[0] or ""), (item[1] or "")
        flair = None
    else:
        subtitle = str(item.get("subtitle", "") or "")
        task = str(item.get("task", "") or "")
        flair = item.get("flair")

    if not task.strip():
        return

    logger.info(f"Printing receipt for task {idx}: {task.strip()} (Subtitle: {subtitle})")

    # Header/new lines
    p.text("\n\n")
    p.set(align="left", bold=False, width=1, height=1)

    # Optional separators
    if bool(config.get("print_separators", True)):
        p.text("------------------------------------------------\n")

    # Subtitle
    if subtitle:
        p.set(align="left", bold=False, width=1, height=1)
        p.text(f"{subtitle}\n")

    # Flair: icon/image/qr (compose with text when image/icon available)
    combined_img = None
    if isinstance(flair, Mapping):
        ftype = flair.get("type")
        fval = str(flair.get("value", "") or "")
        try:
            if ftype in ("icon", "image") and fval:
                flair_src = None
                if ftype == "icon":
                    icon_path = resolve_icon_path(fval)
                    if icon_path and os.path.exists(icon_path):
                        flair_src = icon_path
                    else:
                        img_ph = _generate_icon_placeholder(fval, int(config.get("receipt_width", 512)))
                        if img_ph is not None:
                            flair_src = img_ph
                elif os.path.isfile(fval):
                    flair_src = fval
                else:
                    logger.warning(f"Image not found for task {idx}: {fval}")
                if flair_src is not None:
                    combined_img = render_task_with_flair_image(task.strip(), flair_src, config)
            elif ftype == "qr" and fval:
                p.qr(fval)
        except Exception as e:
            logger.warning(f"Flair render failed for task {idx}: {e}")

    # Task text image (or combined with flair image/icon)
    if combined_img is not None:
        p.image(combined_img)
    else:
        img = render_large_text_image(task.strip(), config)
        p.image(img)

    p.set(align="left", bold=False, width=1, height=1)
    if bool(config.get("print_separators", True)):
        p.text("------------------------------------------------\n")

    # Extra blank lines before cutting, configurable
    try:
        extra = int(config.get("cut_feed_lines", 2))
    except Exception:
        extra = 2
    if extra > 0:
        p.text("\n" * extra)
    if cut:
        p.cut()
        logger.info(f"Printed and cut receipt for task {idx}")
    else:
        logger.info(f"Printed receipt for task {idx} (no cut; tear-off mode)")


def print_tasks(subtitle_tasks: Iterable[SubtitleTask], options: Optional[Mapping[str, Any]] = None) -> bool:
    """
    Print provided subtitle/task items using the saved config.
    Returns True on success, False on failure.
    """
    config = load_config()
    if config is None:
        raise RuntimeError("No config found. Please complete setup at /setup.")

    logger.info(
        f"Starting print job for {len(list(subtitle_tasks)) if hasattr(subtitle_tasks, '__len__') else 'n'} tasks...",
    )
    try:
        logger.info("Attempting to connect to printer...")
        p = _connect_printer(config)
        logger.info("Printer connection established")

        # Determine per-job options
        delay = 0.0
        if options is not None:
            try:
                delay = float(options.get("tear_delay_seconds", 0) or 0)
            except Exception:
                delay = 0.0
        tear_mode = delay > 0
        if tear_mode:
            logger.info("Tear-off mode enabled: delay=%.3fs; cut disabled", delay)

        items = list(subtitle_tasks)
        total = len(items)
        for i, item in enumerate(items, 1):
            _print_subtitle_task_item(p, i, item, config, cut=not tear_mode)
            # Sleep between items when in tear-off mode (not after the last)
            if tear_mode and i < total:
                logger.info("Sleeping %.3fs before next task (#%d -> #%d)", delay, i, i + 1)
                time.sleep(delay)

        try:
            p.close()
        except Exception:
            pass

        logger.info("Printer connection closed")
        logger.info("All tasks printed as separate receipts successfully")
        return True
    except Exception as e:
        logger.exception(f"Printer error: {e!s}")
        return False


def print_tasks_with_config(subtitle_tasks: Iterable[SubtitleTask], config: Mapping[str, Any]) -> bool:
    """
    Print using a provided config override (without saving it).
    Returns True on success, False on failure.
    """
    if config is None:
        return False
    try:
        logger.info("Starting print (override config)")
        p = _connect_printer(config)
        for i, item in enumerate(subtitle_tasks, 1):
            _print_subtitle_task_item(p, i, item, config, cut=True)
        try:
            p.close()
        except Exception:
            pass
        return True
    except Exception as e:
        logger.exception(f"Override-config print failed: {e}")
        return False


def _do_test_print(config_override: Optional[Mapping[str, Any]] = None) -> bool:
    """
    Perform a simple test print using either the saved config or an override.
    """
    cfg = config_override or load_config()
    if cfg is None:
        raise RuntimeError("No config found. Please complete setup at /setup.")
    from datetime import datetime as _dt

    pairs: List[SubtitleTask] = [
        ("TEST", "Task Printer Test Page"),
        (_dt.now().strftime("%Y-%m-%d %H:%M"), "Hello from Task Printer!"),
    ]
    return print_tasks_with_config(pairs, cfg)


def _print_worker() -> None:
    """
    Worker loop that processes queued jobs. Never raises; logs and updates job status.
    """
    while True:
        job = JOB_QUEUE.get()
        try:
            kind = job.get("type")
            job_id = job.get("job_id")
            _update_job(job_id, status="running")

            if kind == "tasks":
                payload = job.get("payload", [])
                opts = job.get("options")
                ok = print_tasks(payload, options=opts)
                _update_job(job_id, status="success" if ok else "error")
            elif kind == "test":
                cfg = job.get("config_override")
                ok = _do_test_print(cfg)
                _update_job(job_id, status="success" if ok else "error")
            else:
                logger.warning(f"Unknown job type: {kind}")
                _update_job(job_id, status="error", error="unknown_job_type")
        except Exception as e:
            logger.exception(f"Job failed: {e}")
            try:
                _update_job(job.get("job_id"), status="error", error=str(e))
            except Exception:
                pass
        finally:
            JOB_QUEUE.task_done()


def ensure_worker() -> None:
    """
    Ensure the background worker thread is started (idempotent).
    """
    global WORKER_THREAD, WORKER_STARTED
    if WORKER_STARTED and WORKER_THREAD and WORKER_THREAD.is_alive():
        return
    t = threading.Thread(target=_print_worker, daemon=True, name="task-printer-worker")
    t.start()
    WORKER_THREAD = t
    WORKER_STARTED = True
    logger.info("Background print worker started")


def enqueue_tasks(subtitle_tasks: Iterable[SubtitleTask], options: Optional[Mapping[str, Any]] = None) -> str:
    """
    Enqueue a 'tasks' job. Returns the job id.
    """
    # Evaluate len for metadata if possible without exhausting the iterator
    total = len(list(subtitle_tasks)) if hasattr(subtitle_tasks, "__len__") else None
    payload = list(subtitle_tasks)  # Ensure it's serializable and reusable in the worker
    # Brief meta for job list/debugging
    meta: Dict[str, Any] = {"total": len(payload) if total is None else total}
    try:
        if options and float(options.get("tear_delay_seconds", 0) or 0) > 0:
            meta["delay_seconds"] = float(options.get("tear_delay_seconds", 0))
    except Exception:
        pass
    job_id = _create_job("tasks", meta=meta)
    JOB_QUEUE.put({"type": "tasks", "payload": payload, "options": dict(options) if options else None, "job_id": job_id})
    return job_id


def enqueue_test_print(config_override: Optional[Mapping[str, Any]] = None, origin: Optional[str] = None) -> str:
    """
    Enqueue a 'test' job. Optionally provide a config override and origin metadata.
    """
    meta = {}
    if origin:
        meta["origin"] = origin
    job_id = _create_job("test", meta=meta or None)
    logger.info("enqueue_test_print: created job id=%s", job_id)
    JOB_QUEUE.put(
        {"type": "test", "job_id": job_id, "config_override": dict(config_override) if config_override else None},
    )
    logger.info("enqueue_test_print: enqueued job id=%s queue_size=%d", job_id, JOB_QUEUE.qsize())
    return job_id


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a job by id.
    """
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        return dict(job) if job else None


def list_jobs() -> List[Dict[str, Any]]:
    """
    Return a list of jobs sorted by created_at descending.
    """
    with JOBS_LOCK:
        items = [dict(v) for v in JOBS.values()]
    try:
        items.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    except Exception:
        pass
    return items


def worker_status() -> Dict[str, Any]:
    """
    Return basic worker/queue status.
    """
    alive = bool(WORKER_THREAD) and WORKER_THREAD.is_alive()  # type: ignore[truthy-function]
    return {
        "worker_started": WORKER_STARTED,
        "worker_alive": alive,
        "queue_size": JOB_QUEUE.qsize(),
    }


__all__ = [
    "JOBS",
    "JOBS_MAX",
    "JOB_QUEUE",
    "WORKER_STARTED",
    "WORKER_THREAD",
    "enqueue_tasks",
    "enqueue_test_print",
    "ensure_worker",
    "get_job",
    "list_jobs",
    "print_tasks",
    "print_tasks_with_config",
    "worker_status",
]
