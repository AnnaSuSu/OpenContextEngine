"""Cooperative request deadlines with transport interruption and thread propagation."""
from contextvars import ContextVar, copy_context
import select
import socket
import threading
import time

_current = ContextVar('retrieval_request', default=None)


class Cancelled(Exception):
    pass


def check():
    token = _current.get()
    if token:
        token.check()


def submit(pool, function, *args):
    return pool.submit(copy_context().run, function, *args)


class RequestScope:
    def __init__(self, timeout=180, connection=None, stop=None):
        self.deadline = time.monotonic() + timeout
        self.connection, self.stop = connection, stop
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.lock = threading.Lock()
        self.callbacks = set()

    def check(self):
        if self.cancelled.is_set() or time.monotonic() >= self.deadline or self.stop and self.stop.is_set():
            self.cancel()
            raise Cancelled('Request cancelled or deadline exceeded')

    def cancel(self):
        with self.lock:
            if self.cancelled.is_set():
                return
            self.cancelled.set()
            callbacks = list(self.callbacks)
        for callback in callbacks:
            try:
                callback()
            except OSError:
                pass

    def register(self, callback):
        with self.lock:
            cancelled = self.cancelled.is_set()
            if not cancelled:
                self.callbacks.add(callback)
        if cancelled:
            callback()
        self.check()
        def unregister():
            with self.lock:
                self.callbacks.discard(callback)
        return unregister

    def _monitor(self):
        while not self.finished.wait(.05):
            try:
                self.check()
                if self.connection and select.select([self.connection], [], [], 0)[0]:
                    if not self.connection.recv(1, socket.MSG_PEEK):
                        self.cancel()
                        return
            except (Cancelled, OSError, ValueError):
                self.cancel()
                return

    def __enter__(self):
        self.context = _current.set(self)
        self.thread = threading.Thread(target=self._monitor, name='request-cancellation', daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.finished.set()
        self.thread.join(timeout=1)
        _current.reset(self.context)


def current():
    return _current.get()
