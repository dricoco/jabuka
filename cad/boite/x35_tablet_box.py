# X35 tablet box (10.1" Feonal/Zonko K116) + power bank pod, for the X35 swivel mount.
# Printer: Bambu Lab A1 (256^3). Material: PETG. Seals: EPDM foam tape / bike inner tube.
# Local frame: x = width (same as mount x), y = 0 on the VESA face (back), +y towards the
# screen/helmsman, z = up, (0,0,0) = VESA centre = box centre. Units mm.
import os
import FreeCAD as App
import Part
from FreeCAD import Vector as V

OUT = os.getcwd()   # run from cad/boite (see build_boite.py)
BED = 256.0

# ---- tablet (spec sheet Feonal K116; [MEASURE]) ----
T_W, T_H, T_D, T_R = 235.0, 158.0, 7.9, 8.0
ACT_W, ACT_H = 217.0, 136.0     # visible screen (10.1" 16:10) [MEASURE]
# Feonal K116 photo: USB-C on a LONG edge near one corner, power/vol on the adjacent short edge.
# Landscape with that long edge DOWN -> port faces down. Viewer's left (seen from the screen) = +x.
PORT_FROM_CORNER = 29.5         # USB-C centre from the left-bottom corner seen from the screen (port starts 25 mm from the edge)
CLR = 2.0                       # clearance tablet-in-bag to walls
PLUG = 16.0                     # gap under the tablet for a 90deg USB-C plug + cable running along the bottom
# Amazon photo (native landscape: home button bottom-centre, USB-C on the top long edge 25 mm from the right edge,
# power/vol on the right short edge from 18 mm below the top). Mounted rotated 180 deg so the USB-C faces DOWN:
# -> USB-C bottom edge near the viewer's left, buttons on the left short edge near the BOTTOM, home button top-centre.
BTN_FROM_BOTTOM = 18.0 + 4.0     # power button centre from the bottom edge once rotated
HOME_W, HOME_H = 22.0, 8.0       # notch in the frame for the home button (top bezel, centred) [MEASURE]
X_EXIT = 20.0                   # cable exit slot in the bottom wall (near the cap slot at x=+15)
FOAM, BAG = 1.5, 0.6            # foam pad behind tablet, freezer bag
WALL_S, WALL_TB, BACK, FRONT = 4.0, 8.0, 3.0, 3.0
WIN_M = 2.0                     # window larger than active area

# ---- power bank Goodmans 10000 mAh (measured) ----
PB_L, PB_W, PB_T = 145.0, 75.0, 16.0
PB_CLR = 2.0
PLUG_SP = 29.0                  # room under the (inverted) ports for plugs
MOD_W, MOD_SKIN = 120.0, 3.0
# USB-A output used (13 mm wide, its side 12 mm from the bank's edge -> centre 18 mm from the edge).
# Bank inserted so the USB-A is on the +x side (same side as the tablet's USB-C).
USB_A_X = PB_W / 2 - 18.0
USBA_PLUG_W, USBA_PLUG_T, USBA_PLUG_L = 17.0, 9.0, 36.0   # straight USB-A plug overmold + strain relief
# photo 1000041047.jpg: [USB-A Out | USB-C In/Out | USB-C Out]; In/Out ~1.5 mm off centre towards the C-Out side
USBC_IN_X = -1.5
SLOT_X = (USB_A_X, USBC_IN_X)    # cap slots: USB-A -> tablet, USB-C In/Out <- boat charging (pass-through to test)

VESA = 100.0
R_M3_INS, D_M3_INS = 2.05, 6.0
R_M4_INS, D_M4_INS = 2.8, 8.0


def box(x0, x1, y0, y1, z0, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def rbox(x0, x1, y0, y1, z0, z1, r):
    s = box(x0, x1, y0, y1, z0, z1)
    eds = [e for e in s.Edges if abs((e.Vertexes[1].Point - e.Vertexes[0].Point).normalize().y) > 0.99]
    return s.makeFillet(r, eds) if r > 0 else s


def cyl(r, h, p, d):
    return Part.makeCylinder(r, h, p, d)


def csk(x, y_face, z, d_out, r_hole=1.7, r_head=3.1, L=12):
    """countersunk clearance hole; head flush on face y_face, screw going in direction -d_out"""
    h =cyl(r_hole, L, V(x, y_face, z), V(0, -d_out, 0))
    cone = Part.makeCone(r_head, r_hole, r_head - r_hole, V(x, y_face, z), V(0, -d_out, 0))
    ext = cyl(r_head, 2, V(x, y_face, z), V(0, d_out, 0))
    return h.fuse(cone).fuse(ext)


# ---- derived ----
MOD_D = MOD_SKIN + PB_T + PB_CLR          # 21
Y_B0, Y_B1 = MOD_D, MOD_D + BACK          # body back wall
Y_T0 = Y_B1 + FOAM                        # tablet back
Y_T1 = Y_T0 + T_D + BAG                   # tablet+bag front
Y_RIM = Y_T1 + 0.5
Y_FR = Y_RIM + FRONT                      # box front face = total depth
PX = T_W / 2 + CLR                        # pocket half width
OX = PX + WALL_S
PZ = (T_H + CLR + PLUG) / 2               # pocket half height (box centred on VESA)
OZ = PZ + WALL_TB
XC = 0.0
ZC = (PLUG - CLR) / 2                     # tablet centre z
TX0, TX1 = XC - T_W / 2, XC + T_W / 2
X_PORT = TX1 - PORT_FROM_CORNER
Z_SCREW = PZ + WALL_TB / 2
FR_X = [-105.0, -40.0, 40.0, 105.0]
X_DRAIN = (-70.0, 80.0)
Z_BTN = ZC - T_H / 2 + BTN_FROM_BOTTOM    # buttons on the +x short edge (same end as the USB-C)
Y_BTN = Y_T0 + T_D / 2


def build():
    doc = App.newDocument("X35_TabletBox")
    parts = {}

    # ---------------- body (one piece, 247 wide) ----------------
    body = rbox(-OX, OX, Y_B0, Y_RIM, -OZ, OZ, 6)
    body = body.cut(rbox(-PX, PX, Y_B1, Y_FR + 5, -PZ, PZ, T_R + CLR))
    body = body.cut(box(X_EXIT - 2.75, X_EXIT + 2.75, Y_B1, Y_FR + 5, -OZ - 1, -PZ + 0.1))   # cable exit, faces down, closed by the frame
    for xd in X_DRAIN:
        body = body.cut(cyl(2.0, 20, V(xd, (Y_B1 + Y_RIM) / 2, -OZ - 1), V(0, 0, 1)))       # drain holes
    for x in FR_X:
        for z in (-Z_SCREW, Z_SCREW):
            body = body.cut(cyl(R_M3_INS, D_M3_INS, V(x, Y_RIM - D_M3_INS, z), V(0, 1, 0)))
    for x in (-VESA / 2, VESA / 2):
        for z in (-75.0, 75.0):
            body = body.cut(csk(x, Y_B1, z, 1, r_hole=2.25, r_head=4.4, L=8))   # M4 csk into pod
    body = body.cut(cyl(2.5, 10, V(PX - 1, Y_BTN, Z_BTN), V(1, 0, 0)))          # power-button plunger hole
    parts["Boite"] = body

    # power-button plunger, inserted from inside before the tablet (flange keeps it in)
    pl = cyl(2.2, OX + 2.5 - (TX1 + 0.4), V(TX1 + 0.4, Y_BTN, Z_BTN), V(1, 0, 0))
    pl = pl.fuse(cyl(3.8, 1.2, V(TX1 + 0.4, Y_BTN, Z_BTN), V(1, 0, 0)))
    parts["Poussoir"] = pl

    # ---------------- front frame (one piece) ----------------
    fr = rbox(-OX, OX, Y_RIM, Y_FR, -OZ, OZ, 6)
    fr = fr.cut(rbox(XC - ACT_W / 2 - WIN_M, XC + ACT_W / 2 + WIN_M, Y_RIM - 1, Y_FR + 1,
                     ZC - ACT_H / 2 - WIN_M, ZC + ACT_H / 2 + WIN_M, 3))
    fr = fr.cut(box(XC - HOME_W / 2, XC + HOME_W / 2, Y_RIM - 1, Y_FR + 1,
                    ZC + ACT_H / 2, ZC + T_H / 2 - 1.0))                 # home button notch
    for xd in X_DRAIN:                    # rain drains at the bottom of the window
        fr = fr.cut(box(xd - 5, xd + 5, Y_RIM - 1, Y_FR + 1, -OZ - 1, ZC - ACT_H / 2 - WIN_M + 1))
    for x in FR_X:
        for z in (-Z_SCREW, Z_SCREW):
            fr = fr.cut(csk(x, Y_FR, z, 1, L=8))
    parts["Cadre"] = fr

    # ---------------- power bank pod (splice plate + VESA interface) ----------------
    pw = PB_W / 2 + PB_CLR
    pod = rbox(-MOD_W / 2, MOD_W / 2, 0, MOD_D, -OZ, OZ, 6)
    pod = pod.cut(box(-pw, pw, MOD_SKIN, MOD_D + 1, -OZ - 1, OZ - 3))      # open to body side and downwards
    for x in (-VESA / 2, VESA / 2):
        for z in (-VESA / 2, VESA / 2):
            pod = pod.cut(cyl(R_M4_INS, D_M4_INS, V(x, -0.01, z), V(0, 1, 0)))         # VESA 100 inserts
        for z in (-75.0, 75.0):
            pod = pod.cut(cyl(R_M4_INS, D_M4_INS, V(x, MOD_D - D_M4_INS, z), V(0, 1, 0)))  # body bolts
        pod = pod.cut(cyl(R_M3_INS, D_M3_INS, V(x, 7.0, -OZ - 0.01), V(0, 0, 1)))     # cap inserts
    parts["Module_powerbank"] = pod

    # ---------------- bottom cap (holds the inverted power bank, cables exit down) ----------------
    pb_bot = OZ - 3 - 1 - PB_L            # ports face of the power bank
    cap = rbox(-MOD_W / 2, MOD_W / 2, 0, MOD_D, -OZ - 4, -OZ, 1.5)
    for x0, x1 in ((-PB_W / 2, -PB_W / 2 + 5), (PB_W / 2 - 5, PB_W / 2)):   # posts under the bank's ends (USB-A sits 12 mm in)
        cap = cap.fuse(box(x0, x1, MOD_SKIN + 2, MOD_D - 2, -OZ - 1, pb_bot))
    for xc in SLOT_X:
        cap = cap.cut(box(xc - 3.5, xc + 3.5, 7.0, MOD_D + 1, -OZ - 5, -OZ + 1))   # cable slots, open towards the box
    for x in (-VESA / 2, VESA / 2):
        h = cyl(1.7, 10, V(x, 7.0, -OZ - 4.1), V(0, 0, 1))
        h = h.fuse(Part.makeCone(3.1, 1.7, 1.4, V(x, 7.0, -OZ - 4.01), V(0, 0, 1)))
        cap = cap.cut(h)
    parts["Bouchon"] = cap.removeSplitter()

    # ---------------- dummies ----------------
    dummies = {
        "Tablette": rbox(TX0, TX1, Y_T0, Y_T0 + T_D, ZC - T_H / 2, ZC + T_H / 2, T_R),
        "Ecran_actif": box(XC - ACT_W / 2, XC + ACT_W / 2, Y_T0 + T_D, Y_T0 + T_D + 0.2, ZC - ACT_H / 2, ZC + ACT_H / 2),
        "Powerbank": rbox(-PB_W / 2, PB_W / 2, MOD_SKIN + 1, MOD_SKIN + 1 + PB_T, pb_bot, pb_bot + PB_L, 4),
        "Fiche_USBA_powerbank": box(USB_A_X - USBA_PLUG_W / 2, USB_A_X + USBA_PLUG_W / 2,
                                    MOD_SKIN + 1 + PB_T / 2 - USBA_PLUG_T / 2, MOD_SKIN + 1 + PB_T / 2 + USBA_PLUG_T / 2,
                                    pb_bot - USBA_PLUG_L, pb_bot),
        "Fiche_USBC_entree_pb": box(USBC_IN_X - 6, USBC_IN_X + 6, MOD_SKIN + 1 + PB_T / 2 - 3.5, MOD_SKIN + 1 + PB_T / 2 + 3.5,
                                    pb_bot - 30, pb_bot),
        "Fiche_USBC_tablette": box(X_PORT - 6, X_PORT + 6, Y_T0 + 1, Y_T0 + T_D - 1, ZC - T_H / 2 - 13, ZC - T_H / 2),
    }

    printed = doc.addObject("App::DocumentObjectGroup", "Pieces_imprimees")
    ref = doc.addObject("App::DocumentObjectGroup", "Reference")
    for n, sh in parts.items():
        o = doc.addObject("Part::Feature", n); o.Shape = sh; printed.addObject(o)
    for n, sh in dummies.items():
        o = doc.addObject("Part::Feature", n); o.Shape = sh; ref.addObject(o)
    doc.recompute()

    # ---------------- checks ----------------
    rep = {}
    allp = list(parts.items()) + list(dummies.items())
    hits = []
    for i in range(len(allp)):
        for j in range(i + 1, len(allp)):
            a, b = allp[i], allp[j]
            if a[0] == "Ecran_actif" or b[0] == "Ecran_actif":
                continue
            v = a[1].common(b[1]).Volume
            if v > 0.5:
                hits.append((a[0], b[0], round(v, 1)))
    rep["hits"] = hits
    fits = {}
    for n, sh in parts.items():
        bb = sh.BoundBox
        dims = sorted([bb.XLength, bb.YLength, bb.ZLength])
        fits[n] = ([round(d, 1) for d in (bb.XLength, bb.YLength, bb.ZLength)], dims[1] <= BED - 6 and dims[2] <= BED - 6)
    rep["fits_A1"] = fits
    rep["box_outer_WxHxD"] = (round(2 * OX, 1), round(OZ + 4 + OZ, 1), round(Y_FR, 1))
    rep["tablet_frame_overlap_x"] = (round(XC - ACT_W / 2 - WIN_M - TX0, 1), round(TX1 - (XC + ACT_W / 2 + WIN_M), 1))
    rep["tablet_frame_overlap_z"] = round(T_H / 2 - ACT_H / 2 - WIN_M, 1)
    rep["usbc_port_x"] = X_PORT
    rep["usbA_x"] = USB_A_X
    rep["room_under_bank_to_cap_mm"] = round(pb_bot - (-OZ), 1)
    rep["volume_cm3"] = {n: round(sh.Volume / 1000, 1) for n, sh in parts.items()}
    return doc, parts, rep


doc, parts, rep = build()
for k, v in rep.items():
    print(k, "=", v)
