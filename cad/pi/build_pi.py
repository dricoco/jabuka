# Rebuild the Pi box: run from cad/pi with
#   freecadcmd -c "exec(open('build_pi.py').read())"
# -> checks report on stdout, STL in ../../stl/pi, STEP in build/, FCStd here.
import os, Mesh, Part
exec(open("x35_pi_box.py").read())
stl = os.path.join(OUT, "..", "..", "stl", "pi"); os.makedirs(stl, exist_ok=True)
os.makedirs(os.path.join(OUT, "build"), exist_ok=True)
pr = doc.getObject("Pieces_imprimees").Group
for o in pr:
    Mesh.export([o], os.path.join(stl, o.Label + ".stl"))
Part.export(pr, os.path.join(OUT, "build", "x35_pi_box.step"))
doc.saveAs(os.path.join(OUT, "X35_PiBox.FCStd"))
print("EXPORT OK")
