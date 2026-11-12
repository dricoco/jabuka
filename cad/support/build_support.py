# Rebuild the X35 tablet mount: run from cad/support with
#   freecadcmd -c "exec(open('build_support.py').read())"
# -> checks report on stdout, STL in ../../stl/support, STEP in build/, FCStd here.
import time, os
t0 = time.time()
exec(open("x35_tablet_mount_v5.py").read())
import Part, Mesh
from FreeCAD import Vector as V
stl = os.path.join(OUT, "..", "..", "stl", "support"); os.makedirs(stl, exist_ok=True)
os.makedirs(os.path.join(OUT, "build"), exist_ok=True)
pr = doc.getObject("Printed_Parts").Group
for o in pr:
    Mesh.export([o], os.path.join(stl, o.Label + ".stl"))
Part.export(pr, os.path.join(OUT, "build", "x35_tablet_mount_v5.step"))
# dovetail test coupon: end of the beam groove (slot + serrations) + one slider
pb = PARTS["Poutre"][0]; bbp = pb.BoundBox
cp = pb.common(Part.makeBox(30, 40, bbp.ZLength + 2, V(bbp.XMax - 30, bbp.YMin - 1, bbp.ZMin - 1)))
for n, sh in (("TEST_Poutre_bout", cp), ("TEST_Coulisseau", PARTS["Coulisseau_S"][0])):
    o = doc.addObject("Part::Feature", n); o.Shape = sh
    Mesh.export([o], os.path.join(stl, n + ".stl"))
    doc.removeObject(n)
for n, sh in KNOBS.items():                       # printed star knobs, print orientation
    o = doc.addObject("Part::Feature", n); o.Shape = sh
    Mesh.export([o], os.path.join(stl, n + ".stl"))
    doc.removeObject(n)
doc.saveAs(os.path.join(OUT, "X35_TabletMount_v5.FCStd"))
print("elapsed", round(time.time() - t0))
