from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/retrieval'))
from languages import files


class FileScanTests(unittest.TestCase):
    def test_unchanged_files_and_exclusions_do_not_reread_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'source.txt').write_text('saved source')
            (root/'binary.dat').write_bytes(b'\x00binary')
            cache = {}
            first = files.discover_snapshot(root, cache=cache)
            with patch.object(files, 'read_text', wraps=files.read_text) as read:
                self.assertEqual(files.discover_snapshot(root, cache=cache), first)
                self.assertEqual(read.call_count, 0)
                self.assertEqual(files.discover_snapshot(root), first)
                self.assertEqual(read.call_count, 2)

    def test_edit_with_preserved_mtime_replacement_delete_and_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source.txt'
            source.write_text('before')
            cache = {}
            first = files.discover_snapshot(root, cache=cache)
            info = source.stat()
            source.write_text('after!')
            os.utime(source, ns=(info.st_atime_ns, info.st_mtime_ns))
            # Windows ctime is creation time. Queries use strict, uncached reads
            # there; metadata-only background scans reconcile periodically.
            second = files.discover_snapshot(root, cache=None if os.name == 'nt' else cache)
            self.assertNotEqual(first['files'], second['files'])
            replacement = root/'replacement.txt'
            replacement.write_text('third!')
            os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns))
            replacement.replace(source)
            third = files.discover_snapshot(root, cache=cache)
            self.assertNotEqual(second['files'], third['files'])
            source.unlink()
            self.assertEqual(files.discover_snapshot(root, cache=cache)['files'], [])
            self.assertEqual(cache, {})
            if os.name != 'nt':
                source.symlink_to(Path(__file__))
                self.assertEqual(files.discover_snapshot(root, cache=cache)['files'], [])

    def test_a_read_crossing_an_edit_is_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source.txt'
            source.write_text('before')
            original = files.read_text
            def edit(path):
                result = original(path)
                source.write_text('after read')
                return result
            cache = {}
            with patch.object(files, 'read_text', side_effect=edit):
                files.discover_snapshot(root, cache=cache)
            self.assertEqual(cache, {})
            self.assertEqual(files.discover_snapshot(root, cache=cache), files.discover_snapshot(root))

    def test_binary_detector_preserves_the_control_byte_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'source.txt'
            for byte in range(32):
                with self.subTest(byte=byte):
                    path.write_bytes(b'hello'+bytes([byte])+b'world')
                    reason = files.read_text(path)[2]
                    self.assertEqual(reason, None if byte in (9, 10, 12, 13) else 'binary-content')


if __name__ == '__main__':
    unittest.main()
