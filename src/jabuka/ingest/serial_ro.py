"""Receive-only serial port for the B&G Fastnet bus.

Data writes are kernel-enforced: the fd is opened O_RDONLY, so write() fails with EBADF. pyserial's
own open() hard-codes O_RDWR, hence the subclass. termios and the BOTHER custom-baud ioctl (28800)
both work on a read-only fd.

O_RDONLY does NOT stop line control: the tty layer accepts TIOCSBRK/TCSBRK (break), TIOCMSET/
TIOCMBIS/TIOCMBIC (RTS/DTR), TIOCSRS485, tcflow(TCION/TCIOFF) (sends START/STOP characters) on a
read-only fd, and the line discipline itself transmits echoed input (ECHO) and XON/XOFF (IXOFF).
On the DTECH in RS-485 mode a break or an echoed byte drives the B&G bus. So:
- every pyserial method that reaches one of those ioctls raises PermissionError (ReadOnlySerial);
- echo, XON/XOFF and hardware flow control are switched off as the first thing after open(), and
  pyserial's own raw-mode configuration keeps them off;
- tests/bus/test_no_write_path.py statically rejects direct ioctl/termios line control.
"""

from __future__ import annotations

import fcntl
import os
import termios

import serial
from serial.serialutil import SerialException

FASTNET_BAUD = 28800


_RO = "Fastnet port is receive-only"
# local modes under which the line discipline itself transmits (echo of received bytes)
_ECHO_LFLAGS = (
    termios.ECHO | termios.ECHOE | termios.ECHOK | termios.ECHONL | termios.ICANON | termios.IEXTEN
)
_ECHOCTL = getattr(termios, "ECHOCTL", 0) | getattr(termios, "ECHOKE", 0)


def _quiesce_and_reset_speed(fd: int) -> None:
    """First thing after open(): stop the tty from transmitting on its own, and put it back on a
    standard speed (38400, no parity) before pyserial configures it.

    - ECHO/ICANON off: a fresh ttyUSB defaults to cooked mode with echo, so every received byte
      would be sent back onto the bus until pyserial's raw-mode setup ran.
    - IXON/IXOFF/IXANY and CRTSCTS off: no XON/XOFF characters, no RTS flow control.
    - Speed: after a previous 28800 open, recent glibc (2.43) reports the custom speed as the
      literal 28800 from tcgetattr, and pyserial's tcsetattr of those attributes is then rejected
      (EINVAL), so reopening the same tty (ingest restart, reconnect, pty replay) failed.

    Best effort: a failure here is left for pyserial's own configuration to report.
    """
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] &= ~(termios.IXON | termios.IXOFF | termios.IXANY)
        cflag = attrs[2]
        cflag &= ~(termios.CBAUD | termios.PARENB | termios.PARODD | termios.CRTSCTS)
        cflag |= termios.B38400 | termios.CREAD | termios.CLOCAL
        attrs[2] = cflag
        attrs[3] &= ~(_ECHO_LFLAGS | _ECHOCTL)
        attrs[4] = termios.B38400
        attrs[5] = termios.B38400
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except (termios.error, OSError, AttributeError):
        pass


class ReadOnlySerial(serial.Serial):
    """pyserial Serial whose fd is opened O_RDONLY (the kernel rejects data writes with EBADF) and
    whose line-control methods all raise PermissionError (O_RDONLY does not block those)."""

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
            _quiesce_and_reset_speed(self.fd)  # no echo; reopen-safe on glibc 2.43
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
        raise PermissionError(_RO)

    # -- line control: each of these reaches an ioctl that works on an O_RDONLY fd -------------
    # (the deprecated aliases sendBreak/setRTS/setDTR/setXON/flowControlOut route through these)
    def send_break(self, duration: float = 0.25) -> None:  # tcsendbreak
        raise PermissionError(_RO)

    def _update_break_state(self) -> None:  # break_condition setter: TIOCSBRK/TIOCCBRK
        raise PermissionError(_RO)

    def _update_rts_state(self) -> None:  # rts setter: TIOCMBIS/TIOCMBIC
        raise PermissionError(_RO)

    def _update_dtr_state(self) -> None:  # dtr setter: TIOCMBIS/TIOCMBIC
        raise PermissionError(_RO)

    def _set_rs485_mode(self, rs485_settings: object) -> None:  # TIOCSRS485
        raise PermissionError(_RO)

    def set_input_flow_control(self, enable: bool = True) -> None:  # tcflow TCION/TCIOFF: TX
        raise PermissionError(_RO)

    def set_output_flow_control(self, enable: bool = True) -> None:  # tcflow TCOON/TCOOFF
        raise PermissionError(_RO)

    @serial.Serial.rs485_mode.setter
    def rs485_mode(self, rs485_settings: object) -> None:
        if rs485_settings is not None:
            raise PermissionError(_RO)
        self._rs485_mode = None

    @serial.Serial.xonxoff.setter
    def xonxoff(self, xonxoff: bool) -> None:  # IXOFF: the tty would transmit XOFF/XON
        if xonxoff:
            raise PermissionError(_RO)
        self._xonxoff = False  # never enabled, so nothing to reconfigure

    @serial.Serial.rtscts.setter
    def rtscts(self, rtscts: bool) -> None:  # CRTSCTS: the kernel drives RTS
        if rtscts:
            raise PermissionError(_RO)
        self._rtscts = False  # never enabled, so nothing to reconfigure


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
