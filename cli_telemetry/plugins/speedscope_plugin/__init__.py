"""
Folded stack generator plugin for cli-telemetry.
"""

from .plugin import load_spans, export_folded, build_path, register

__all__ = ["load_spans", "export_folded", "build_path", "register"]
