"""Navigation engine (Phase 2): geometry, polar, true wind, laylines, course, settings.

Pure modules: no clock reads (time is passed in, tests/test_no_wallclock.py scans this package);
file I/O only in course.py and settings.py, through jabuka.common.atomicio.
Internal units: radians, m/s, degrees for lat/lon. Distances in nautical miles, speeds handed to the
layline maths in knots (nm/h).
"""
