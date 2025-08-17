# Per-Print Tear-Off Mode (Delay Between Task Prints)

This document proposes and details an implementation to support a per-print “tear-off mode” in which the system delays between printing subsequent tasks and does not send a cut command. This accommodates printers that either don’t support auto-cut or for users who prefer manual tearing.

## Problem

Some ESC/POS printers don’t have cutters or have unreliable cut behavior. Today our worker always calls `cut()` after each task receipt. Users want to optionally disable cutting on a per-print basis and introduce a short delay between task receipts so they have time to tear off the paper manually.

## Goals

- Add a per-print option (not a universal config) to:
  - Disable cutting for the print job.
  - Introduce a delay of X seconds between task prints.
- Keep default behavior unchanged (prints + cuts as today) when the option is not used.
- Validate and clamp delay within safe bounds.
- Ensure request handlers stay fast (no sleeping in web routes).
- Maintain compatibility with current job flow and status pages.

## Non-goals

- Changing global configuration or saved printer settings.
- Persisting this option beyond a single print submission.
- Introducing any new persistence for job options in storage (in-memory job meta is sufficient).
- Adding a separate queue or worker concurrency model.

## UX changes (templates/index.html)

Add a small “Print Options” block above the “Print Tasks” button:

- Input:
  - Label: “Tear-off delay (seconds)”
  - Field: `name="tear_delay_seconds"`, `type="number"`, `min="0"`, `max="60"`, `step="0.5"`, placeholder “0 (disabled)”
  - Help text: “Wait this many seconds between tasks and do not cut.”
- Defaults to blank/0. If left blank or 0, behavior is unchanged.
- Keep it unobtrusive; no JS is required for dynamic sections.

Example layout (conceptual):
- Subtitle/task form (unchanged)
- New row:
  - [ Tear-off delay (seconds): (number input) ]
  - Help note below the field
- Print button remains as-is

## Web layer changes (task_printer/web/routes.py)

In `POST /` handler:

1. Parse `tear_delay_seconds` from `request.form`:
   - `raw = (form.get("tear_delay_seconds", "") or "").strip()`
   - If empty → `delay = 0.0`
   - Else convert to float; if conversion fails, flash error and redirect back.
   - Clamp to [0, 60] (both inclusive). Optionally flash a warning if clamped.
2. If `delay > 0`, create `options = {"tear_delay_seconds": delay}` else `options = None`.
3. Pass `options` to the queue via the enqueue call (see Worker API changes).
4. Flash success: optionally include a note like “Tear-off mode enabled: waiting Xs (no cut).”

Validation:
- Negative values are treated as 0 (or rejected).
- Values > 60 are clamped to 60.
- Decimal values are allowed (step 0.5).

## Worker API changes (task_printer/printing/worker.py)

Extend the worker to accept per-job options and adjust behavior accordingly.

### Public queue API

- `enqueue_tasks(subtitle_tasks, options: Optional[Mapping[str, Any]] = None) -> str`
  - Store an abbreviated meta entry on the job (e.g., `delay_seconds` if provided).
  - Put `options` on the queue payload: `{"type": "tasks", "payload": payload, "options": options, "job_id": job_id}`.

- `print_tasks(subtitle_tasks, options: Optional[Mapping[str, Any]] = None) -> bool`
  - Interpret options:
    - `delay = float(options.get("tear_delay_seconds", 0)) if options else 0.0`
    - `tear_mode = delay > 0`
  - Connect to the printer (unchanged).
  - Iterate items with an index and total count:
    - Call `_print_subtitle_task_item(p, i, item, config, cut=not tear_mode)`
    - If `tear_mode` and not last item: `time.sleep(delay)`

- `_print_worker()`:
  - When handling `"tasks"` jobs, pass `options` through to `print_tasks(...)`.

### Single-item print adjustment

- Update `_print_subtitle_task_item(p, idx, item, config, cut: bool = True)`:
  - Existing behavior unchanged when `cut=True`.
  - When `cut=False`:
    - Keep existing spacing behavior (write blank lines before cut feed) as these lines help tearing.
    - Do NOT call `p.cut()`.

Note:
- Spacing in tear-off mode can be tuned separately via the global `tear_feed_lines` config. If unset, it falls back to `cut_feed_lines`. Increase `tear_feed_lines` to compensate for the cutter's built-in pre-feed so spacing matches between modes.

### Logging

- When `tear_mode` is enabled, log at INFO:
  - “Tear-off mode enabled: delay=<X>s; cut disabled”
- Between tasks, log at DEBUG or INFO:
  - “Sleeping <X>s before next task (#i -> #i+1)”
- Retain all existing job lifecycle logs.

## Data contracts

- Web → Worker enqueue:
  - Job payload includes: `payload` (subtitle/tasks), optional `options` dict with `tear_delay_seconds`.
- Worker job meta:
  - May include a summary like `{"delay_seconds": X}` for list views or debugging.
- Defaults:
  - No `options` or `{tear_delay_seconds: 0}` means no behavioral change.

## Validation and limits

- `0 ≤ tear_delay_seconds ≤ 60`
- Decimal allowed (0.5 step recommended).
- Treat invalid input as 0 or reject (prefer clamping to be user-friendly).

## Edge cases and safety

- Printers without cutters: tear-off mode avoids calling `cut()` which can prevent driver errors on some implementations.
- Very large delays: capped to 60s to keep the worker from appearing “hung.”
- Single-task jobs: no sleep is performed even in tear-off mode (no next task).
- Exceptions during cut (when not in tear-mode): current implementation already calls `p.cut()` and logs; this change does not alter that path for default behavior.

## Testing

Add tests under `tests/`:

1. Unit tests for worker orchestration:
   - Given `options={"tear_delay_seconds": 3}`, verify `_print_subtitle_task_item` is called with `cut=False` and `time.sleep` is called `len(tasks) - 1` times with 3.
   - Given `options=None` or `0`, verify `cut=True` and `sleep` is never called.

2. Web route parsing:
   - POST to `/` with form values + `tear_delay_seconds=2.5`.
   - Verify a job is created (via redirect banner or by introspecting the job store if accessible) and that the worker receives the `options` (can assert via log capture or a small hook if you expose job meta).

3. Bounds and invalid input:
   - Negative value → treated as 0 (or rejected).
   - > 60 → clamped to 60.

Use `create_app(register_worker=False)` and mock worker functions for fast, isolated tests where needed.

## Rollout plan

- Implement and land behind minimal UI change on `/` page.
- Setup: add an optional global default `default_tear_delay_seconds` persisted in `config.json`.
- Templates: when printing directly from the Templates page, use the global default if set.
- Test print continues to cut by default (no change).
- Default behavior remains unchanged for users who do not supply a delay.
- Update docs (`AGENTS.md`, README) to mention the per‑print option and the global default.

## Implementation checklist

Frontend:
- [x] Add “Tear-off delay (seconds)” number input to `templates/index.html` near the submit button (preloaded from config when available).

Web (routes):
- [x] Parse and validate `tear_delay_seconds` in `POST /`.
- [x] Add `options` dict on enqueue when `delay > 0`.
- [x] Setup: parse/save `default_tear_delay_seconds` and preload into Index.

Worker:
- [x] Update `enqueue_tasks(...)` to accept `options` and place on queue payload; store brief meta on job.
- [x] Update `_print_worker()` to pass `options` to `print_tasks(...)`.
- [x] Update `print_tasks(...)` to compute `tear_mode` from options, suppress cuts, and sleep between tasks.
- [x] Update `_print_subtitle_task_item(...)` to accept `cut: bool = True` and skip `p.cut()` when false.

Observability:
- [x] Add informative logs for tear-off mode and sleeps.

Tests:
- [x] Add unit tests for worker and route parsing as described.
- [x] Add tests for Setup saving and Index/Template defaults behavior.

Docs:
- [x] Merge this file and note the new option in `AGENTS.md` “Routes (now implemented as blueprints)” → “GET/POST /” section and “Coding guidelines” if relevant.
- [x] README updated: feature bullet, usage, configuration key.

## Future enhancements

- A separate checkbox “Disable cut for this print” to decouple cut from delay (could enable “no cut, no delay”).
- Per-job override for “tear feed lines” distinct from the global `tear_feed_lines` (future).
- Persist and remember last-used delay per client (localStorage) for convenience.
- Surface job options (e.g., `tear_delay_seconds`) in the `/jobs` UI.

## Definition of Done

- When `tear_delay_seconds` is blank or 0, printing behaves exactly as before (including cut).
- When `tear_delay_seconds` > 0:
  - No cut commands are sent between tasks.
  - The worker sleeps `X` seconds between tasks (not after the last one).
- Optional global default `default_tear_delay_seconds` can be set in Setup; Templates honor it and Index preloads it.
- The UI remains simple and unobtrusive; default behavior is unchanged.
- Tests cover worker orchestration, form parsing boundaries, and default handling.
- Logs clearly indicate tear-off mode and timing.
