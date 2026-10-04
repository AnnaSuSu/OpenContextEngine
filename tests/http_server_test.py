"""A numeric loopback worker must start without reverse DNS."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1]/'scripts/retrieval-server.py'
SPEC = importlib.util.spec_from_file_location('retrieval_worker',SOURCE)
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


class LoopbackServerTests(unittest.TestCase):
    def test_bind_uses_the_numeric_address_and_bound_port_without_dns(self):
        server = WORKER.LoopbackHTTPServer.__new__(WORKER.LoopbackHTTPServer)
        server.server_address = ('127.0.0.1',0)
        server.socket = Mock()
        server.socket.getsockname.return_value = ('127.0.0.1',23456)
        with patch('socket.getfqdn',side_effect=AssertionError('Reverse DNS must not run')):
            server.server_bind()
        server.socket.bind.assert_called_once_with(('127.0.0.1',0))
        self.assertEqual(server.server_name,'127.0.0.1')
        self.assertEqual(server.server_port,23456)
