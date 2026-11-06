"""Local demo (quick 001): the whole synthetic stack on this computer, for a desktop browser.

    python -m jabuka.tools.demo                 # http://127.0.0.1:8080/
    python -m jabuka.tools.demo --lan           # also reachable from a phone/tablet on the Wi-Fi
    bash scripts/demo.sh --speed 1              # same, through the repo's .venv

What runs (the rehearsal's synthetic boat, jabuka.tools.rehearsal):

- jabuka-core on --clock sim, reading the synth's fake gpsd, bound to 127.0.0.1 (0.0.0.0 with
  --lan) on --port (8080). The core's Host check accepts localhost and any IP literal, so the LAN
  address works as is.
- jabuka-sim in pty mode with its embedded fake gpsd: an X35 starting 2 nm downwind of Plić
  Sestre (Course A, first mark) in 12 kn from 161°, veering --shift °/h, sailing the core's own
  route (--follow --follow-route; the laylines while there is no route yet): it beats, tacks where
  the route says, rounds the mark and carries on to Jabuka. --speed sim seconds per real second
  (2 by default, so it feels live).
- jabuka-ingest-fastnet reading the synth's Fastnet bytes from the pty.

The race pack (one directory, --racepack: the map and the routing files live together) is built
under OUT/racepack: the real map from var/racepack/ when it is there (race.pmtiles,
coastline.geojson, seamarks.geojson, racepack.json), else the test map of the Šibenik area; the
rehearsal's land mask; a wind.npz matching the synth's wind (same direction, speed and veer).

OUT (var/demo by default) is wiped on every start, and only when it carries the demo marker or is
empty. Ctrl-C (or SIGTERM) stops every child; the children's logs are kept in OUT/logs.
Dev tool only (never in a systemd unit); it may read the wall clock.
"""

from __future__ import annotations

import argparse
import math
import shutil
import signal
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

from jabuka.common.atomicio import atomic_write_bytes
from jabuka.tools.rehearsal import (
    BOAT_START_UTC,
    BOAT_TWA,
    BOAT_TWD,
    BOAT_TWS,
    DEFAULT_CAPTURE,
    PLIC,
    REPO,
    BoatStack,
    Context,
    StackError,
    synth_args,
    wait_for,
    write_boat_pack,
)

DEFAULT_OUT = REPO / "var" / "demo"
REAL_MAP = REPO / "var" / "racepack"
FIXTURE_MAP = REPO / "tests" / "fixtures" / "map"
MAP_FILES = ("race.pmtiles", "coastline.geojson", "seamarks.geojson", "racepack.json")
MARKER = ".jabuka-demo"
START_NM, START_BRG = 2.0, 341.0  # downwind of Plić Sestre: a clear beat (rehearsal/UI tests)


class DemoError(Exception):
    pass


def reset_out(out: Path) -> None:
    """Empty OUT for a fresh demo, refusing to wipe a directory the demo did not create."""
    if out.exists():
        if not out.is_dir():
            raise DemoError(f"{out} existe et n'est pas un dossier")
        if not (out / MARKER).is_file() and any(out.iterdir()):
            raise DemoError(
                f"{out} existe et n'est pas un dossier de démo (pas de {MARKER}) : refus de "
                "l'effacer, choisir --out"
            )
        shutil.rmtree(out)
    out.mkdir(parents=True)
    atomic_write_bytes(out / MARKER, b"jabuka demo data, wiped on every start\n")


def build_pack(
    pack: Path, map_dir: Path | None, start: datetime, twd: float, tws: float, shift: float
) -> str:
    """Race pack for the demo; returns a French line saying which map it uses."""
    write_boat_pack(pack, start, twd=twd, tws=tws, shift_deg_h=shift)
    src = map_dir if map_dir is not None else REAL_MAP
    if (src / "race.pmtiles").is_file():
        for name in MAP_FILES:
            if (src / name).is_file():
                shutil.copyfile(src / name, pack / name)
        return f"carte réelle ({src})"
    if map_dir is not None:
        raise DemoError(f"pas de race.pmtiles dans {map_dir}")
    shutil.copyfile(FIXTURE_MAP / "sibenik.pmtiles", pack / "race.pmtiles")
    shutil.copyfile(FIXTURE_MAP / "seamarks-mini.geojson", pack / "seamarks.geojson")
    return "carte de test (zone de Šibenik, var/racepack/ absent)"


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def lan_ips() -> list[str]:
    """This computer's IPv4 addresses on the local network (no packet is sent)."""
    ips: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.append(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = str(info[4][0])
            if ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith("127.") and ip != "0.0.0.0"]


class Demo:
    def __init__(self, args: argparse.Namespace, echo=print) -> None:
        self.args = args
        self.echo = echo
        self.out = Path(args.out).resolve()
        self.host = "0.0.0.0" if args.lan else "127.0.0.1"
        self.ctx: Context | None = None
        self.stack: BoatStack | None = None

    def start(self) -> None:
        a = self.args
        if not port_free(self.host, a.port):
            raise DemoError(f"le port {a.port} est déjà utilisé : relancer avec --port AUTRE")
        reset_out(self.out)
        self.ctx = Context(out=self.out, capture=DEFAULT_CAPTURE, mode="quick")
        self.stack = BoatStack(self.ctx, root=self.out, http_port=a.port, http_host=self.host)
        st = self.stack
        start = BOAT_START_UTC
        carte = build_pack(st.pack, a.map, start, BOAT_TWD, BOAT_TWS, a.shift)
        self.echo(f"  {carte}")
        self.echo("  démarrage de jabuka-core…")
        st._spawn_core()
        st.variation = float(st.client.get("/api/settings").json()["settings"]["variation_deg"])
        from jabuka.nav import geo

        lat, lon = geo.offset(*PLIC, math.radians(START_BRG), START_NM)
        self.echo(f"  démarrage du bateau de synthèse (vitesse ×{a.speed:g})…")
        st.synth = self.ctx.spawn(
            "demo-synth",
            "jabuka.sim.synth",
            *synth_args(
                st.link,
                st.gpsd,
                (lat, lon),
                start,
                speed=a.speed,
                variation=st.variation,
                twd=BOAT_TWD,
                tws=BOAT_TWS,
                twa=BOAT_TWA,
                duration_s=10 * 86400,
                shift_deg_h=a.shift,
                follow=f"http://127.0.0.1:{a.port}",
                follow_route=True,
            ),
        )
        if not wait_for(st.link.is_symlink, 15):
            raise DemoError("jabuka-sim n'a pas créé le pty")
        self.echo("  démarrage de jabuka-ingest-fastnet…")
        st._spawn_ingest()
        if not st.wait_source("LIVE", 45):
            raise DemoError(f"pas de vent LIVE après 45 s : {st.nav().get('wind')}")

    def route_state(self) -> str | None:
        """The core's route state ("ok", "computing"...), None when it does not answer."""
        st = self.stack
        try:
            return (st.nav().get("route") or {}).get("state") if st is not None else None
        except Exception:  # noqa: BLE001 - the core may be busy: ask again later
            return None

    def alive(self) -> str | None:
        """Name of a child that died, or None."""
        st = self.stack
        if st is None:
            return None
        procs = (("jabuka-core", st.core), ("jabuka-sim", st.synth), ("ingest", st.ingest))
        for name, proc in procs:
            if proc is not None and proc.poll() is not None:
                return f"{name} (code {proc.returncode})"
        return None

    def stop(self) -> None:
        if self.stack is not None:
            try:
                self.stack.stop()
            except Exception as e:  # noqa: BLE001 - keep stopping the others
                self.echo(f"  arrêt : {e}")
        if self.ctx is not None:
            self.ctx.stop_all()
            try:
                self.ctx.save_logs()
            except OSError:
                pass


def urls(port: int, lan: bool) -> list[str]:
    out = [f"http://127.0.0.1:{port}/", f"http://localhost:{port}/"]
    if lan:
        out += [f"http://{ip}:{port}/" for ip in lan_ips()]
    return out


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jabuka-demo",
        description="Démo locale : core + bateau de synthèse + ingest, dans un navigateur.",
    )
    p.add_argument("--port", type=int, default=8080, help="port HTTP (défaut 8080)")
    p.add_argument(
        "--speed", type=float, default=2.0, help="secondes simulées par seconde réelle (défaut 2)"
    )
    p.add_argument(
        "--shift",
        type=float,
        default=6.0,
        help="rotation du vent en °/h, + = sens horaire (défaut 6)",
    )
    p.add_argument(
        "--lan",
        action="store_true",
        help="écouter sur 0.0.0.0 : ouvrable depuis un téléphone ou une tablette du même Wi-Fi",
    )
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="dossier de données (effacé)")
    p.add_argument(
        "--map", type=Path, default=None, help="dossier carte (défaut var/racepack/ si présent)"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.speed <= 0:
        print("--speed doit être > 0", file=sys.stderr)
        return 2

    def echo(line: str) -> None:
        print(line, flush=True)

    def on_term(signum, frame) -> None:  # noqa: ARG001
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_term)
    demo = Demo(args, echo)
    echo(f"JABUKA — démo locale (données dans {demo.out})")
    code = 0
    try:
        demo.start()
        t_live = time.monotonic()
        echo("")
        echo("Prêt. Ouvrir dans le navigateur :")
        for u in urls(args.port, args.lan):
            echo(f"    {u}")
        if not args.lan:
            echo("  (--lan pour l'ouvrir depuis un téléphone ou une tablette du même Wi-Fi)")
        echo("À voir : onglet Barre (cap/TWA cible, compte à rebours de virement, ON RESTE),")
        echo("la route et les lay-lines sur la carte, Réglages > Langue FR / EN / SL, Diag.")
        echo("Ctrl-C pour tout arrêter.")
        echo("")
        echo("Calcul de la première route (les lay-lines sont déjà là)…")
        routed = False
        while True:
            dead = demo.alive()
            if dead:
                echo(f"ARRÊT : {dead} s'est arrêté (journaux dans {demo.out / 'logs'})")
                code = 1
                break
            if not routed and demo.route_state() == "ok":
                routed = True
                echo(f"Route calculée ({time.monotonic() - t_live:.0f} s) : visible sur la Barre.")
            time.sleep(1.0)
    except KeyboardInterrupt:
        echo("")
        echo("Arrêt demandé…")
    except (DemoError, StackError) as e:
        echo(f"ÉCHEC : {e} (journaux dans {demo.out / 'logs'})")
        code = 1
    finally:
        demo.stop()
        echo("Tout est arrêté.")
    return code


if __name__ == "__main__":
    sys.exit(main())
