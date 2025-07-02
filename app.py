#!/usr/bin/env python3
"""
Task Printer - Flask web app for printing daily tasks
Runs on Raspberry Pi with thermal printer support
"""

from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime
from escpos.printer import Usb
import os
from PIL import Image, ImageDraw, ImageFont
import json
import subprocess

app = Flask(__name__)
app.secret_key = 'taskprinter_secret_key_2024'  # Required for flash messages

CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'config.json')

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return None

def save_config(data):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(data, f, indent=2)

# On every request, check for config.json
from flask import g
@app.before_request
def check_config():
    if not request.path.startswith('/setup'):
        config = load_config()
        if not config:
            return redirect(url_for('setup'))
        g.config = config

def get_usb_devices():
    try:
        output = subprocess.check_output(['lsusb']).decode()
        devices = []
        for line in output.strip().split('\n'):
            parts = line.split()
            if 'ID' in parts:
                idx = parts.index('ID')
                id_pair = parts[idx+1]
                vendor, product = id_pair.split(':')
                desc = ' '.join(parts[idx+2:])
                is_printer = any(x in desc.lower() for x in ['epson', 'printer', 'star', 'citizen', 'bixolon', 'seiko'])
                devices.append({
                    'vendor': vendor,
                    'product': product,
                    'desc': desc,
                    'is_printer': is_printer
                })
        return devices
    except Exception as e:
        return []

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    usb_devices = get_usb_devices()
    auto_startup_result = None
    show_close = os.path.exists(CONFIG_PATH)
    if request.method == 'POST':
        printer_type = request.form.get('printer_type', 'usb')
        if printer_type == 'usb':
            selected_usb = request.form.get('usb_device', '')
            if selected_usb and selected_usb != 'manual':
                usb_vendor_id, usb_product_id = selected_usb.split(':')
            else:
                usb_vendor_id = request.form.get('usb_vendor_id', '0x04b8')
                usb_product_id = request.form.get('usb_product_id', '0x0e28')
        else:
            usb_vendor_id = request.form.get('usb_vendor_id', '0x04b8')
            usb_product_id = request.form.get('usb_product_id', '0x0e28')
        network_ip = request.form.get('network_ip', '')
        network_port = request.form.get('network_port', '9100')
        serial_port = request.form.get('serial_port', '')
        serial_baudrate = request.form.get('serial_baudrate', '19200')
        receipt_width = 512
        task_font_size = 72
        if printer_type == 'usb':
            if usb_vendor_id.lower() == '0x04b8':
                if usb_product_id.lower() in ['0x0e28', '0x0202', '0x020a', '0x0e15', '0x0e03']:
                    receipt_width = 512
                else:
                    receipt_width = 576
        if receipt_width >= 576:
            task_font_size = 90
        elif receipt_width >= 512:
            task_font_size = 72
        else:
            task_font_size = 60
        config = {
            'printer_type': printer_type,
            'usb_vendor_id': usb_vendor_id,
            'usb_product_id': usb_product_id,
            'network_ip': network_ip,
            'network_port': network_port,
            'serial_port': serial_port,
            'serial_baudrate': serial_baudrate,
            'receipt_width': receipt_width,
            'task_font_size': task_font_size,
        }
        save_config(config)
        auto_startup = request.form.get('auto_startup') == 'on'
        return render_template('loading.html', auto_startup=auto_startup)
    # Render setup page (for GET requests)
    show_close = os.path.exists(CONFIG_PATH)
    return render_template('setup.html', usb_devices=usb_devices, show_close=show_close)

@app.route('/restart', methods=['POST'])
def restart():
    data = request.get_json(force=True)
    auto_startup = data.get('auto_startup', False)
    if auto_startup:
        try:
            subprocess.run(['bash', './install_service.sh'], capture_output=True, text=True, timeout=30)
        except Exception as e:
            pass
    # Restart the app (systemd will restart it)
    import sys
    os.execv(sys.executable, [sys.executable] + sys.argv)
    return '', 204

def print_tasks(subtitle_tasks):
    config = load_config()
    if config is None:
        raise RuntimeError("No config found. Please complete setup at /setup.")
    print(f"Starting print job for {len(subtitle_tasks)} tasks (subtitle/task pairs)...")
    try:
        print("Attempting to connect to printer...")
        p = None
        if config['printer_type'] == 'usb':
            p = Usb(int(config['usb_vendor_id'], 16), int(config['usb_product_id'], 16))
        elif config['printer_type'] == 'network':
            from escpos.printer import Network
            p = Network(config['network_ip'], int(config['network_port']))
        elif config['printer_type'] == 'serial':
            from escpos.printer import Serial
            p = Serial(config['serial_port'], baudrate=int(config['serial_baudrate']))
        else:
            raise Exception('Unsupported printer type')
        print("✓ Printer connection established")
        for i, (subtitle, task) in enumerate(subtitle_tasks, 1):
            if not task.strip():
                continue
            print(f"Printing receipt for task {i}: {task.strip()} (Subtitle: {subtitle})")
            p.text("\n\n")
            p.set(align='left', bold=False, width=1, height=1)
            p.text("------------------------------------------------\n")
            if subtitle:
                p.set(align='left', bold=False, width=1, height=1)
                p.text(f"{subtitle}\n")
            img = render_large_text_image(task.strip(), config)
            p.image(img)
            p.set(align='left', bold=False, width=1, height=1)
            p.text("------------------------------------------------\n")
            p.text("\n\n")
            p.cut()
            print(f"✓ Printed and cut receipt for task {i}")
        p.close()
        print("✓ Printer connection closed")
        print("✓ All tasks printed as separate receipts successfully")
        return True
    except Exception as e:
        print(f"❌ Printer error: {str(e)}")
        print(f"❌ Error type: {type(e).__name__}")
        import traceback
        print(f"❌ Full traceback:")
        traceback.print_exc()
        return False

def render_large_text_image(text, config=None):
    if config is None:
        config = load_config()
    if config is None:
        raise RuntimeError("No config found. Please complete setup at /setup.")
    width = int(config.get('receipt_width', 512))
    font_size = int(config.get('task_font_size', 72))
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font = ImageFont.truetype(font_path, font_size)
    def wrap_text(text, font, max_width):
        words = text.split()
        lines = []
        current_line = ''
        for word in words:
            test_line = current_line + (' ' if current_line else '') + word
            bbox = font.getbbox(test_line)
            w = bbox[2] - bbox[0]
            if w <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        return lines
    extra_spacing = 10
    lines = wrap_text(text, font, width - 20)
    bbox = font.getbbox('A')
    line_height = bbox[3] - bbox[1]
    img_height = 40 + (line_height + extra_spacing) * len(lines)
    img = Image.new("L", (int(width), int(img_height)), 255)
    draw = ImageDraw.Draw(img)
    y = 20
    for line in lines:
        draw.text((10, y), line, font=font, fill=0)
        y += line_height + extra_spacing
    return img

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Parse all subtitle/task groups from the form
        subtitle_tasks = []
        form = request.form
        section = 1
        while True:
            subtitle_key = f'subtitle_{section}'
            subtitle = form.get(subtitle_key, '').strip()
            if not subtitle and section == 1:
                # If the first section is empty, treat as no input
                break
            if not subtitle:
                # No more sections
                break
            # Find all tasks for this section
            task_num = 1
            while True:
                task_key = f'task_{section}_{task_num}'
                task = form.get(task_key, '').strip()
                if not task:
                    break
                subtitle_tasks.append((subtitle, task))
                task_num += 1
            section += 1
        if not subtitle_tasks:
            flash('Please enter at least one task.', 'error')
            return redirect(url_for('index'))
        try:
            if print_tasks(subtitle_tasks):
                flash(f'{len(subtitle_tasks)} tasks sent to printer successfully!', 'success')
            else:
                flash('Error: Could not print tasks. Check printer connection.', 'error')
        except Exception as e:
            flash(f'Error printing tasks: {str(e)}', 'error')
        return redirect(url_for('index'))
    return render_template('index.html')

if __name__ == '__main__':
    print("Starting Task Printer on http://0.0.0.0:5000")
    print("Access from local network: http://[raspberry-pi-ip]:5000")
    print("Press Ctrl+C to stop the server")
    app.run(host='0.0.0.0', port=5000, debug=False) 