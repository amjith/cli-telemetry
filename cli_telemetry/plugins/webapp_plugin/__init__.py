"""
Web-based telemetry viewer plugin for cli-telemetry.
Requires Flask and flask-cors.
"""
from .plugin import create_app, register