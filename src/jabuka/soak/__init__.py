"""Soak harness (plan 04-01, REL-02): the real Jabuka processes under SimClock at ~60x, a seeded
fault schedule, a WebSocket "tablet" checking recovery, /proc probes and a JSON + Markdown report.

Entry point: ``python -m jabuka.tools.soak --scenario NAME`` (``jabuka-soak``). Dev/bench tool:
never part of a systemd unit.
"""
