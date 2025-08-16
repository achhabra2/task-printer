#!/bin/bash
# Install or update the taskprinter systemd service

SERVICE_FILE=taskprinter.service
ENV_FILE=/etc/default/taskprinter
USER=$(whoami)
WORKDIR=$(pwd)

# Create or update systemd unit file
cat > $SERVICE_FILE <<EOF
[Unit]
Description=Task Printer Flask App
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$WORKDIR
EnvironmentFile=$ENV_FILE
ExecStart=/bin/bash $WORKDIR/start.sh
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=true
EOF

# Optionally add DynamicUser if the variable is set (avoids emitting an empty setting)
if [ -n "$DYNAMIC_USER" ]; then
  echo "DynamicUser=$DYNAMIC_USER" >> $SERVICE_FILE
fi

# Optionally add CapabilityBoundingSet if provided via environment (avoid empty value)
if [ -n "$CAPABILITY_BOUNDING_SET" ]; then
  echo "CapabilityBoundingSet=$CAPABILITY_BOUNDING_SET" >> $SERVICE_FILE
fi

# Finish unit file
cat >> $SERVICE_FILE <<EOF

[Install]
WantedBy=multi-user.target
EOF

# Ensure default environment file exists with helpful placeholders
if [ ! -f "$ENV_FILE" ]; then
  echo "Creating default env file at $ENV_FILE (requires sudo)..."
  TMP_ENV=$(mktemp)
  cat > "$TMP_ENV" <<ENVEOF
# Environment for Task Printer service
# Provide a strong random secret for Flask sessions
# TASKPRINTER_SECRET_KEY=change_me_to_a_random_string

# Optional: override where config.json is stored
# TASKPRINTER_CONFIG_PATH=

# Logging options
# TASKPRINTER_JSON_LOGS=false

# Runtime options
# USE_UV=false           # If true and 'uv' is available, runs via uv
# VENV_PATH=             # If set and points to a venv, uses that venv

# Systemd hardening options
# Set to 'yes' to enable dynamic user sandboxing (leave empty to disable)
# Note: If enabling, consider removing/ignoring the static User= in unit.
# DYNAMIC_USER=no
ENVEOF
  sudo mkdir -p "$(dirname "$ENV_FILE")"
  sudo cp "$TMP_ENV" "$ENV_FILE"
  rm -f "$TMP_ENV"
fi

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
