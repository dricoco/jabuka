"""Kernel-enforced receive-only serial port for the B&G Fastnet bus.

The fd is opened O_RDONLY, so the kernel refuses any write with EBADF. pyserial's own open()
hard-codes O_RDWR, hence the subclass. termios and the BOTHER custom-baud ioctl (28800) both work
on a read-only fd. Never call send_break() or any other line-control method on this port.
"""

from __future__ import annotations

import fcntl
import os

import serial
from serial.serialutil import SerialException

FASTNET_BAUD = 28800


class ReadOnlySerial(serial.Serial):
    """pyserial Serial whose fd is opened O_RDONLY: the kernel rejects any write (EBADF)."""

    def open(self) -> None:
        if self._port is None:
            raise SerialException("Port must be configured before it can be used.")
        if self.is_open:
            raise SerialException("Port is already open.")
        try:
            self.fd = os.open(self.portstr, os.O_RDONLY | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as msg:
            self.fd = None
            raise SerialException(msg.errno, f"could not open port {self._port}: {msg}") from msg
        self.pipe_abort_read_r, self.pipe_abort_read_w = os.pipe()
        self.pipe_abort_write_r, self.pipe_abort_write_w = os.pipe()
        fcntl.fcntl(self.pipe_abort_read_r, fcntl.F_SETFL, os.O_NONBLOCK)
        fcntl.fcntl(self.pipe_abort_write_r, fcntl.F_SETFL, os.O_NONBLOCK)
        try:
            self._reconfigure_port(force_update=True)  # termios + BOTHER 28800 8O2
            self._reset_input_buffer()
        except BaseException:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
            for fd in (
                self.pipe_abort_read_r,
                self.pipe_abort_read_w,
                self.pipe_abort_write_r,
                self.pipe_abort_write_w,
            ):
                try:
                    os.close(fd)
                except OSError:
                    pass
            raise
        self.is_open = True

    def write(self, data: bytes) -> int:  # belt and braces: the fd cannot write anyway
        raise PermissionError("Fastnet port is receive-only")


def open_fastnet(path: str) -> ReadOnlySerial:
    """Open the Fastnet device receive-only at 28800 baud, 8 data bits, odd parity, 2 stop bits."""
    return ReadOnlySerial(
        path,
        baudrate=FASTNET_BAUD,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_ODD,
        stopbits=serial.STOPBITS_TWO,
        timeout=0,
    )
