"""Discovery and expiring client leases for a single locked index writer."""
import json
import os
from pathlib import Path
import secrets
import re
from background_process import run_background
import sys
import threading
import time

PROTOCOL = 1


def restrict_permissions(path):
    if sys.platform == 'win32':
        # os.open(mode=0o600) does not set a Windows DACL. Resolve the current
        # user's SID (independent of localized account names) and remove inheritance.
        result = run_background(['whoami', '/user', '/fo', 'csv', '/nh'],
                                capture_output=True, check=True, timeout=5)
        match = re.search(rb'S-1-[0-9-]+', result.stdout)
        if not match:
            raise PermissionError('Cannot determine current Windows user SID')
        sid = match.group().decode('ascii')
        run_background(['icacls', str(path), '/inheritance:r', '/grant:r', '*' + sid + ':F'],
                       capture_output=True, check=True, timeout=5)


class SharedWorker:
    def __init__(self, config):
        options = config['shared']
        self.path = Path(config['state']) / 'worker.json'
        self.instance = secrets.token_hex(24)
        self.fingerprint = options['fingerprint']
        self.key = config['serviceKey']
        self.ttl = options.get('leaseSeconds', 15)
        self.idle = options.get('idleSeconds', 30)
        self.leases = {}
        self.active = 0
        self.empty_since = time.monotonic()
        self.stopping = False
        self.lock = threading.Lock()
        self.finished = threading.Event()

    def publish(self, port):
        # Called only by the writer-lock holder, after HTTP bind succeeds.
        self.record = {'protocol': PROTOCOL, 'instanceId': self.instance,
                       'pid': os.getpid(), 'port': port, 'apiKey': self.key}
        temporary = self.path.with_name('worker-' + self.instance + '.tmp')
        try:
            with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as file:
                restrict_permissions(temporary)
                json.dump(self.record, file)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def lease(self, body, release=False):
        with self.lock:
            if body.get('instanceId') != self.instance:
                return 409, {'error': 'Worker instance changed', 'code': 'INSTANCE_CHANGED'}
            if not secrets.compare_digest(str(body.get('fingerprint', '')), self.fingerprint):
                return 409, {'error': 'This index is used by a worker with incompatible configuration or runtime. '
                             'Close its clients before changing configuration, or use a separate --state directory.',
                             'code': 'CONFIG_MISMATCH'}
            identifier = body.get('leaseId')
            if not isinstance(identifier, str) or not 1 <= len(identifier) <= 128:
                return 422, {'error': 'Invalid lease identifier'}
            if self.stopping:
                return 503, {'error': 'Worker is stopping'}
            if release:
                self.leases.pop(identifier, None)
            else:
                self.leases[identifier] = time.monotonic() + self.ttl
            self.empty_since = time.monotonic()
            return 200, {'instanceId': self.instance, 'pid': os.getpid(), 'leaseSeconds': self.ttl}

    def enter(self):
        with self.lock:
            if self.stopping:
                return False
            self.active += 1
            return True

    def leave(self):
        with self.lock:
            self.active -= 1
            self.empty_since = time.monotonic()

    def should_stop(self):
        with self.lock:
            now = time.monotonic()
            self.leases = {key: until for key, until in self.leases.items() if until > now}
            if self.leases or self.active:
                self.empty_since = now
            elif now - self.empty_since >= self.idle:
                self.stopping = True
            return self.stopping

    def monitor(self, server, busy=lambda: False):
        def run():
            while not self.finished.wait(min(1, self.idle / 2)):
                if busy():
                    continue
                if self.should_stop():
                    server.shutdown()
                    return
        threading.Thread(target=run, name='worker-leases', daemon=True).start()

    def close(self):
        self.finished.set()
        # Cleanup precedes releasing the writer lock; never unlink a successor's record.
        try:
            if json.loads(self.path.read_text()).get('instanceId') == self.instance:
                self.path.unlink()
        except (FileNotFoundError, ValueError):
            pass
