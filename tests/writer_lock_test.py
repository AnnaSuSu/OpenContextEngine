"""Single-writer exclusion and release across operating systems and processes."""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]/'src/retrieval'
sys.path.insert(0, str(ROOT))
from writer_lock import acquire_writer_lock


class WriterLockTests(unittest.TestCase):
    def test_competing_process_is_rejected_and_close_releases_lock(self):
        code = ('from pathlib import Path; import sys; '
                f'sys.path.insert(0, {str(ROOT)!r}); '
                'from writer_lock import acquire_writer_lock; '
                'acquire_writer_lock(Path(sys.argv[1])).close()')
        with tempfile.TemporaryDirectory(prefix='oce lock 中文 ') as directory:
            path = Path(directory)/'writer.lock'
            with acquire_writer_lock(path):
                contender = subprocess.run([sys.executable,'-c',code,str(path)],
                                           capture_output=True,encoding='utf-8')
                self.assertNotEqual(contender.returncode,0)
                self.assertIn('running writer',contender.stderr)
            released = subprocess.run([sys.executable,'-c',code,str(path)],
                                      capture_output=True,encoding='utf-8')
            self.assertEqual(released.returncode,0,released.stderr)

    def test_windows_uses_nonblocking_byte_zero_and_closes_on_contention(self):
        calls = []
        def locking(fd, mode, length):
            import os
            calls.append((os.lseek(fd,0,os.SEEK_CUR),mode,length))
            if len(calls) > 1:
                raise OSError('locked')
        api = SimpleNamespace(locking=locking,LK_NBLCK=123)
        with patch('sys.platform','win32'), patch.dict(sys.modules,{'msvcrt':api}):
            windows = runpy.run_path(str(ROOT/'writer_lock.py'))['acquire_writer_lock']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'writer.lock'
            # Existing files must also lock byte zero, rather than the append offset.
            path.write_bytes(b'existing')
            with windows(path):
                with self.assertRaisesRegex(ValueError,'running writer'):
                    windows(path)
            self.assertEqual(calls,[(0,123,1),(0,123,1)])
            path.unlink()  # A failed attempt must not leave an open Windows handle.
