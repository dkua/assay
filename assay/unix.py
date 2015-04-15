"""Support for users interacting with the terminal."""

import errno
import fcntl
import os
import select
import signal
import sys
import termios
import tty
from contextlib import contextmanager

_everything = 1024 * 1024

@contextmanager
def configure_tty():
    """Configure the terminal to give us keystrokes, not whole lines.

    By turning off echo and canonical line interpretation, a read from
    standard input will immediately see each keystroke the user types.

    """
    isatty = sys.stdin.isatty() and sys.stdout.isatty()
    if isatty:
        fd = sys.stdin.fileno()
        original_mode = termios.tcgetattr(fd)
        tty.setcbreak(fd)
    try:
        yield isatty
    finally:
        if isatty:
            termios.tcsetattr(fd, termios.TCSAFLUSH, original_mode)

def close_on_exec(fd):
    """Set the close-on-exec flag of the file descriptor `fd`."""
    fcntl.fcntl(fd, fcntl.F_SETFD, fcntl.FD_CLOEXEC)

def keep_on_exec(fd):
    """Clear the close-on-exec flag of the file descriptor `fd`."""
    fcntl.fcntl(fd, fcntl.F_SETFD, 0)

def cpu_count():
    """Return the number of CPUs on the system."""
    if os.path.exists('/proc/cpuinfo'):
        with open('/proc/cpuinfo') as f:
            return f.read().count('\nbogomips')
    return 2

def discard_input(fileobj, bufsize):
    """Discard all bytes queued for input on `fileobj`.

    Bytes queued in the operating system are disposed of through an
    ``os.read()``, and bytes in our own buffers by replacing the object.

    """
    fd = fileobj.fileno()
    fcntl.fcntl(fd, fcntl.F_SETFL, os.O_NONBLOCK)
    try:
        os.read(fd, _everything)
    except OSError:
        pass
    fcntl.fcntl(fd, fcntl.F_SETFL, 0)
    return os.fdopen(os.dup(fd), fileobj.mode, bufsize)

def kill_dash_9(pid):
    """Kill a process with a signal that cannot be caught or ignored."""
    os.kill(pid, signal.SIGKILL)

class EPoll(object):
    """File descriptor polling object that returns objects, not integers."""

    def __init__(self):
        self.fdmap = {}
        self.poller = select.epoll()

    def register(self, obj, flags=select.EPOLLIN):
        fd = obj.fileno()
        self.fdmap[fd] = obj
        self.poller.register(fd, flags)

    def unregister(self, obj):
        fd = obj.fileno()
        del self.fdmap[fd]
        self.poller.unregister(fd)

    def events(self):
        while True:
            try:
                for fd, flags in self.poller.poll():
                    yield self.fdmap[fd], flags
            except IOError as e:
                if e.errno != errno.EINTR:
                    raise


class KQueue(object):
    """File descriptor polling object that returns objects, not integers."""

    def __init__(self):
        self.fdmap = {}
        self.poller = select.kqueue()

    def register(self, obj):
        fd = obj.fileno()
        self.fdmap[fd] = obj
        event = [select.kevent(
            fd,
            select.KQ_FILTER_READ,
            flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
        )]
        self.poller.control(event, max_events=0)

    def unregister(self, obj):
        fd = obj.fileno()
        del self.fdmap[fd]
        event = [select.kevent(
            fd,
            select.KQ_FILTER_READ,
            select.KQ_EV_DELETE
        )]
        self.poller.control(event, max_events=0)

    def events(self):
        while True:
            try:
                for event in self.poller.control(None, max_events=0):
                    yield self.fdmap[event.ident], event.flags
            except IOError as e:
                if e.errno != errno.EINTR:
                    raise
        self.poller.close()
