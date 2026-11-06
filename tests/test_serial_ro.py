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


# -- WR-01: O_RDONLY does not block line control; every pyserial path to it must raise ----------
LINE_CONTROL = [
    ("send_break()", lambda s: s.send_break()),
    ("send_break(0)", lambda s: s.send_break(0)),
    ("sendBreak()", lambda s: s.sendBreak()),
    ("break_condition=True", lambda s: setattr(s, "break_condition", True)),
    ("break_condition=False", lambda s: setattr(s, "break_condition", False)),
    ("rts=True", lambda s: setattr(s, "rts", True)),
    ("rts=False", lambda s: setattr(s, "rts", False)),
    ("dtr=True", lambda s: setattr(s, "dtr", True)),
    ("dtr=False", lambda s: setattr(s, "dtr", False)),
    ("setRTS()", lambda s: s.setRTS(1)),
    ("setDTR()", lambda s: s.setDTR(0)),
    ("rs485_mode=settings", lambda s: setattr(s, "rs485_mode", _rs485())),
    ("set_input_flow_control()", lambda s: s.set_input_flow_control(True)),
    ("set_input_flow_control(False)", lambda s: s.set_input_flow_control(False)),
    ("set_output_flow_control()", lambda s: s.set_output_flow_control(False)),
    ("xonxoff=True", lambda s: setattr(s, "xonxoff", True)),
    ("rtscts=True", lambda s: setattr(s, "rtscts", True)),
]


def _rs485():
    import serial.rs485

    return serial.rs485.RS485Settings()


@pytest.mark.parametrize("name,action", LINE_CONTROL, ids=[n for n, _ in LINE_CONTROL])
def test_line_control_raises(pty_pair, name, action) -> None:
    _, path = pty_pair
    ser = open_fastnet(path)
    try:
        with pytest.raises(PermissionError):
            action(ser)
    finally:
        ser.close()


@pytest.mark.parametrize("name,action", LINE_CONTROL, ids=[n for n, _ in LINE_CONTROL])
def test_line_control_raises_even_when_closed(name, action) -> None:
    """Setters are stored and applied on open; the methods refuse regardless of state."""
    ser = ReadOnlySerial()
    if name.split("=")[0].split("(")[0] in ("rts", "dtr", "break_condition", "setRTS", "setDTR"):
        action(ser)  # only stored while closed; open() never applies them (no TIOCM* on open)
        return
    with pytest.raises(PermissionError):
        action(ser)


def test_disabling_is_still_allowed(pty_pair) -> None:
    _, path = pty_pair
    ser = open_fastnet(path)
    try:
        ser.rs485_mode = None
        ser.xonxoff = False
        ser.rtscts = False
        assert ser.rs485_mode is None and not ser.xonxoff and not ser.rtscts
    finally:
        ser.close()


def test_open_turns_off_echo_and_flow_control(pty_pair) -> None:
    """A fresh ttyUSB is in cooked mode with ECHO: the line discipline would transmit every
    received byte back onto the bus. open() must leave echo and XON/XOFF off."""
    master, path = pty_pair
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
    try:
        attrs = termios.tcgetattr(fd)
        attrs[0] |= termios.IXON | termios.IXOFF
        attrs[3] |= termios.ECHO | termios.ICANON | termios.ECHONL
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    finally:
        os.close(fd)
    ser = open_fastnet(path)
    try:
        iflag, _o, _c, lflag = termios.tcgetattr(ser.fileno())[:4]
        assert not lflag & (termios.ECHO | termios.ICANON | termios.ECHONL)
        assert not iflag & (termios.IXON | termios.IXOFF)
        # behaviour: bus bytes in, nothing comes back out towards the bus
        os.write(master, b"\x01\x02\x03abc\n")
        import select
        import time

        time.sleep(0.05)
        r, _, _ = select.select([master], [], [], 0.1)
        assert r == [], os.read(master, 64)
    finally:
        ser.close()


# -- WR-04: exclusive open --------------------------------------------------------------------
def test_second_open_is_refused_without_touching_the_tty(pty_pair) -> None:
    from jabuka.ingest.serial_ro import PortBusyError

    _, path = pty_pair
    first = open_fastnet(path)
    try:
        before = termios.tcgetattr(first.fileno())
        with pytest.raises(PortBusyError):
            open_fastnet(path)
        assert termios.tcgetattr(first.fileno()) == before  # speed/flags untouched
    finally:
        first.close()
    again = open_fastnet(path)  # the lock goes with the fd
    again.close()
