"""jabuka-touch: French touchscreen menu for the MHS35 3.5" screen of the Jabuka Pi.

Runs with the system python (/usr/bin/python3, Pillow + numpy from apt) as the separate unit
jabuka-touch.service. It only reads the core's HTTP API and calls existing commands from a fixed
whitelist: a crash of the menu never affects navigation (jabuka-core, jabuka-ingest-fastnet).
The package never imports ``jabuka`` (except demo_wind.py, run by the venv python as jabuka).
"""

__version__ = "1.0"
