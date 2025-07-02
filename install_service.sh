#!/bin/bash
# Install or update the taskprinter systemd service

SERVICE_FILE=taskprinter.service
USER=$(whoami)
WORKDIR=$(pwd)

cat > $SERVICE_FILE <<EOF
[Unit]
Description=Task Printer Flask App
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$WORKDIR
ExecStart=/usr/bin/python3 $WORKDIR/app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "Copying $SERVICE_FILE to /etc/systemd/system/taskprinter.service (requires sudo)..."
sudo cp -f $SERVICE_FILE /etc/systemd/system/taskprinter.service

echo "Reloading systemd daemon..."
sudo systemctl daemon-reload

echo "Enabling taskprinter.service to start on boot..."
sudo systemctl enable taskprinter.service

echo "Restarting taskprinter.service..."
sudo systemctl restart taskprinter.service

echo "Done! Service status:"
sudo systemctl status taskprinter.service --no-pager 