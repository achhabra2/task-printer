# Task Printer

A simple, user-friendly Flask web app for Raspberry Pi that lets you enter tasks via a web interface and prints each task on a USB, network, or serial-connected receipt printer (e.g., Epson TM-T20III). Designed for easy setup and use by anyone.

Recent frontend refactor: the dynamic form UI is now driven by small Jinja form macros and a single static JS module. Form submissions include a compact JSON payload (plus multipart files) to make the backend simpler and more reliable.

**Inspired by and functionally based on [Laurie Hérault's article: "A receipt printer cured my procrastination"](https://www.laurieherault.com/articles/a-thermal-receipt-printer-cured-my-procrastination). Their code was not public, so this open-source version was created for the community.**

## Features
- Web interface for entering and organizing tasks
- Each task prints as a separate receipt with clear formatting
- Supports USB, network, and serial receipt printers (via python-escpos)
- **JWT-based authentication** for MCP (Model Context Protocol) server access
- **MCP server integration** for AI assistant access to task printing capabilities
- Dynamic task and category sections
  - Per‑print tear‑off mode (optional delay between tasks, no cut)
 - Templates: save, load, edit, duplicate, delete, and print reusable task sets
- Frontend powered by:
  - Jinja form macros for reusable UI (icon picker, flair row, task row)
  - A single static module `static/js/app.js` for add/remove rows, flair toggles, job polling, image preview, save-as-template, and prefill
  - Cleaner form submission: a hidden `payload_json` field carries sections/tasks as JSON; image files stay in the multipart body and are referenced by field name
- Dark mode and responsive design
- Easy first-run setup and reconfiguration via web UI
- Systemd service for auto-start on boot
- Works for any user and install location

## Requirements
- Raspberry Pi (or any Linux system)
- Python 3.7+
- A compatible receipt printer (USB, network, or serial)
- [requirements.txt](./requirements.txt) dependencies:
  - Flask
  - python-escpos
  - Pillow
  - pyusb
  - FastMCP (for MCP server functionality)
  - PyJWT (for authentication)

## Installation
1. **Clone the repository:**
   ```bash
   git clone https://github.com/belu1357/task-printer.git
   cd task-printer
   ```
2. **Install Python dependencies system-wide:**
   ```bash
  sudo pip3 install -r requirements.txt
  ```
  - Fedora helper: `./scripts/setup_fedora.sh --yes` will install system packages (including emoji fonts) and set up a venv with requirements.
3. **Plug in your receipt printer:**
   - For USB: Connect the printer to your Raspberry Pi via USB.
   - For network: Ensure the printer is on the same network and you know its IP address.
   - For serial: Connect the serial cable and note the port (e.g., /dev/ttyUSB0).
4. **(Optional) Add your user to the printer group for USB access:**
   ```bash
   sudo usermod -aG lp $(whoami)
   # or, for some printers:
   sudo usermod -aG plugdev $(whoami)
   ```
   Then reboot or log out/in.

## Running the App

### Web Interface
1. **Start the web app:**
   ```bash
   # quickest
   python3 app.py
   # or use the helper which can leverage uv/venv if configured
   ./start.sh
   ```
2. **Access the web interface:**
   - On the Pi: [http://localhost:5000](http://localhost:5000)
   - On your network: http://(raspberry-pi-ip):5000

### MCP Server (for AI Assistants)
The TaskPrinter includes a Model Context Protocol (MCP) server that allows AI assistants to access task printing capabilities.

1. **Generate an authentication token:**
   ```bash
   uv run python scripts/generate_token.py
   ```

2. **Start the MCP server:**
   ```bash
   uv run python mcp_server.py
   ```
   
   The server will start on `http://localhost:8000/mcp` with JWT authentication enabled.

3. **Use with MCP clients:**
   - Include the JWT token in the `Authorization: Bearer <token>` header
   - The server provides tools for job submission, template management, and health checks
   - See [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md) for detailed setup and usage

4. **Available MCP capabilities:**
   - **Tools**: `submit_job`, `get_job_status`, `list_templates`, `create_template`, `print_template`, `get_health_status`, `test_print`
   - **Resources**: `config`, `health`, `templates`, `jobs/recent`
   - **Prompts**: `create_task_list`, `optimize_for_printing`, `template_from_description`, `print_job_assistant`, `troubleshooting_guide`

## First-Time Setup
- On first run, you'll be guided through a web-based setup page to select your printer type, connection, and preferences.
- The app auto-detects USB printers and helps you enter network/serial details if needed.
- You can always revisit the setup page via the ⚙️ Settings button.

## Using the Web Interface
- Add tasks and optional subtitles using the dynamic form.
- Click **Print Tasks** to print each task as a separate receipt.
 - Optional: set a “Tear‑off delay (seconds)” to wait between tasks and disable cutting for that print. Leave blank/0 for default behavior.
- Use the ⚙️ **Settings** button to reconfigure your printer or preferences at any time.
 - Toggle dark mode for easier viewing.
 - Check recent print jobs and status via the **🧾 Jobs** page.

### Task Metadata (optional)
- Click the small “Details” toggle under a task to reveal fields:
  - Assigned date, Due date, Priority (Normal/High/Urgent), Assignee
- These print below the task as a compact panel (grayscale) so they don’t affect the main text/flair layout.
- JSON payloads can set per-task `metadata` directly (see below).
- Date picker & helpers:
  - Assigned/Due are date inputs. They are blank by default; use the quick buttons if you want to set them.
  - Quick buttons: Today, +1d, +1w, +1m for fast Due adjustments.
  - Server-side validation accepts YYYY-MM-DD, MM-DD, or MM/DD and checks ranges.

## Health Check

- The endpoint `GET /healthz` returns JSON with app and printer status (worker started/alive, queue size, config presence, and basic printer reachability).

## Auto-Start on Boot (systemd)
1. **Install the systemd service:**
   ```bash
   sudo ./install_service.sh
   ```
   This script will auto-detect your user and install location—no editing required.
2. **Check the service status:**
   ```bash
   sudo systemctl status taskprinter.service
   ```
3. **View logs:**
   ```bash
   journalctl -u taskprinter.service -f
   ```

## Troubleshooting
- **Printer not found:**
  - For USB, ensure your user is in the correct group (`lp` or `plugdev`).
  - For network, double-check the IP and port.
  - For serial, verify the port and baudrate.
- **Permissions:**
  - If you see permission errors, try rebooting after adding your user to the printer group.
- **Service not starting:**
  - Check logs with `journalctl -u taskprinter.service -f`.
- **Web UI not loading:**
  - Ensure Python dependencies are installed and the service is running.

## Contributing
Pull requests and issues are welcome! See the [GitHub repo](https://github.com/belu1357/task-printer.git) for more info.

## License
GPL License. See [LICENSE](LICENSE) for details.

## Project Structure

```
task-printer/
├── app.py                      # Main runner that imports create_app()
├── task_printer/               # Application package
│   ├── __init__.py             # App factory (create_app)
│   ├── core/                   # Core helpers (config, assets, logging, db)
│   ├── printing/               # Rendering + background worker
│   └── web/                    # Blueprints (routes, setup, jobs, templates)
├── templates/                  # Jinja templates (repo root for easy edits)
│   ├── _components.html        # UI macros (buttons, cards, flashes, etc.)
│   ├── _form_macros.html       # Form macros (icon picker, flair row, task row)
│   ├── base.html               # Base layout (loads Tailwind + static/js/app.js)
│   ├── index.html              # Main UI (uses form macros)
│   ├── templates.html          # Templates list (Load, Edit, Print, Duplicate, Delete)
│   └── template_edit.html      # Edit a saved template
├── static/
│   ├── styles/app.css          # Minimal styling and tokens
│   ├── js/app.js               # Frontend module (add/remove rows, prefill, JSON payload)
│   └── icons/*.png             # Built-in flair icons
├── docs/
│   ├── IMPLEMENTED.md          # Implemented changes and usage
│   ├── IMPROVEMENTS.md         # Proposed improvements / roadmap
│   ├── DEPLOYMENT.md           # Systemd, uv/venv, Docker
│   └── PERSISTENCE.md          # Phase 3: SQLite templates design
├── README.md                   # This file
└── requirements.txt            # Python dependencies
```

## Stopping the Application

Press `Ctrl+C` in the terminal where the application is running. 

## Configuration

### Authentication (MCP Server)
- **JWT Authentication**: The MCP server uses JWT tokens for secure access
- **Token Generation**: Use `uv run python scripts/generate_token.py` to create new tokens
- **Token Storage**: Secrets are automatically stored in `~/.taskprinter/jwt_secret`
- **Disable Authentication**: Set `TASKPRINTER_AUTH_ENABLED=false` to disable
- **Token Expiration**: Tokens expire after 30 days by default

### Environment Variables
- `TASKPRINTER_MCP_HOST`: MCP server host (default: localhost)
- `TASKPRINTER_MCP_PORT`: MCP server port (default: 8000) 
- `TASKPRINTER_MCP_ENABLED`: Enable MCP server (default: true)
- `TASKPRINTER_AUTH_ENABLED`: Enable JWT authentication (default: true)
- `TASKPRINTER_JWT_SECRET`: JWT signing secret (auto-generated if not set)

### General Settings

- Global default tear‑off delay: set `default_tear_delay_seconds` in `config.json` (0–60). When set, template prints use this value by default and the Index page preloads it into the tear‑off input. Users can override it per print.
- Frontend JSON payload:
  - On submit, the index form adds a hidden input `payload_json` containing `{ sections: [...] }`, where each section has `category` and an array of `tasks`.
  - Each task may include flair: `{ flair_type: "none" | "icon" | "image" | "qr" | "emoji", flair_value: string | null }`.
  - Each task may include metadata: `{ metadata: { assigned?: string, due?: string, priority?: string, assignee?: string } }`.
    - Templates only keep `priority` and `assignee` when saved; dates are not stored.
  - For image flair, `flair_value` is the file input field name (e.g., `flair_image_2_3`); the actual file is sent in the multipart form under that name.
- Backend parsing:
  - The server now prefers `payload_json` and falls back to legacy dynamic field names (e.g., `task_1_2`) for backward compatibility.
  - Server-side validation enforces section/task limits, text/QR length, total character limits, and rejects control characters.
  - Emoji flair uses a monochrome emoji font for rasterization when configured.

### Emoji Rendering

- For reliable emoji on thermal printers, use a monochrome emoji font.
- Recommended fonts: Noto Emoji (monochrome), OpenMoji-Black, or Symbola.
- Set via either:
  - Config `emoji_font_path` (Setup page → Fonts), or
  - Env var `TASKPRINTER_EMOJI_FONT_PATH`.
- If no emoji font is provided, the app attempts to auto-detect common paths. A basic substitution (e.g., ✅ → ✔) is applied for popular symbols to improve out-of-the-box results, but a proper font is preferred.
- Recent emoji:
  - When choosing flair type “Emoji”, a small “Recent…” dropdown appears next to the input.
  - It caches your 12 most recent emoji selections in localStorage for quick reuse.

## Docs

- **Authentication Setup**: `docs/AUTHENTICATION.md` (JWT authentication for MCP server)
- Implemented changes and how to use them: `docs/IMPLEMENTED.md` (includes the macros/JS/payload_json refactor)
- Proposed improvements and roadmap: `docs/IMPROVEMENTS.md`
- Deployment (systemd hardening, uv/venv, Docker): `docs/DEPLOYMENT.md`

## HTTP API (v1)

- Submit a print job:
  - POST `/api/v1/jobs` with `Content-Type: application/json`
  - Body:
    ```json
    {
      "sections": [
        {"category": "Kitchen", "tasks": [
          {"text": "Wipe counter", "flair_type": "icon", "flair_value": "cleaning"}
        ]},
        {"category": "Hall", "tasks": [
          {"text": "Check mail", "flair_type": "qr", "flair_value": "OPEN:MAIL"}
        ]}
      ],
      "options": {"tear_delay_seconds": 2.5}
    }
    ```
  - Response: `202 Accepted` with JSON `{ id, status: "queued", links: { self, job } }` and `Location` header to `/api/v1/jobs/{id}`.
- Get job status:
  - GET `/api/v1/jobs/{id}` → JSON `{ id, status, ... }` or `404`.
- Notes:
  - Enforces the same limits as the web UI (max sections/tasks/chars; control chars rejected).
  - For `flair_type: "image"`, pass a server-local path to an image file (API does not accept multipart uploads).
  - When `options.tear_delay_seconds > 0`, the worker prints receipts without cutting and sleeps between tasks.
