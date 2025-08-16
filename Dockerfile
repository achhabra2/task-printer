# Task Printer Dockerfile (example)
#
# Build:
#   docker build -t task-printer .
# Run (network printer):
#   docker run --rm -p 5000:5000 task-printer
# Run (USB printer - privileged, not recommended; prefer specific --device):
#   docker run --rm -p 5000:5000 --device /dev/bus/usb -e TASKPRINTER_SECRET_KEY=... task-printer

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TASKPRINTER_JSON_LOGS=true

WORKDIR /app

# System deps for pillow and usb (adjust as needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libjpeg62-turbo-dev zlib1g-dev libusb-1.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Expose Flask port
EXPOSE 5000

# Default: run the app
CMD ["python", "app.py"]
