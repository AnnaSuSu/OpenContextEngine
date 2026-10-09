from pathlib import Path
import os
import sys
import tempfile
import threading
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/retrieval'))
from cancellation import RequestScope, Cancelled
from background_process import run_background


class CancellationTests(unittest.TestCase):
    def test_resource_registered_after_cancellation_is_interrupted(self):
        scope = RequestScope()
        scope.cancel()
        calls = []
        with self.assertRaises(Cancelled):
            scope.register(lambda: calls.append('closed'))
        self.assertEqual(calls, ['closed'])

    def test_cancelled_parser_process_is_reaped(self):
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'pid'
            stop=threading.Event()
            def cancel_when_started():
                deadline=time.monotonic()+5
                while not marker.exists() and time.monotonic()<deadline:
                    time.sleep(.01)
                stop.set()
            watcher=threading.Thread(target=cancel_when_started)
            watcher.start()
            started=time.monotonic()
            with RequestScope(timeout=10,stop=stop),self.assertRaises(Cancelled):
                run_background([sys.executable,'-c',
                    'import os,time,pathlib,sys; pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)',str(marker)],
                    capture_output=True,check=True,timeout=30)
            watcher.join()
            self.assertLess(time.monotonic()-started,5)
            if os.name!='nt':
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(marker.read_text()),0)

    def test_helper_output_and_exit_status_survive_cancellable_execution(self):
        with RequestScope():
            result=run_background([sys.executable,'-c','print(input().upper())'],
                                  input='source',text=True,capture_output=True,check=True,timeout=5)
        self.assertEqual(result.stdout,'SOURCE\n')


if __name__=='__main__':unittest.main()
