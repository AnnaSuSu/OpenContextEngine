"""Cross-process admission limits shared by workers using a state parent."""
from contextlib import contextmanager
from pathlib import Path
from writer_lock import acquire_writer_lock, WriterBusy
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


@contextmanager
def build_slot(directory, count, stop):
    handle = acquire_slot(directory, 'build', count, stop)
    try:
        yield
    finally:
        handle.close()
