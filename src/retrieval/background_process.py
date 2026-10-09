"""Run worker helpers without creating Windows console windows."""
import subprocess
import sys
import os
import signal
import time
from cancellation import current


def run_background(args, **kwargs):
    # Redirecting stdio alone does not stop a console application launched by
    # our detached worker from opening a new console on Windows.
    if sys.platform == 'win32':
        kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.CREATE_NO_WINDOW
    scope = current()
    if scope is None:
        return subprocess.run(args, **kwargs)
    scope.check()
    checked = kwargs.pop('check', False)
    timeout = kwargs.pop('timeout', None)
    data = kwargs.pop('input', None)
    if kwargs.pop('capture_output', False):
        kwargs['stdout'] = subprocess.PIPE
        kwargs['stderr'] = subprocess.PIPE
    if data is not None:
        kwargs['stdin'] = subprocess.PIPE
    if sys.platform != 'win32':
        kwargs['start_new_session'] = True
    deadline = time.monotonic()+timeout if timeout is not None else float('inf')
    with subprocess.Popen(args, **kwargs) as child:
        def interrupt():
            if child.poll() is None:
                if sys.platform == 'win32':
                    try:
                        subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
                    except (OSError, subprocess.SubprocessError):
                        child.kill()
                else:
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        unregister = lambda: None
        try:
            unregister = scope.register(interrupt)
            while True:
                scope.check()
                try:
                    stdout, stderr = child.communicate(input=data, timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    data = None
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(args, timeout)
            scope.check()
            result = subprocess.CompletedProcess(args, child.returncode, stdout, stderr)
            if checked:
                result.check_returncode()
            return result
        finally:
            interrupt()
            child.communicate()
            unregister()
