#!/usr/bin/env python3
"""
Task Printer - Flask web app for printing daily tasks
Runs on Raspberry Pi with thermal printer support
"""

from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime, timezone
from escpos.printer import Usb
import os
from PIL import Image, ImageDraw, ImageFont
import json
import subprocess
import threading
import queue
from pathlib import Path
import logging
import uuid
from time import time, sleep
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf
from werkzeug.utils import secure_filename

app = Flask(__name__)
# Secret key from env, with safe dev fallback
app.secret_key = os.environ.get('TASKPRINTER_SECRET_KEY', 'taskprinter_dev_secret_key')

# Basic input and payload limits
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('TASKPRINTER_MAX_CONTENT_LENGTH', 1024 * 1024))  # 1MB default
MAX_SECTIONS = int(os.environ.get('TASKPRINTER_MAX_SECTIONS', 50))
MAX_TASKS_PER_SECTION = int(os.environ.get('TASKPRINTER_MAX_TASKS_PER_SECTION', 50))
MAX_TASK_LEN = int(os.environ.get('TASKPRINTER_MAX_TASK_LEN', 200))
MAX_SUBTITLE_LEN = int(os.environ.get('TASKPRINTER_MAX_SUBTITLE_LEN', 100))
MAX_TOTAL_CHARS = int(os.environ.get('TASKPRINTER_MAX_TOTAL_CHARS', 5000))
MAX_QR_LEN = int(os.environ.get('TASKPRINTER_MAX_QR_LEN', 512))
MAX_UPLOAD_SIZE = int(os.environ.get('TASKPRINTER_MAX_UPLOAD_SIZE', 5 * 1024 * 1024))

csrf = CSRFProtect(app)

# Config path resolution: env override -> XDG config -> legacy fallback
def _default_config_path():
    xdg = os.environ.get('XDG_CONFIG_HOME')
    if xdg:
        return os.path.join(xdg, 'taskprinter', 'config.json')
    home = str(Path.home())
    return os.path.join(home, '.config', 'taskprinter', 'config.json')

CONFIG_PATH = os.environ.get('TASKPRINTER_CONFIG_PATH', _default_config_path())

def _default_media_path():
    xdg = os.environ.get('XDG_DATA_HOME')
    if xdg:
        return os.path.join(xdg, 'taskprinter', 'media')
    home = str(Path.home())
    return os.path.join(home, '.local', 'share', 'taskprinter', 'media')

MEDIA_PATH = os.environ.get('TASKPRINTER_MEDIA_PATH', _default_media_path())
os.makedirs(MEDIA_PATH, exist_ok=True)

ICON_EXTS = ['.png', '.jpg', '.jpeg', '.gif', '.bmp']

def get_available_icons():
    icons_dir = os.path.join(os.path.dirname(__file__), 'static', 'icons')
    mapping = {}
    try:
        for fname in os.listdir(icons_dir):
            base, ext = os.path.splitext(fname)
            if ext.lower() in ICON_EXTS:
                # prefer png over others if multiple
                if base not in mapping or (os.path.splitext(mapping[base])[1].lower() != '.png' and ext.lower() == '.png'):
                    mapping[base] = fname
    except Exception:
        pass
    icons = []
    for base, fname in sorted(mapping.items()):
        icons.append({'name': base, 'filename': f"icons/{fname}"})
    return icons

def _resolve_icon_path(key: str):
    icons_dir = os.path.join(os.path.dirname(__file__), 'static', 'icons')
    for ext in ICON_EXTS:
        candidate = os.path.join(icons_dir, key + ext)
        if os.path.exists(candidate):
            return candidate
    return None

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return None

def save_config(data):
    cfg_dir = os.path.dirname(CONFIG_PATH)
    if cfg_dir and not os.path.exists(cfg_dir):
        os.makedirs(cfg_dir, exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(data, f, indent=2)

# Logging setup with request IDs and optional systemd journal integration
class RequestIdFilter(logging.Filter):
    def filter(self, record):
        try:
            from flask import has_request_context, g
            record.request_id = g.request_id if has_request_context() and hasattr(g, 'request_id') else '-'
            record.path = request.path if has_request_context() else '-'
        except Exception:
            record.request_id = '-'
            record.path = '-'
        return True

class JsonFormatter(logging.Formatter):
    def format(self, record):
        from json import dumps
        base = {
            'ts': self.formatTime(record, self.datefmt),
            'level': record.levelname,
            'msg': record.getMessage(),
            'request_id': getattr(record, 'request_id', '-')
        }
        # Include extras if present
        if hasattr(record, 'path'):
            base['path'] = getattr(record, 'path')
        return dumps(base, ensure_ascii=False)

def configure_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    # Clear default handlers to avoid duplicate logs when reloading
    logger.handlers = []
    json_logs = os.environ.get('TASKPRINTER_JSON_LOGS', 'false').lower() in ('1', 'true', 'yes')
    if json_logs:
        fmt = JsonFormatter()
    else:
        fmt = logging.Formatter('[%(asctime)s] %(levelname)s %(request_id)s %(message)s')
    # Try systemd journal
    handler = None
    try:
        from systemd.journal import JournalHandler  # type: ignore
        handler = JournalHandler()
        handler.setFormatter(fmt)
    except Exception:
        handler = logging.StreamHandler()
        handler.setFormatter(fmt)
    handler.addFilter(RequestIdFilter())
    logger.addHandler(handler)
    # Also direct Flask's app.logger to root
    app.logger.handlers = []
    app.logger.propagate = True

configure_logging()

# Simple background job queue for printing
JOB_QUEUE: "queue.Queue[dict]" = queue.Queue()
WORKER_STARTED = False
JOBS = {}
JOBS_MAX = 200

def _print_worker():
    while True:
        job = JOB_QUEUE.get()
        try:
            kind = job.get('type')
            job_id = job.get('job_id')
            _update_job(job_id, status='running')
            if kind == 'tasks':
                subtitle_tasks = job.get('payload', [])
                ok = print_tasks(subtitle_tasks)
                _update_job(job_id, status='success' if ok else 'error')
            elif kind == 'test':
                cfg = job.get('config_override')
                ok = _do_test_print(cfg)
                _update_job(job_id, status='success' if ok else 'error')
            else:
                app.logger.warning(f"Unknown job type: {kind}")
                _update_job(job_id, status='error', error='unknown_job_type')
        except Exception as e:
            app.logger.exception(f"Job failed: {e}")
            try:
                _update_job(job.get('job_id'), status='error', error=str(e))
            except Exception:
                pass
        finally:
            JOB_QUEUE.task_done()

def ensure_worker():
    global WORKER_STARTED
    if not WORKER_STARTED:
        t = threading.Thread(target=_print_worker, daemon=True)
        t.start()
        WORKER_STARTED = True
        globals()['PRINT_WORKER_THREAD'] = t

def _update_job(job_id, **updates):
    if not job_id:
        return
    job = JOBS.get(job_id)
    if not job:
        return
    job.update(updates)
    job['updated_at'] = datetime.now(timezone.utc).isoformat()

def _create_job(kind, meta=None):
    job_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc).isoformat()
    job = {
        'id': job_id,
        'type': kind,
        'status': 'queued',
        'created_at': now,
        'updated_at': now,
    }
    if meta:
        job.update(meta)
    # prune if needed
    if len(JOBS) >= JOBS_MAX:
        # remove oldest
        oldest = sorted(JOBS.values(), key=lambda j: j.get('created_at'))[0]['id']
        JOBS.pop(oldest, None)
    JOBS[job_id] = job
    return job_id

# On every request, check for config.json
from flask import g
@app.before_request
def check_config():
    # Assign a request id for logging
    g.request_id = uuid.uuid4().hex
    if not request.path.startswith('/setup'):
        if request.path.startswith('/setup_test_print'):
            return None
        config = load_config()
        if not config:
            return redirect(url_for('setup'))
        g.config = config

@app.after_request
def set_csrf_cookie(response):
    try:
        token = generate_csrf()
        response.set_cookie('csrf_token', token, secure=False, httponly=False, samesite='Lax')
    except Exception:
        pass
    return response

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
        # Profile selection (optional)
        printer_profile = request.form.get('printer_profile', '').strip()
        if printer_profile.lower() == 'generic':
            printer_profile = ''

        # Spacing and formatting preferences
        try:
            cut_feed_lines = int(request.form.get('cut_feed_lines', '2'))
        except ValueError:
            cut_feed_lines = 2
        cut_feed_lines = max(0, min(10, cut_feed_lines))
        print_separators = request.form.get('print_separators') == 'on'

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
            'printer_profile': printer_profile,
            'cut_feed_lines': cut_feed_lines,
            'print_separators': print_separators,
        }
        save_config(config)
        auto_startup = request.form.get('auto_startup') == 'on'
        return render_template('loading.html', auto_startup=auto_startup)
    # Render setup page (for GET requests)
    show_close = os.path.exists(CONFIG_PATH)
    cfg = load_config()
    return render_template('setup.html', usb_devices=usb_devices, show_close=show_close, config=cfg)

@app.route('/restart', methods=['POST'])
def restart():
    data = request.get_json(force=True)
    auto_startup = data.get('auto_startup', False)
    if auto_startup:
        try:
            subprocess.run(['bash', './install_service.sh'], capture_output=True, text=True, timeout=30)
        except Exception as e:
            pass
    # Schedule process exit so caller gets a response first.
    def _exit_soon():
        try:
            sleep(0.3)
        finally:
            os._exit(0)
    threading.Thread(target=_exit_soon, daemon=True).start()
    return '', 204

def print_tasks(subtitle_tasks):
    config = load_config()
    if config is None:
        raise RuntimeError("No config found. Please complete setup at /setup.")
    app.logger.info(f"Starting print job for {len(subtitle_tasks)} tasks (subtitle/task pairs)...")
    try:
        app.logger.info("Attempting to connect to printer...")
        p = None
        profile = config.get('printer_profile') or None
        if config['printer_type'] == 'usb':
            p = Usb(int(config['usb_vendor_id'], 16), int(config['usb_product_id'], 16), 0, profile=profile) if profile else Usb(int(config['usb_vendor_id'], 16), int(config['usb_product_id'], 16))
        elif config['printer_type'] == 'network':
            from escpos.printer import Network
            p = Network(config['network_ip'], int(config['network_port']), profile=profile) if profile else Network(config['network_ip'], int(config['network_port']))
        elif config['printer_type'] == 'serial':
            from escpos.printer import Serial
            p = Serial(config['serial_port'], baudrate=int(config['serial_baudrate']), profile=profile) if profile else Serial(config['serial_port'], baudrate=int(config['serial_baudrate']))
        else:
            raise Exception('Unsupported printer type')
        app.logger.info("Printer connection established")
        for i, item in enumerate(subtitle_tasks, 1):
            if isinstance(item, (list, tuple)):
                subtitle, task = item[0], item[1]
                flair = None
            else:
                subtitle = (item or {}).get('subtitle', '')
                task = (item or {}).get('task', '')
                flair = (item or {}).get('flair')
            if not task or not task.strip():
                continue
            app.logger.info(f"Printing receipt for task {i}: {task.strip()} (Subtitle: {subtitle})")
            p.text("\n\n")
            p.set(align='left', bold=False, width=1, height=1)
            if bool(config.get('print_separators', True)):
                p.text("------------------------------------------------\n")
            if subtitle:
                p.set(align='left', bold=False, width=1, height=1)
                p.text(f"{subtitle}\n")
            # Flair: icon/image or QR
            if flair and isinstance(flair, dict):
                ftype = flair.get('type')
                fval = flair.get('value', '')
                try:
                    if ftype == 'icon' and fval:
                        icon_path = _resolve_icon_path(fval)
                        if icon_path and os.path.exists(icon_path):
                            p.image(icon_path)
                        else:
                            # generate simple placeholder
                            img = _generate_icon_placeholder(fval, int(config.get('receipt_width', 512)))
                            p.image(img)
                    elif ftype == 'image' and fval:
                        if os.path.isfile(fval):
                            p.image(fval)
                        else:
                            app.logger.warning(f"Image not found for task {i}: {fval}")
                    elif ftype == 'qr' and fval:
                        p.qr(fval)
                except Exception as e:
                    app.logger.warning(f"Flair render failed for task {i}: {e}")
            img = render_large_text_image(task.strip(), config)
            p.image(img)
            p.set(align='left', bold=False, width=1, height=1)
            if bool(config.get('print_separators', True)):
                p.text("------------------------------------------------\n")
            # Extra blank lines before cutting, configurable
            extra = int(config.get('cut_feed_lines', 2))
            if extra > 0:
                p.text("\n" * extra)
            p.cut()
            app.logger.info(f"Printed and cut receipt for task {i}")
        p.close()
        app.logger.info("Printer connection closed")
        app.logger.info("All tasks printed as separate receipts successfully")
        return True
    except Exception as e:
        app.logger.exception(f"Printer error: {str(e)}")
        return False

def _generate_icon_placeholder(key: str, width: int):
    try:
        from PIL import Image as _Image, ImageDraw as _ImageDraw, ImageFont as _ImageFont
        size = min(192, max(96, width // 4))
        img = _Image.new("L", (size, size), 255)
        d = _ImageDraw.Draw(img)
        # draw a simple circle and letter
        r = size // 2 - 6
        center = (size // 2, size // 2)
        d.ellipse([center[0]-r, center[1]-r, center[0]+r, center[1]+r], outline=0, width=4)
        letter = (key[:1] or '?').upper()
        try:
            font = _resolve_font_path({'font_path': None}, size // 2)
        except Exception:
            font = _ImageFont.load_default()
        tw, th = d.textsize(letter, font=font)
        d.text((center[0]-tw//2, center[1]-th//2), letter, fill=0, font=font)
        return img
    except Exception:
        return None

def print_tasks_with_config(subtitle_tasks, config):
    # Temporarily run print using provided config
    if config is None:
        return False
    # We reuse render_large_text_image with config override already supported
    try:
        app.logger.info("Starting print (override config)")
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
        for i, (subtitle, task) in enumerate(subtitle_tasks, 1):
            if not task.strip():
                continue
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
        p.close()
        return True
    except Exception as e:
        app.logger.exception(f"Override-config print failed: {e}")
        return False

def _do_test_print(config_override=None):
    config = config_override or load_config()
    if config is None:
        raise RuntimeError("No config found. Please complete setup at /setup.")
    test_pairs = [("TEST", "Task Printer Test Page"), (datetime.now().strftime('%Y-%m-%d %H:%M'), "Hello from Task Printer!")]
    return print_tasks_with_config(test_pairs, config)

def _resolve_font_path(config, font_size):
    # Preferred order: config font_path -> env -> common system paths
    candidates = []
    cfg_path = None
    if config:
        cfg_path = config.get('font_path')
    env_path = os.environ.get('TASKPRINTER_FONT_PATH')
    if cfg_path:
        candidates.append(cfg_path)
    if env_path and env_path not in candidates:
        candidates.append(env_path)
    common = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]
    for pth in common:
        if pth not in candidates:
            candidates.append(pth)
    from PIL import ImageFont as _IF
    for pth in candidates:
        try:
            return _IF.truetype(pth, font_size)
        except Exception:
            continue
    app.logger.warning("No TTF font found; falling back to default PIL font.")
    return ImageFont.load_default()

def render_large_text_image(text, config=None):
    if config is None:
        config = load_config()
    if config is None:
        raise RuntimeError("No config found. Please complete setup at /setup.")
    width = int(config.get('receipt_width', 512))
    font_size = int(config.get('task_font_size', 72))
    font = _resolve_font_path(config, font_size)
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
        # Parse all subtitle/task groups from the form with limits
        subtitle_tasks = []
        form = request.form
        section = 1
        total_chars = 0
        while True:
            subtitle_key = f'subtitle_{section}'
            subtitle = form.get(subtitle_key, '').strip()
            if not subtitle and section == 1:
                # If the first section is empty, treat as no input
                break
            if not subtitle:
                # No more sections
                break
            if len(subtitle) > MAX_SUBTITLE_LEN:
                flash(f'Subtitle in section {section} is too long (max {MAX_SUBTITLE_LEN}).', 'error')
                return redirect(url_for('index'))
            if _has_control_chars(subtitle):
                flash('Subtitles cannot contain control characters.', 'error')
                return redirect(url_for('index'))
            # Find all tasks for this section
            task_num = 1
            while True:
                task_key = f'task_{section}_{task_num}'
                task = form.get(task_key, '').strip()
                if not task:
                    break
                if len(task) > MAX_TASK_LEN:
                    flash(f'Task {task_num} in section {section} is too long (max {MAX_TASK_LEN}).', 'error')
                    return redirect(url_for('index'))
                if _has_control_chars(task):
                    flash('Tasks cannot contain control characters.', 'error')
                    return redirect(url_for('index'))
                # Flair parsing
                flair = None
                ftype = form.get(f'flair_type_{section}_{task_num}', 'none')
                if ftype == 'icon':
                    icon_key = form.get(f'flair_icon_{section}_{task_num}', '').strip()
                    if icon_key:
                        flair = {'type': 'icon', 'value': icon_key}
                elif ftype == 'qr':
                    qr_val = form.get(f'flair_qr_{section}_{task_num}', '').strip()
                    if qr_val:
                        if len(qr_val) > MAX_QR_LEN:
                            flash(f'QR data too long in section {section} task {task_num} (max {MAX_QR_LEN}).', 'error')
                            return redirect(url_for('index'))
                        if _has_control_chars(qr_val):
                            flash('QR data cannot contain control characters.', 'error')
                            return redirect(url_for('index'))
                        flair = {'type': 'qr', 'value': qr_val}
                elif ftype == 'image':
                    file_key = f'flair_image_{section}_{task_num}'
                    if file_key in request.files:
                        file = request.files.get(file_key)
                        if file and file.filename:
                            fname = secure_filename(file.filename)
                            ext = os.path.splitext(fname)[1].lower()
                            if ext not in {'.png', '.jpg', '.jpeg', '.gif', '.bmp'}:
                                flash('Unsupported image type. Use PNG, JPG, GIF, or BMP.', 'error')
                                return redirect(url_for('index'))
                            # size check
                            try:
                                file.stream.seek(0, os.SEEK_END)
                                size = file.stream.tell()
                                file.stream.seek(0)
                            except Exception:
                                size = 0
                            if size and size > MAX_UPLOAD_SIZE:
                                flash('Image too large.', 'error')
                                return redirect(url_for('index'))
                            unique = uuid.uuid4().hex + ext
                            dest = os.path.join(MEDIA_PATH, unique)
                            file.save(dest)
                            flair = {'type': 'image', 'value': dest}
                subtitle_tasks.append({'subtitle': subtitle, 'task': task, 'flair': flair})
                task_num += 1
                if task_num > MAX_TASKS_PER_SECTION:
                    flash(f'Too many tasks in section {section} (max {MAX_TASKS_PER_SECTION}).', 'error')
                    return redirect(url_for('index'))
            section += 1
            if section > MAX_SECTIONS:
                flash(f'Too many sections (max {MAX_SECTIONS}).', 'error')
                return redirect(url_for('index'))
        total_chars = sum(len(s) + len(t) for s, t in subtitle_tasks)
        if total_chars > MAX_TOTAL_CHARS:
            flash(f'Input too large (max total characters {MAX_TOTAL_CHARS}).', 'error')
            return redirect(url_for('index'))
        if not subtitle_tasks:
            flash('Please enter at least one task.', 'error')
            return redirect(url_for('index'))
        try:
            ensure_worker()
            job_id = _create_job('tasks', meta={'total': len(subtitle_tasks)})
            JOB_QUEUE.put({'type': 'tasks', 'payload': subtitle_tasks, 'job_id': job_id})
            flash(f'Queued {len(subtitle_tasks)} task(s) for printing. Job: {job_id}', 'success')
            return redirect(url_for('index', job=job_id))
        except Exception as e:
            flash(f'Error queuing print job: {str(e)}', 'error')
        return redirect(url_for('index'))
    job_id = request.args.get('job')
    return render_template('index.html', job_id=job_id, icons=get_available_icons())

@app.route('/test_print', methods=['POST'])
def test_print():
    try:
        ensure_worker()
        job_id = _create_job('test')
        JOB_QUEUE.put({'type': 'test', 'job_id': job_id})
        flash(f'Test print queued. Job: {job_id}', 'success')
        return redirect(url_for('index', job=job_id))
    except Exception as e:
        flash(f'Error queuing test print: {str(e)}', 'error')
    return redirect(url_for('index'))

@app.route('/jobs/<job_id>')
def job_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return ({'error': 'not_found'}, 404)
    return job

@app.route('/jobs')
def jobs_list():
    # Return recent jobs sorted by created_at descending
    jobs = list(JOBS.values())
    try:
        jobs.sort(key=lambda j: j.get('created_at', ''), reverse=True)
    except Exception:
        pass
    return render_template('jobs.html', jobs=jobs)

@app.route('/setup_test_print', methods=['POST'])
def setup_test_print():
    # Build config from form values without saving, then queue a test print
    form = request.form
    printer_type = form.get('printer_type', 'usb')
    if printer_type == 'usb':
        selected_usb = form.get('usb_device', '')
        if selected_usb and selected_usb != 'manual':
            usb_vendor_id, usb_product_id = selected_usb.split(':')
        else:
            usb_vendor_id = form.get('usb_vendor_id', '0x04b8')
            usb_product_id = form.get('usb_product_id', '0x0e28')
    else:
        usb_vendor_id = form.get('usb_vendor_id', '0x04b8')
        usb_product_id = form.get('usb_product_id', '0x0e28')
    network_ip = form.get('network_ip', '')
    network_port = form.get('network_port', '9100')
    serial_port = form.get('serial_port', '')
    serial_baudrate = form.get('serial_baudrate', '19200')
    # Match width/font size logic from setup
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
    try:
        ensure_worker()
        job_id = _create_job('test', meta={'origin': 'setup'})
        JOB_QUEUE.put({'type': 'test', 'job_id': job_id, 'config_override': config})
        flash(f'Setup Test Print queued. Job: {job_id}', 'success')
    except Exception as e:
        flash(f'Error queuing setup test print: {str(e)}', 'error')
    return redirect(url_for('setup'))

def _has_control_chars(s: str) -> bool:
    return any((ord(c) < 32 and c not in '\n\r\t') or ord(c) == 127 for c in s)

@app.route('/healthz')
def healthz():
    status = {
        'status': 'ok',
        'worker_started': WORKER_STARTED,
        'worker_alive': bool(globals().get('PRINT_WORKER_THREAD', None)) and globals()['PRINT_WORKER_THREAD'].is_alive(),
        'queue_size': JOB_QUEUE.qsize(),
    }
    cfg = load_config()
    if not cfg:
        status['status'] = 'degraded'
        status['reason'] = 'no_config'
        return status, 200
    # Try basic printer reachability
    try:
        if cfg['printer_type'] == 'usb':
            _ = Usb(int(cfg['usb_vendor_id'], 16), int(cfg['usb_product_id'], 16))
            _.close()
        elif cfg['printer_type'] == 'network':
            from escpos.printer import Network
            _ = Network(cfg['network_ip'], int(cfg['network_port']))
            _.close()
        elif cfg['printer_type'] == 'serial':
            from escpos.printer import Serial
            _ = Serial(cfg['serial_port'], baudrate=int(cfg['serial_baudrate']))
            _.close()
        status['printer_ok'] = True
    except Exception as e:
        status['printer_ok'] = False
        status['status'] = 'degraded'
        status['reason'] = f'printer_unreachable: {type(e).__name__}'
    return status, 200

if __name__ == '__main__':
    app.logger.info("Starting Task Printer on http://0.0.0.0:5000")
    app.logger.info("Access from local network: http://[raspberry-pi-ip]:5000")
    app.logger.info("Press Ctrl+C to stop the server")
    ensure_worker()
    app.run(host='0.0.0.0', port=5000, debug=False) 
