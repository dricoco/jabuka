"""Soak finding (plan 04-01, kill-core): the closed-loop helmsman must survive the core dying in
the middle of an HTTP answer. The synth crashed with http.client.IncompleteRead (an
HTTPException, not an OSError), which stopped the whole soak."""

from __future__ import annotations

import socket
import threading

from jabuka.sim.synth import FollowHelm


def _one_shot_server(payload: bytes) -> tuple[int, threading.Thread]:
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def serve() -> None:
        conn, _ = srv.accept()
        with conn:
            conn.recv(4096)
            conn.sendall(payload)  # then close: the client sees a short body
        srv.close()

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    return port, th


def test_fetch_survives_a_truncated_answer() -> None:
    port, th = _one_shot_server(
        b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2512\r\n\r\n{"ty'
    )
    helm = FollowHelm(f"http://127.0.0.1:{port}", 45.0)
    assert helm.fetch() is None
    assert helm.fetch_errors == 1
    th.join(timeout=5)


def test_fetch_survives_a_garbled_status_line() -> None:
    port, th = _one_shot_server(b"NOT-HTTP\r\n\r\n")
    helm = FollowHelm(f"http://127.0.0.1:{port}", 45.0)
    assert helm.fetch() is None
    assert helm.fetch_errors == 1
    th.join(timeout=5)
