"""Lease expiration, shutdown arbitration, and private discovery records."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'retrieval'))
from shared_worker import SharedWorker, restrict_permissions


class SharedWorkerTests(unittest.TestCase):
    def test_admitted_build_finishes_before_idle_worker_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = self.worker(directory)
            worker.idle = .04
            building = threading.Event()
            building.set()
            stopped = threading.Event()
            server = type('Server', (), {'shutdown': lambda _: stopped.set()})()
            try:
                worker.monitor(server, busy=building.is_set)
                self.assertFalse(stopped.wait(.15))
                building.clear()
                self.assertTrue(stopped.wait(1))
            finally:
                worker.close()

    def worker(self, directory):
        return SharedWorker({'state': directory, 'serviceKey': 'test-key',
                             'shared': {'fingerprint': 'test-fingerprint', 'leaseSeconds': 15, 'idleSeconds': 30}})

    def body(self, worker):
        return {'instanceId': worker.instance, 'fingerprint': worker.fingerprint, 'leaseId': 'client-a'}

    def test_crashed_client_expires_and_active_request_prevents_shutdown(self):
        with tempfile.TemporaryDirectory() as directory, patch('shared_worker.time.monotonic', return_value=0) as clock:
            worker = self.worker(directory)
            self.assertEqual(worker.lease(self.body(worker))[0], 200)
            clock.return_value = 14
            self.assertFalse(worker.should_stop())
            self.assertTrue(worker.enter())
            clock.return_value = 100
            self.assertFalse(worker.should_stop())
            self.assertFalse(worker.leases)
            worker.leave()
            clock.return_value = 129
            self.assertFalse(worker.should_stop())
            clock.return_value = 131
            self.assertTrue(worker.should_stop())
            self.assertFalse(worker.enter())
            self.assertEqual(worker.lease(self.body(worker))[0], 503)

    def test_releasing_one_client_does_not_remove_another_and_bad_handshakes_do_not_attach(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = self.worker(directory)
            first = self.body(worker)
            self.assertEqual(worker.lease(first)[0], 200)
            self.assertEqual(worker.lease({**first, 'leaseId': 'client-b'})[0], 200)
            self.assertEqual(worker.lease(first, release=True)[0], 200)
            self.assertEqual(set(worker.leases), {'client-b'})
            self.assertFalse(worker.should_stop())
            self.assertEqual(worker.lease({**first, 'instanceId': 'stale'})[1]['code'], 'INSTANCE_CHANGED')
            self.assertEqual(worker.lease({**first, 'fingerprint': 'different'})[1]['code'], 'CONFIG_MISMATCH')
            self.assertEqual(set(worker.leases), {'client-b'})

    def test_publication_and_cleanup_do_not_remove_a_successors_record(self):
        with tempfile.TemporaryDirectory() as directory:
            worker = self.worker(directory)
            worker.publish(12345)
            record = json.loads(worker.path.read_text())
            self.assertEqual(record['instanceId'], worker.instance)
            self.assertNotIn('fingerprint', record)
            if sys.platform != 'win32':
                self.assertEqual(worker.path.stat().st_mode & 0o777, 0o600)
            worker.close()
            self.assertFalse(worker.path.exists())
            successor = self.worker(directory)
            successor.publish(12346)
            worker.close()
            self.assertEqual(json.loads(worker.path.read_text())['instanceId'], successor.instance)
            successor.close()

    def test_windows_discovery_acl_uses_the_current_user_sid(self):
        with patch('shared_worker.sys.platform', 'win32'), patch('shared_worker.run_background') as run:
            run.return_value.stdout = b'"COMPUTER\\user","S-1-5-21-123-456-789-1001"\r\n'
            restrict_permissions('worker.tmp')
            self.assertEqual(run.call_args.args[0], ['icacls', 'worker.tmp', '/inheritance:r', '/grant:r',
                                                    '*S-1-5-21-123-456-789-1001:F'])
