"""Compatibility entry point for existing installations."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).with_name("opencontextengine-worker.py")), run_name="__main__")
