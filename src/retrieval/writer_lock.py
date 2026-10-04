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


def acquire_writer_lock(path):
    file = path.open('a+b')
    try:
        lock(file)
    except OSError:
        file.close()
        raise ValueError('This index directory already has a running writer') from None
    return file
