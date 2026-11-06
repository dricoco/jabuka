"""ReadOnlySerial: the fd is O_RDONLY (kernel refuses writes) and 28800 8O2 is applied."""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import termios

import pytest

from jabuka.ingest.serial_ro import ReadOnlySerial, open_fastnet


@pytest.fixture
def pty_pair():
    master, slave = pty.openpty()
    name = os.ttyname(slave)
    yield master, name
    for fd in (master, slave):
        try:
            os.close(fd)
        except OSError:
            pass


def test_fd_is_read_only(pty_pair) -> None:
    _, name = pty_pair
    ser = open_fastnet(name)
    try:
        assert isinstance(ser, ReadOnlySerial)
        flags = fcntl.fcntl(ser.fileno(), fcntl.F_GETFL)
        assert flags & os.O_ACCMODE == os.O_RDONLY
    finally:
        ser.close()


def test_kernel_rejects_write_with_ebadf(pty_pair) -> None:
    _, name = pty_pair
    ser = open_fastnet(name)
    try:
        with pytest.raises(OSError) as exc:
            os.write(ser.fileno(), b"\x00")
        assert exc.value.errno == errno.EBADF
    finally:
        ser.close()


def test_write_method_raises_permission_error(pty_pair) -> None:
    _, name = pty_pair
    ser = open_fastnet(name)
    try:
        with pytest.raises(PermissionError):
            ser.write(b"x")
    finally:
        ser.close()


def test_termios_8o2(pty_pair) -> None:
    """CSTOPB, PARODD and CS8 are applied. PARENB is deliberately NOT asserted: Linux ptys clear
    it, so parity is a Pi human-verify item (stty -F /dev/fastnet)."""
    _, name = pty_pair
    ser = open_fastnet(name)
    try:
        cflag = termios.tcgetattr(ser.fileno())[2]
        assert cflag & termios.CSTOPB
        assert cflag & termios.PARODD
        assert cflag & termios.CSIZE == termios.CS8
        assert ser.baudrate == 28800
    finally:
        ser.close()


def test_reads_bytes_written_to_master(pty_pair) -> None:
    master, name = pty_pair
    ser = open_fastnet(name)
    try:
        os.write(master, b"\xff\x01\x02")
        got = b""
        for _ in range(100):
            try:
                got += os.read(ser.fileno(), 64)
            except BlockingIOError:
                pass
            if len(got) >= 3:
                break
            import time

            time.sleep(0.01)
        assert got == b"\xff\x01\x02"
    finally:
        ser.close()
