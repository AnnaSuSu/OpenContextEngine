"""Run worker helpers without creating Windows console windows."""
import subprocess
import sys


def run_background(args, **kwargs):
    # Redirecting stdio alone does not stop a console application launched by
    # our detached worker from opening a new console on Windows.
    if sys.platform == 'win32':
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
    return subprocess.run(args, **kwargs)
