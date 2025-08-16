#!/usr/bin/env python3
"""
Task Printer — Flask bootstrap

This thin module delegates to the Task Printer package's application factory.
It preserves the previous default host/port and logs friendly startup messages.
"""

import os

from task_printer import create_app


def _get_port() -> int:
    """
    Determine the port to bind the server to.
    Defaults to 5001 (matching previous behavior), but honors TASKPRINTER_PORT or PORT if set.
    """
    val = os.environ.get("TASKPRINTER_PORT") or os.environ.get("PORT") or "5001"
    try:
        return int(val)
    except ValueError:
        return 5001


app = create_app()


if __name__ == "__main__":
    host = os.environ.get("TASKPRINTER_HOST", "0.0.0.0")
    port = _get_port()

    app.logger.info(f"Starting Task Printer on http://{host}:{port}")
    app.logger.info(f"Access from local network: http://[raspberry-pi-ip]:{port}")
    app.logger.info("Press Ctrl+C to stop the server")

    # The app factory already attempts to start the worker, but ensure it's running just in case.
    try:
        from task_printer.printing.worker import ensure_worker

        ensure_worker()
    except Exception:
        # Optional; non-fatal if worker cannot be ensured here.
        pass

    app.run(host=host, port=port, debug=False)
