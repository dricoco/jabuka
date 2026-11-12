# Renders the assembly-manual step images (cad/bom/img/m_*.png) in the FreeCAD GUI.
# Run inside the FreeCAD GUI (Python console or MCP) with the two model .FCStd files available:
#   exec(open('/path/to/cad/bom/manual_scenes.py').read())
# Exploded IKEA-style views: parts already mounted in grey, parts of the step in orange,
# hardware in steel, red arrows for the assembly direction.
import math, os
import FreeCAD as App, FreeCADGui as Gui, Part
from FreeCAD import Vector as V, Placement, Rotation

BOM = globals().get("MANUAL_BOM_DIR", "/home/drico/git/jabuka/cad/bom")   # set MANUAL_BOM_DIR before exec if the repo lives elsewhere
CAD = os.path.dirname(BOM)
IMG = os.path.join(BOM, "img")


def params(path):
    src = open(path).read()
    ns = {"__name__": "params"}
    cwd = os.getcwd()
    os.chdir(os.path.dirname(path))
    try:
        exec(src.split("\ndef build(")[0], ns)
    finally:
        os.chdir(cwd)
    return ns


SP = params(os.path.join(CAD, "support", "x35_tablet_mount_v5.py"))
BP = params(os.path.join(CAD, "boite", "x35_tablet_box.py"))


def opendoc(path, name):
    for d in list(App.listDocuments().values()):
        if d.Name == name:
            App.closeDocument(d.Name)
    return App.openDocument(path)


DS = opendoc(os.path.join(CAD, "support", "X35_TabletMount_v5.FCStd"), "X35_TabletMount_v5")
DB = opendoc(os.path.join(CAD, "boite", "X35_TabletBox.FCStd"), "X35_TabletBox")


def S(name):
    return DS.getObject(name).Shape.copy()


def Bx(name, glob=False):
    s = DB.getObject(name).Shape.copy()
    if glob:
        s.translate(V(0, SP["YA"] + SP["TILT_ARM"] + SP["VESA_T"], SP["H_T"]))
    return s


def mv(s, d):
    s = s.copy()
    s.translate(d)
    return s


# ---------------- hardware models (p = bearing point under the head / nut centre, d = screwing direction) ----------------
AF = {3: 5.5, 4: 7.0, 6: 10.0, 8: 13.0}


def rot_to(d):
    return Rotation(V(0, 0, 1), V(d).normalize())


def hexprism(af, h, p, d, centred=False):
    r = af / math.sqrt(3)
    pts = [V(r * math.cos(math.radians(60 * i + 30)), r * math.sin(math.radians(60 * i + 30)), 0) for i in range(7)]
    s = Part.Face(Part.makePolygon(pts)).extrude(V(0, 0, h))
    if centred:
        s.translate(V(0, 0, -h / 2))
    s.Placement = Placement(p, rot_to(d))
    return s


def bolt(p, d, L, M):
    d = V(d).normalize()
    sh = Part.makeCylinder(M / 2, L, p, d)
    hd = hexprism(AF[M], 0.7 * M, p - d * (0.7 * M), d)
    return sh.fuse(hd)


def cskscrew(p, d, L, M):
    d = V(d).normalize()
    sh = Part.makeCylinder(M / 2, L, p, d)
    hd = Part.makeCone(M, M / 2, M / 2, p, d)
    return sh.fuse(hd)


def nut(p, d, M):
    d = V(d).normalize()
    n = hexprism(AF[M], 0.8 * M, p, d, centred=True)
    return n.cut(Part.makeCylinder(M / 2, 2 * M, p - d * M, d))


def washer(p, d, M, od=None, t=1.6):
    d = V(d).normalize()
    od = od or 2 * M
    w = Part.makeCylinder(od / 2, t, p - d * t, d)
    return w.cut(Part.makeCylinder(M / 2 + 0.2, 3 * t, p - d * 2 * t, d))


def knob(p, d, L):
    """M8 star knob: 5-lobe head (dia ~38) behind p, threaded stud L along d"""
    d = V(d).normalize()
    head = Part.makeCylinder(11, 14, V(0, 0, -14))
    for i in range(5):
        a = math.radians(72 * i)
        head = head.fuse(Part.makeCylinder(6.5, 14, V(13 * math.cos(a), 13 * math.sin(a), -14)))
    head.Placement = Placement(p, rot_to(d))
    return head.fuse(Part.makeCylinder(4, L, p, d))


def arrow(tail, head, r=1.6):
    d = head - tail
    Lt = d.Length
    d.normalize()
    hl = min(4.5 * r * 2, Lt * 0.45)
    s = Part.makeCylinder(r, Lt - hl, tail, d)
    return s.fuse(Part.makeCone(2.6 * r, 0, hl, tail + d * (Lt - hl), d))


def guide(a, b, r=0.35):
    d = b - a
    return Part.makeCylinder(r, d.Length, a, d)


# ---------------- scene rendering ----------------
GREY, ORA, STEEL, DARK, RED, RUBBER, BLUE, FOAMC = ((0.82, 0.82, 0.82), (0.96, 0.55, 0.13), (0.55, 0.60, 0.68),
                                                   (0.12, 0.12, 0.12), (0.85, 0.08, 0.08), (0.18, 0.18, 0.18),
                                                   (0.15, 0.25, 0.45), (0.35, 0.35, 0.35))
LEGC = (0.70, 0.74, 0.80)


def scene(fname, items, view, w=1500, h=1100, zoom=1.0):
    if "Manuel" in App.listDocuments():
        App.closeDocument("Manuel")
    doc = App.newDocument("Manuel")
    for i, (shape, col) in enumerate(items):
        o = doc.addObject("Part::Feature", "o%02d" % i)
        o.Shape = shape
        vo = o.ViewObject
        vo.ShapeColor = col
        vo.LineColor = (0.15, 0.15, 0.15) if col not in (RED,) else RED
        vo.LineWidth = 1.0
        if col == LEGC:
            vo.Transparency = 35
    doc.recompute()
    Gui.ActiveDocument.ActiveView.setCameraType("Orthographic")
    v = Gui.ActiveDocument.ActiveView
    from pivy import coin                         # camera looks along `view`, world z stays up on screen
    d = V(view).normalize()
    c = V(0, 0, 0)
    for o in doc.Objects:
        c += o.Shape.BoundBox.Center
    c = c * (1.0 / len(doc.Objects))
    cam = v.getCameraNode()
    p = c - d * 3000
    cam.position.setValue(coin.SbVec3f(p.x, p.y, p.z))
    cam.pointAt(coin.SbVec3f(c.x, c.y, c.z), coin.SbVec3f(0, 0, 1))
    v.fitAll()
    if zoom != 1.0:
        cam = v.getCameraNode()
        cam.height.setValue(cam.height.getValue() / zoom)
    Gui.updateGui()
    v.saveImage(os.path.join(IMG, fname + ".png"), w, h, "White")
    return fname


ISO_AFT = V(-0.75, -1.0, -0.62)       # looking from aft (+y), starboard (+x), above
ISO_AFT_P = V(0.75, -1.0, -0.62)      # from aft, port side
ISO_FWD = V(-0.7, 1.0, -0.55)         # from forward, starboard, above
ISO_FWD_P = V(0.7, 1.0, -0.55)

YA, H_T, Z_Y = SP["YA"], SP["H_T"], SP["Z_Y"]
ZC, HB, XS = SP["Z_CLAMP"], SP["HB"], SP["XS"]
NUT_T, NUT_AF = SP["NUT_T"], SP["NUT_AF"]
YB_BOLTS = (YA - 6.0, YA + 18.0)
ZF0 = ZC + HB
YV = YA + SP["TILT_ARM"]
Y_BEAM_AFT = S("Poutre").BoundBox.YMax
done = []

# ---- 1a: M6 nuts into the beam ----
it = [(S("Poutre"), ORA)]
for x in (-36.0, 36.0):
    for yb in YB_BOLTS:
        c = V(x, yb, ZF0 - 3.5 - NUT_T / 2)
        out = V(math.copysign(1, x), 0, 0)
        fin = c + out * (45 - abs(x) + 12)
        it += [(nut(fin, V(0, 0, 1), 6), STEEL), (arrow(fin + out * 8, fin + out * -(45 - abs(x) + 3) + out * 8), RED)]
done.append(scene("m_1a_poutre_ecrous", it, V(-0.35, -1.0, -0.8)))

# ---- 1b: M6 nut into a cradle ----
sx = 1
pl = SP["clamp_pl"](sx, ZC)
yap = SP["RB"] * math.sqrt(2)
cn = pl.multVec(V(0, yap + 1.0 + NUT_T / 2, 0))
slide = pl.Rotation.multVec(V(1, 0, 0))
fin = cn + slide * 45
it = [(S("Berceau_S"), ORA), (nut(fin, V(0, 1, 0), 6), STEEL), (arrow(fin - slide * 9, cn + slide * 34), RED)]
done.append(scene("m_1b_berceau_ecrou", it, V(-0.9, -0.55, -0.45)))

# ---- 1c: M8 nut into the column ----
cn = V(0, YA, Z_Y - 32 + 3.5)
fin = cn + V(70, 0, 0)
it = [(S("Column"), ORA), (nut(fin, V(0, 0, 1), 8), STEEL), (arrow(fin - V(10, 0, 0), cn + V(40, 0, 0)), RED)]
done.append(scene("m_1c_colonne_ecrou", it, V(-1.0, -0.6, -0.45)))

# ---- 1d: M8 nut into the VESA head ----
cn = V(28 - 3.5, YA, H_T)
fin = cn + V(45, 0, 0)
it = [(S("VESA_Head"), ORA), (nut(fin, V(1, 0, 0), 8), STEEL), (arrow(fin - V(8, 0, 0), cn + V(10, 0, 0)), RED)]
done.append(scene("m_1d_tete_ecrou", it, V(-1.0, 0.5, -0.4)))

# ---- 2: sliders into the dovetail ----
it = [(S("Poutre"), GREY)]
for tag, sx in (("S", 1), ("P", -1)):
    c = S("Coulisseau_" + tag)
    off = V(sx * 105, 0, 0)
    it += [(mv(c, off), ORA), (arrow(V(sx * (XS + 140), c.BoundBox.Center.y - 22, ZC), V(sx * (XS + 70), c.BoundBox.Center.y - 22, ZC), 2.0), RED)]
done.append(scene("m_2_coulisseaux", it, V(-0.45, -1.0, -0.5)))

# ---- 3: cradles onto the sliders, pivot bolts ----
it = [(S("Poutre"), GREY), (S("Coulisseau_S"), GREY), (S("Coulisseau_P"), GREY)]
for tag, sx in (("S", 1), ("P", -1)):
    it.append((mv(S("Berceau_" + tag), V(0, -45, 0)), ORA))
    pb = V(sx * XS, Y_BEAM_AFT, ZC)
    e = V(0, 55, 0)
    it += [(bolt(pb + e + V(0, 1.6, 0), V(0, -1, 0), 45, 6), STEEL), (washer(pb + e * 0.55, V(0, -1, 0), 6, 18), STEEL),
           (guide(pb + e * 0.5, pb - V(0, 60, 0)), RED),
           (arrow(V(sx * XS, 70, ZC - 45), V(sx * XS, 105, ZC - 45), 2.0), RED)]
done.append(scene("m_3_berceaux_pivots", it, V(-0.65, -1.0, -0.45)))

# ---- 3b: the pivot stack along the bolt axis (one side): bolt > washer > beam > slider > cradle > nut ----
cut = Part.makeBox(90, 400, 200, V(XS - 45, -100, ZC - 100))
yap = SP["RB"] * math.sqrt(2)
pl = SP["clamp_pl"](1, ZC)
nut_c = pl.multVec(V(0, yap + 1.0 + NUT_T / 2, 0))
e_sl, e_cr, e_bolt = V(0, -35, 0), V(0, -80, 0), V(0, 45, 0)
pb = V(XS, Y_BEAM_AFT, ZC)
it = [(S("Poutre").common(cut), GREY),
      (mv(S("Coulisseau_S"), e_sl), ORA),
      (mv(S("Berceau_S"), e_cr), ORA),
      (nut(nut_c + e_cr + pl.Rotation.multVec(V(1, 0, 0)) * 45, V(0, 1, 0), 6), STEEL),
      (arrow(nut_c + e_cr + pl.Rotation.multVec(V(1, 0, 0)) * 39, nut_c + e_cr + pl.Rotation.multVec(V(1, 0, 0)) * 33, 1.2), RED),
      (bolt(pb + e_bolt + V(0, 1.6, 0), V(0, -1, 0), 45, 6), STEEL),
      (washer(pb + e_bolt * 0.5, V(0, -1, 0), 6, 18), STEEL),
      (guide(pb + e_bolt * 0.5, nut_c + e_cr), RED)]
done.append(scene("m_3b_empilage_pivot", it, V(-1.0, -0.25, -0.35)))

# ---- 4: on the pedestal, rubber + hose clamps ----
legs = [DS.getObject(n).Shape.copy() for n in ("Leg_aft_S", "Leg_aft_P")]
clip = Part.makeBox(800, 200, 220, V(-400, -50, ZC - 110))
it = [(l.common(clip), LEGC) for l in legs]
it += [(S(n), GREY) for n in ("Poutre", "Coulisseau_S", "Coulisseau_P", "Berceau_S", "Berceau_P")]
it += [(DS.getObject(n).Shape.copy(), STEEL) for n in ("Collier_inox_S1", "Collier_inox_S2", "Collier_inox_P1", "Collier_inox_P2")]
done.append(scene("m_4_pietement", it, V(-0.55, 1.0, -0.35)))
done.append(scene("m_4_pietement_arriere", it, V(-0.45, -1.0, -0.3)))

# ---- 5: column on the beam, 4 x M6x20 ----
it = [(S(n), GREY) for n in ("Poutre", "Coulisseau_S", "Coulisseau_P", "Berceau_S", "Berceau_P")]
up = V(0, 0, 70)
it.append((mv(S("Column"), up), ORA))
for x in (-36.0, 36.0):
    for yb in YB_BOLTS:
        p = V(x, yb, ZF0 + 10) + up + V(0, 0, 40)
        it += [(bolt(p + V(0, 0, 1.6), V(0, 0, -1), 20, 6), STEEL), (washer(p, V(0, 0, -1), 6), STEEL),
               (guide(p, V(x, yb, ZF0 - 2)), RED)]
it.append((arrow(V(-80, YA, ZF0 + 120), V(-80, YA, ZF0 + 40), 2.0), RED))
it.append((arrow(V(60, YA - 40, ZF0 + 3), V(60, YA + 10, ZF0 + 3), 1.6), RED))
done.append(scene("m_5_colonne", it, V(-0.8, -1.0, -0.55)))

# ---- 6: tower + yaw knob ----
it = [(S(n), GREY) for n in ("Poutre", "Column")]
up = V(0, 0, 60)
it.append((mv(S("Tower"), up), ORA))
kp = V(0, YA, Z_Y + 14.2) + up + V(0, 0, 60)
it += [(knob(kp, V(0, 0, -1), 50), DARK), (guide(kp, V(0, YA, Z_Y - 30)), RED),
       (arrow(V(-55, YA, Z_Y + 120), V(-55, YA, Z_Y + 40), 2.0), RED)]
done.append(scene("m_6_tour", it, V(-0.8, -1.0, -0.45)))

# ---- 7: VESA head + tilt knob ----
it = [(S(n), GREY) for n in ("Column", "Tower")]
off = V(60, 0, 0)
it.append((mv(S("VESA_Head"), off), ORA))
kp = V(-14, YA, H_T) - V(55, 0, 0)
it += [(knob(kp, V(1, 0, 0), 45), DARK), (guide(kp, V(28, YA, H_T) + off), RED),
       (arrow(V(110, YA - 20, H_T + 80), V(55, YA - 20, H_T + 80), 2.0), RED)]
done.append(scene("m_7_tete_vesa", it, V(-0.55, -1.0, -0.4)))

# ---- 8a: M3 nuts into the box (from the tablet pocket) ----
FR_X, ZS, PZ, Y_RIM, NW = BP["FR_X"], BP["Z_SCREW"], BP["PZ"], BP["Y_RIM"], BP["N_WALL"]
it = [(Bx("Boite"), ORA)]
for x in FR_X:
    for z in (-ZS, ZS):
        c = V(x, Y_RIM - NW - BP["N3_T"] / 2, z)
        fin = c - V(0, 0, math.copysign(32, z))
        it += [(nut(fin, V(0, 1, 0), 3), STEEL), (arrow(fin + V(0, 0, math.copysign(5, z)), c - V(0, 0, math.copysign(9, z)), 1.0), RED)]
done.append(scene("m_8a_boite_ecrous", it, V(-0.35, -1.0, -0.55)))

# ---- 8b: M4 + M3 nuts into the power bank pod (from the bank cavity) ----
MOD_D, OZ, N4T, N3T = BP["MOD_D"], BP["OZ"], BP["N4_T"], BP["N3_T"]
it = [(Bx("Module_powerbank"), ORA)]
for x in (-50.0, 50.0):
    sg = math.copysign(1, x)
    for y, z in ((NW + N4T / 2, -50.0), (NW + N4T / 2, 50.0), (MOD_D - NW - N4T / 2, -75.0), (MOD_D - NW - N4T / 2, 75.0)):
        c = V(x, y, z)
        fin = c - V(sg * 28, 0, 0)
        it += [(nut(fin, V(0, 1, 0), 4), STEEL), (arrow(fin + V(sg * 5, 0, 0), c - V(sg * 7, 0, 0), 1.0), RED)]
    c = V(x, 7.0, -OZ + NW + N3T / 2)
    fin = c - V(sg * 28, 0, 0)
    it += [(nut(fin, V(0, 0, 1), 3), STEEL), (arrow(fin + V(sg * 5, 0, 0), c - V(sg * 7, 0, 0), 1.0), RED)]
done.append(scene("m_8b_module_ecrous", it, V(-0.45, -1.0, 0.35)))

# ---- 9: box on the pod (4 x M4x12 csk from inside the pocket) + power button plunger ----
Y_B1 = BP["Y_B1"]
it = [(Bx("Module_powerbank"), GREY)]
e = V(0, 45, 0)
it.append((mv(Bx("Boite"), e), ORA))
it.append((mv(Bx("Poussoir"), e + V(0, 0, 0)), ORA))
for x in (-50.0, 50.0):
    for z in (-75.0, 75.0):
        p = V(x, Y_B1, z) + e + V(0, 35, 0)
        it += [(cskscrew(p, V(0, -1, 0), 12, 4), STEEL), (guide(p, V(x, MOD_D - 8, z)), RED)]
it.append((arrow(V(-150, 75, 0), V(-150, 35, 0), 2.0), RED))
done.append(scene("m_9_boite_module", it, V(-0.45, -1.0, -0.45)))

# ---- 10: foam, tablet, frame (8 x M3x10 csk) ----
Y_FR, Y_T0 = BP["Y_FR"], BP["Y_T0"]
it = [(Bx(n), GREY) for n in ("Module_powerbank", "Boite", "Poussoir")]
foam = Part.makeBox(230, 1.5, 150, V(-115, Y_T0 - 1.5, -75 + BP["ZC"]))
e1, e2 = V(0, 30, 0), V(0, 75, 0)
it += [(mv(foam, V(0, 12, 0)), FOAMC), (mv(Bx("Tablette"), e1), BLUE), (mv(Bx("Ecran_actif"), e1), (0.05, 0.05, 0.08)),
       (mv(Bx("Cadre"), e2), ORA)]
for x in FR_X:
    for z in (-ZS, ZS):
        p = V(x, Y_FR, z) + e2 + V(0, 30, 0)
        it += [(cskscrew(p, V(0, -1, 0), 10, 3), STEEL), (guide(p, V(x, Y_RIM - 6, z)), RED)]
done.append(scene("m_10_tablette_cadre", it, V(-0.5, -1.0, -0.4)))

# ---- 11: power bank + bottom cap (2 x M3x12 csk) ----
it = [(Bx(n), GREY) for n in ("Module_powerbank", "Boite", "Cadre")]
dn1, dn2 = V(0, 0, -60), V(0, 0, -130)
it += [(mv(Bx("Powerbank"), dn1), BLUE), (mv(Bx("Bouchon"), dn2), ORA)]
for x in (-50.0, 50.0):
    p = V(x, 7.0, -OZ - 4) + dn2 - V(0, 0, 30)
    it += [(cskscrew(p, V(0, 0, 1), 12, 3), STEEL), (guide(p, V(x, 7.0, -OZ + 6)), RED)]
it.append((arrow(V(-100, 10, -OZ - 150), V(-100, 10, -OZ - 60), 2.0), RED))
done.append(scene("m_11_powerbank_bouchon", it, V(-0.6, -1.0, 0.55)))

# ---- 12: box on the VESA head (4 x M4x16 + washer, from the head side) ----
it = [(S(n), GREY) for n in ("Poutre", "Column", "Tower", "VESA_Head", "Knob_yaw_M8")]
it.append((knob(V(-14, YA, H_T), V(1, 0, 0), 45), DARK))
e = V(0, 50, 0)
for n in ("Module_powerbank", "Boite", "Cadre", "Bouchon"):
    it.append((mv(Bx(n, True), e), ORA))
it.append((mv(Bx("Tablette", True), e), BLUE))
for x in (-50.0, 50.0):
    for z in (-50.0, 50.0):
        p = V(x, YV, H_T + z) - V(0, 35, 0)
        it += [(bolt(p - V(0, 1.6, 0), V(0, 1, 0), 16, 4), STEEL), (washer(p, V(0, 1, 0), 4), STEEL),
               (guide(p, V(x, YV + 60, H_T + z)), RED)]
done.append(scene("m_12_boite_sur_tete", it, V(-0.7, 1.0, -0.4)))

# ---- 13: finished ----
it = [(l.common(Part.makeBox(800, 300, 450, V(-400, -100, ZC - 110))), LEGC) for l in legs]
it += [(S(n), ORA) for n in ("Poutre", "Coulisseau_S", "Coulisseau_P", "Berceau_S", "Berceau_P", "Column", "Tower", "VESA_Head")]
it += [(DS.getObject(n).Shape.copy(), STEEL) for n in ("Collier_inox_S1", "Collier_inox_S2", "Collier_inox_P1", "Collier_inox_P2")]
it += [(DS.getObject("Knob_yaw_M8").Shape.copy(), DARK), (knob(V(-14, YA, H_T), V(1, 0, 0), 45), DARK)]
for n in ("Module_powerbank", "Boite", "Cadre", "Bouchon"):
    it.append((Bx(n, True), ORA))
done.append(scene("m_13_fini", it, V(-0.8, -1.0, -0.45)))
print("rendered", done)
