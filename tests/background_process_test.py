"""Windowless worker helpers retain their pipes, failures, and timeouts."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'retrieval'))
from background_process import run_background
from languages import files, go, typescript
from languages.schema import SourceFile
from shared_worker import restrict_permissions


class BackgroundProcessTests(unittest.TestCase):
    def test_windows_helpers_all_suppress_console_creation(self):
        commands = []

        def execute(args, **kwargs):
            commands.append(args)
            self.assertTrue(kwargs['creationflags'] & 0x08000000)
            if args[0] == 'git':
                output = 'true\n' if 'rev-parse' in args else b'main.ts\0'
            elif args[0] == 'node':
                self.assertIn('main.ts', kwargs['input'])
                output = json.dumps({'compilerVersion': typescript.COMPILER_VERSION, 'units': []})
            elif args[0] == 'test-go':
                output = 'go version go1.22 windows/amd64\n'
            else:
                output = b'"user","S-1-5-21-123-456-789-1001"\r\n'
            return subprocess.CompletedProcess(args, 0, stdout=output)

        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'main.ts').write_text('export const value = 1;\n')
            with patch('background_process.sys.platform', 'win32'), \
                    patch('background_process.subprocess.CREATE_NO_WINDOW', 0x08000000, create=True), \
                    patch('background_process.subprocess.run', side_effect=execute):
                self.assertEqual(files.discover_snapshot(directory)['files'][0]['path'], 'main.ts')
                self.assertEqual(typescript.extract([SourceFile('main.ts', 'export const value = 1;', 'test')]), [])
                self.assertIn('go1.22', go.toolchain.__wrapped__('test-go'))
                restrict_permissions('worker.tmp')
        self.assertEqual([args[0] for args in commands], ['git', 'git', 'node', 'test-go', 'whoami', 'icacls'])

    def test_platform_flags_preserve_other_process_options(self):
        for platform in ['win32', 'darwin', 'linux']:
            with self.subTest(platform=platform), patch('background_process.sys.platform', platform), \
                    patch('background_process.subprocess.CREATE_NO_WINDOW', 0x08000000, create=True), \
                    patch('background_process.subprocess.run') as execute:
                options = {'input': '中文', 'encoding': 'utf-8', 'capture_output': True, 'check': True, 'timeout': 3}
                run_background(['helper'], **options)
                expected = {**options, 'creationflags': 0x08000000} if platform == 'win32' else options
                execute.assert_called_once_with(['helper'], **expected)
                if platform == 'win32':
                    run_background(['helper'], creationflags=0x00000200)
                    self.assertEqual(execute.call_args.kwargs['creationflags'], 0x08000200)

    def test_real_helpers_preserve_utf8_pipes_errors_and_timeouts(self):
        code = 'import sys; sys.stdout.write(sys.stdin.read()); sys.stderr.write("diagnostic")'
        result = run_background([sys.executable, '-c', code], input='中文\n', encoding='utf-8',
                                capture_output=True, check=True, timeout=10)
        self.assertEqual(result.stdout, '中文\n')
        self.assertEqual(result.stderr, 'diagnostic')
        with self.assertRaises(subprocess.CalledProcessError) as failure:
            run_background([sys.executable, '-c', 'raise SystemExit(7)'], capture_output=True, check=True)
        self.assertEqual(failure.exception.returncode, 7)
        with self.assertRaises(subprocess.TimeoutExpired):
            run_background([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=.1)

    @unittest.skipUnless(sys.platform == 'win32', 'Requires Windows console APIs')
    def test_native_windows_helper_has_no_console(self):
        result = run_background([getattr(sys, '_base_executable', sys.executable), '-c',
                                 'import ctypes; print(bool(ctypes.windll.kernel32.GetConsoleWindow()))'],
                                capture_output=True, text=True, check=True, timeout=10)
        self.assertEqual(result.stdout.strip(), 'False')
