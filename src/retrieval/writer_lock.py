"""Nonblocking process lock, released when its file handle is closed."""
import sys

if sys.platform == 'win32':
    import msvcrt

    def lock(file):
        # Every writer locks the same byte, including when the file is empty.
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
else:
    import fcntl

    def lock(file):
        fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)


class WriterBusy(ValueError):
    pass


def remove_lock_file(path):
    """A Windows liveness probe may still have this closed lock file open."""
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass  # An unused file is harmless; its process lock has been released.


def acquire_writer_lock(path):
    file = path.open('a+b')
    try:
        lock(file)
    except OSError:
        file.close()
        raise WriterBusy(f'This index directory already has a running writer: {path}') from None
    return file
