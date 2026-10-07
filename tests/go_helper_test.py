"""Windows Go helper filenames and UTF-8 protocol handling."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/retrieval'))
from languages import go
from languages.schema import SourceFile


class GoHelperTests(unittest.TestCase):
    def test_windows_builds_and_reuses_an_exe_with_utf8_protocol(self):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            self.assertTrue(kwargs['creationflags'] & 0x08000000)
            self.assertEqual(kwargs['encoding'],'utf-8')
            if command[1:2] == ['build']:
                target = Path(command[command.index('-o')+1])
                self.assertEqual(target.suffix,'.exe')
                target.write_bytes(b'fake helper')
                return subprocess.CompletedProcess(command,0,stdout='',stderr='')
            self.assertEqual(Path(command[0]).suffix,'.exe')
            payload = json.loads(kwargs['input'])
            self.assertEqual(payload['files'][0]['path'],'目录/main.go')
            return subprocess.CompletedProcess(command,0,
                stdout=json.dumps({'files':[], 'note':'中文'},ensure_ascii=False),stderr='')
        with tempfile.TemporaryDirectory(prefix='oce go 中文 ') as directory:
            with patch.object(go,'compiler',return_value=('fake-go','go1.22 windows/amd64')), \
                    patch.object(go.tempfile,'gettempdir',return_value=directory), \
                    patch.object(go.sys,'platform','win32'), \
                    patch('background_process.subprocess.CREATE_NO_WINDOW', 0x08000000, create=True), \
                    patch('background_process.subprocess.run',side_effect=run):
                sources = [SourceFile('目录/main.go','package main\n','test')]
                for _ in range(2):
                    self.assertEqual(go.parse(sources,go.settings())['note'],'中文')
        self.assertEqual(sum(command[1:2] == ['build'] for command in calls),1)
