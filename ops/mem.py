"""Hand freed heap back to the OS after a big piece of work.

CPython keeps memory it once needed (e.g. a scan or a page that held tens of thousands of rows) for itself, so a
long-running loop otherwise stays at its highest point for good and the 512 MB server slowly fills up.
"""
import gc


def trim():
    gc.collect()
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):
        pass
