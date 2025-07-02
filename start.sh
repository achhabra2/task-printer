#!/bin/bash
# Task Printer Startup Script
# Run this script to start the Task Printer application

echo "Starting Task Printer..."
echo "Web interface will be available at:"
echo "  Local:  http://localhost:5000"
echo "  Network: http://$(hostname -I | awk '{print $1}'):5000"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

python3 app.py 