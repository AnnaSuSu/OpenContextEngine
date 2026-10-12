"""Cross-process admission limits shared by workers using a state parent."""
from contextlib import contextmanager
from pathlib import Path
import time
import uuid
from writer_lock import acquire_writer_lock, remove_lock_file, WriterBusy
from cancellation import check, Cancelled


def acquire_slot(directory, name, count, stop):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    while not stop.is_set():
        check()
        for number in range(count):
            try:
                return acquire_writer_lock(directory/f'{name}-{number}.lock')
            except WriterBusy:
                pass
        stop.wait(.1)
    raise Cancelled('Worker stopped while waiting for resource capacity')


class BuildSlot:
    """FIFO admission within each priority, with process-lock-backed waiters."""
    def __init__(self, directory, count, stop, *, update=False, name='build'):
        self.directory, self.count, self.stop = Path(directory), count, stop
        self.name, self.update, self.handle = name, update, None
        self.queue = self.directory/(name+'-queue')
        self.queue.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _waiting(self):
        waiting = []
        for path in sorted(self.queue.glob('*.request')):
            try:
                probe = acquire_writer_lock(path.with_suffix('.lock'))
            except WriterBusy:
                waiting.append(path.name)
            else:
                # A killed or cancelled process cannot retain priority forever.
                path.unlink(missing_ok=True)
                probe.close()
                remove_lock_file(path.with_suffix('.lock'))
        return waiting

    def has_updates(self):
        if self.update:
            return False
        with acquire_slot(self.queue, 'scheduler', 1, self.stop):
            return any(name.startswith('0-') for name in self._waiting())

    def acquire(self):
        name = f'{0 if self.update else 1}-{time.time_ns():020d}-{uuid.uuid4().hex}'
        request = self.queue/(name+'.request')
        ticket = acquire_writer_lock(request.with_suffix('.lock'))
        request.touch()
        try:
            while not self.stop.is_set():
                check()
                with acquire_slot(self.queue, 'scheduler', 1, self.stop):
                    waiting = self._waiting()
                    if request.name in waiting[:self.count]:
                        for number in range(self.count):
                            try:
                                self.handle = acquire_writer_lock(self.directory/f'{self.name}-{number}.lock')
                                return self
                            except WriterBusy:
                                pass
                self.stop.wait(.1)
            raise Cancelled('Worker stopped while waiting for build capacity')
        finally:
            request.unlink(missing_ok=True)
            ticket.close()
            remove_lock_file(request.with_suffix('.lock'))

    def release(self):
        if self.handle:
            self.handle.close()
            self.handle = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.release()


@contextmanager
def build_slot(directory, count, stop, *, update=False):
    with BuildSlot(directory, count, stop, update=update) as slot:
        yield slot
