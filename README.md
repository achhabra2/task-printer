# Task Printer

A simple, user-friendly Flask web app for Raspberry Pi that lets you enter tasks via a web interface and prints each task on a USB, network, or serial-connected receipt printer (e.g., Epson TM-T20III). Designed for easy setup and use by anyone.

**Inspired by and functionally based on [Laurie Hérault's article: "A receipt printer cured my procrastination"](https://www.laurieherault.com/articles/a-thermal-receipt-printer-cured-my-procrastination). Their code was not public, so this open-source version was created for the community.**

## Features
- Web interface for entering and organizing tasks
- Each task prints as a separate receipt with clear formatting
- Supports USB, network, and serial receipt printers (via python-escpos)
- Dynamic task and subtitle sections
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
1. **Start the app manually:**
   ```bash
   python3 app.py
   ```
2. **Access the web interface:**
   - On the Pi: [http://localhost:5000](http://localhost:5000)
   - On your network: [http://<raspberry-pi-ip>:5000](http://<raspberry-pi-ip>:5000)

## First-Time Setup
- On first run, you'll be guided through a web-based setup page to select your printer type, connection, and preferences.
- The app auto-detects USB printers and helps you enter network/serial details if needed.
- You can always revisit the setup page via the ⚙️ Settings button.

## Using the Web Interface
- Add tasks and optional subtitles using the dynamic form.
- Click **Print Tasks** to print each task as a separate receipt.
- Use the ⚙️ **Settings** button to reconfigure your printer or preferences at any time.
- Toggle dark mode for easier viewing.

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
MIT License. See [LICENSE](LICENSE) for details.

## Project Structure

```
taskprinter/
├── app.py              # Main Flask application
├── templates/          # HTML templates
│   └── index.html     # Web interface
├── README.md          # This file
└── printout_*.txt     # Generated task files
```

## Stopping the Application

Press `Ctrl+C` in the terminal where the application is running. 