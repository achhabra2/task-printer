# Task Printer — Proposed Improvements

This document outlines potential future improvements, grouped by impact and area.

## High-Impact / Next Steps

- CSRF protection: Add Flask-WTF and CSRF tokens for `/`, `/setup`, and `/restart`.
- Error handling UX: Clear error banners with actionable steps (permissions, cable, IP, groups).

## Reliability & Printer Handling

- Receipt width configuration: Let users choose 58mm/80mm or pixel width; avoid device-ID heuristics.
- Subtitle rendering: Render subtitles as images (like tasks) for consistent typography and code-page independence.
- Timeouts/retries: Wrap print calls with timeouts, limited retries, and device reconnects.
- `lsusb` fallback: If not available, attempt `pyusb` enumeration; otherwise show a helpful message.
- Health endpoint: Add `/healthz` to confirm app readiness; include simple checks (config present, worker alive).

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
