# Rebuild the tablet box: run from cad/boite with
#   freecadcmd -c "exec(open('build_boite.py').read())"
# -> checks report on stdout, STL in ../../stl/boite, STEP in build/, FCStd here.
import os, Mesh, Part
exec(open("x35_tablet_box.py").read())
stl = os.path.join(OUT, "..", "..", "stl", "boite"); os.makedirs(stl, exist_ok=True)
os.makedirs(os.path.join(OUT, "build"), exist_ok=True)
pr = doc.getObject("Pieces_imprimees").Group
for o in pr:
    Mesh.export([o], os.path.join(stl, o.Label + ".stl"))
Part.export(pr, os.path.join(OUT, "build", "x35_tablet_box.step"))
doc.saveAs(os.path.join(OUT, "X35_TabletBox.FCStd"))
print("EXPORT OK")
