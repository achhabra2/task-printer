# Task Printer — Proposed Improvements

This document outlines potential future improvements, grouped by impact and area.

## Recent Improvements (Implemented)

### Smart Font Sizing for Better Text Layout
- **Dynamic font adjustment**: When text would wrap by just 1-2 characters or split simple two-word phrases, the system now automatically reduces the font size slightly to fit the text on one line instead of wrapping.
- **Example**: "Mount Pegboard" and "Measure Pegboard" now render on single lines with slightly smaller fonts instead of wrapping to two lines.
- **Configuration**: Controlled by `enable_dynamic_font_sizing` (default: True), `max_overflow_chars_for_dynamic_sizing` (default: 3), and existing `min_font_size`/`max_font_size` settings.
- **Behavior**: Only affects text that would wrap into 2 lines with small overflow. Long text that genuinely needs multiple lines continues to wrap normally.
- **Benefits**: Cleaner appearance for short task names, better space utilization, maintains readability.

### Emoji Flair Rendering
- **New flair type**: `emoji` enables per-task emoji rendered alongside text, composed like icons/images.
- **Monochrome fonts**: Prefer and auto-detect monochrome emoji fonts (Noto Emoji, OpenMoji-Black, Symbola) for ESC/POS compatibility.
- **Setup integration**: Fonts section in Setup lets you specify `emoji_font_path`; auto-detects common paths if left blank.
- **Worker support**: End-to-end wiring so `{"type":"emoji","value":"✅"}` prints correctly.

### Health Endpoint + Badge
- **/healthz** now reports: worker status, queue size, printer reachability, and `emoji_ok` status.
- **UI badge**: A small health badge appears at the top of the Index page summarizing worker/printer/emoji.

### Fedora Setup
- **setup_fedora.sh**: Installs `google-noto-emoji-fonts` along with existing dependencies; still supports interactive/non-interactive modes.

## New: Templates (Saved task sets)
- We added a SQLite-backed Templates feature so you can save, list, load, edit, duplicate, delete, and print grouped tasks with optional flair (icon/image/QR).
- Where to find it:
  - Main page: "💾 Save as Template" button saves the current form (icon/QR flair included; image flair requires multipart form).
  - Templates page: "📚 Templates" lists saved templates with actions: Load (prefill main form), Print Now, Duplicate, Delete.
- Printing uses the existing background worker. Template prints appear in Jobs with normal status updates.
- Paths and configuration:
  - Database path: TASKPRINTER_DB_PATH (fallback to XDG data dir).
  - Media uploads (image flair) are stored under TASKPRINTER_MEDIA_PATH.
- API endpoints (HTML/JSON):
  - GET /templates (HTML by default; JSON when Accept: application/json without text/html, or ?format=json)
  - POST /templates (create), GET /templates/<id> (prefill JSON)
  - POST /templates/<id>/update, /duplicate, /delete, /print
- Limits and security: CSRF on all POSTs, server-side limits for sections, tasks, and lengths, and control-character rejection.
- See docs/IMPLEMENTED.md for the full breakdown.

## High-Impact / Next Steps

- CSRF protection: Add Flask-WTF and CSRF tokens for `/`, `/setup`, and `/restart`.
- Error handling UX: Clear error banners with actionable steps (permissions, cable, IP, groups).

## Reliability & Printer Handling

- Receipt width configuration: Let users choose 58mm/80mm or pixel width; avoid device-ID heuristics.
- Subtitle rendering: Render subtitles as images (like tasks) for consistent typography and code-page independence.
- Timeouts/retries: Wrap print calls with timeouts, limited retries, and device reconnects.
- `lsusb` fallback: If not available, attempt `pyusb` enumeration; otherwise show a helpful message.
- Health endpoint: `/healthz` implemented and extended with emoji rendering checks; surfaced in the UI.

## UX & Accessibility

- Client/server validation: Enforce non-empty tasks and reasonable length. Indicate failing fields.
- Dark mode via CSS variables: Replace ad-hoc selectors with `:root` variables for clean theme switching.
- Keyboard navigation and labels: Ensure `for` attributes and focus states are consistent; ARIA for flash messages.
- Presets/history: Save recent task sets; enable re-print and quick edit.
- Preview: Show a client-side preview approximating the printed output.

## DevOps & Packaging

- Systemd hardening: Consider `Restart=on-failure`, `NoNewPrivileges=true`, `ProtectSystem=full`, `DynamicUser=yes`.
- Virtualenv support: Allow service to run under a venv path; document venv install flow.
- Config locations: Consider `/var/lib/taskprinter/config.json` or XDG by default; keep env override.
- JSON logging enhancements: Optionally include more fields (duration, job_id) and add a log context helper.
- Containerization: Provide a Dockerfile; document USB passthrough and network printer constraints.

## Security

- CSRF (implemented) and method checks. Consider simple origin checks for `/restart`.
- Input limits: Cap total payload size and per-task length. Reject control characters.
- Session cookie flags: `SESSION_COOKIE_HTTPONLY=True`, optionally `SESSION_COOKIE_SECURE=True` behind TLS.

## Code Quality & Testing

- Module structure: Split `app.py` into `routes.py`, `printer.py`, `config.py`, and `queue.py`.
- Type hints and docstrings: Annotate public functions (`print_tasks`, `render_large_text_image`, queue helpers).
- Unit tests: Flask test client for routes and setup gating; mock `escpos` for printing; unit test word-wrap.
- Lint/format: Add pre-commit with `black`, `ruff`, and basic CI (GitHub Actions).

## Nice-to-Have Features

- Job queue UI: Show queued jobs and allow canceling pending ones.
- Multi-user presets: Named lists shared across users in the network.
- Internationalization: Unicode coverage and optional language packs; choose font family.

## Suggested Priorities

1. CSRF + validation + status endpoint
2. Receipt width config + improved printing robustness
3. Logging + health checks + systemd hardening
4. Preview + presets/history
5. Tests and CI
