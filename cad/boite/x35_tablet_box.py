# X35 tablet box (10.1" Feonal/Zonko K116) + power bank pod, for the X35 swivel mount.
# Printer: Bambu Lab A1 (256^3). Material: PETG. Seals: EPDM foam tape / bike inner tube.
# Local frame: x = width (same as mount x), y = 0 on the VESA face (back), +y towards the
# screen/helmsman, z = up, (0,0,0) = VESA centre = box centre. Units mm.
import os
import math
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
PORT_FROM_CORNER = 30.0         # USB-C centre from the button corner of the tablet (measured 30 mm)
CLR = 2.0                       # clearance tablet-in-bag to walls
PLUG = 16.0                     # gap under the tablet for a 90deg USB-C plug + cable running along the bottom
# Amazon photo (native landscape: home button bottom-centre, USB-C on the top long edge 25 mm from the right edge,
# power/vol on the right short edge from 18 mm below the top). Mounted rotated 180 deg so the USB-C faces DOWN:
# -> USB-C bottom edge near the viewer's left, buttons on the left short edge near the BOTTOM, home button top-centre.
BTN_FROM_BOTTOM = 25.0          # power button centre from the bottom (USB-C) edge once rotated (measured)
# Volume + power buttons stand PROUD of the tablet edge (measured 2.8 mm) over 10.5..46.5 mm from the
# bottom edge. The box is widened on the +x (button) side only and the +x wall is relieved over that
# zone (+ margin), so a tablet sliding against the wall at heel lands on its edge, never on a button.
BTN_PROUD = 2.8
BTN_Z0, BTN_Z1, BTN_MARGIN = 10.5, 46.5, 5.0
X_PLUS = 3.0                    # extra width on the +x side only (250 = A1 bed check limit; YA of the mount unchanged up to 4)
REL_DEPTH = 4.5                 # wall relief beyond the pocket over the button zone (wall left there: WALL_S + X_PLUS - REL_DEPTH)
HOME_W, HOME_H = 22.0, 8.0       # notch in the frame for the home button (top bezel, centred) [MEASURE]
X_EXIT = None                   # cable exit slot in the bottom wall: right under the USB-C port (X_PORT, set below)
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
# captive hex nuts (no heat-set inserts): bore radius, nut pocket width (across flats + 0.4), pocket height, wall above nut
R_M3, N3_W, N3_T = 1.7, 5.9, 2.6
R_M4, N4_W, N4_T = 2.25, 7.4, 3.6
N_WALL = 3.5


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


def nut_slot_x(x, pw, y0, y1, z, w):
    """nut pocket at (x, z) between y0..y1, slid in along x from the bank cavity (|x| < pw)"""
    xo, xi = math.copysign(abs(x) + w / 2 + 0.5, x), math.copysign(pw - 1.0, x)
    return box(min(xo, xi), max(xo, xi), y0, y1, z - w / 2, z + w / 2)


# ---- derived ----
MOD_D = MOD_SKIN + PB_T + PB_CLR          # 21
Y_B0, Y_B1 = MOD_D, MOD_D + BACK          # body back wall
Y_T0 = Y_B1 + FOAM                        # tablet back
Y_T1 = Y_T0 + T_D + BAG                   # tablet+bag front
Y_RIM = Y_T1 + 0.5
Y_FR = Y_RIM + FRONT                      # box front face = total depth
PX = T_W / 2 + CLR                        # pocket half width
OX = PX + WALL_S
OXP = OX + X_PLUS                         # +x outer face (box is 2*OX + X_PLUS wide)
REL_X = PX + REL_DEPTH                    # +x wall inner face over the button zone
PZ = (T_H + CLR + PLUG) / 2               # pocket half height (box centred on VESA)
OZ = PZ + WALL_TB
XC = 0.0
ZC = (PLUG - CLR) / 2                     # tablet centre z
TX0, TX1 = XC - T_W / 2, XC + T_W / 2
X_PORT = TX1 - PORT_FROM_CORNER
X_EXIT = X_PORT
Z_SCREW = PZ + WALL_TB / 2
FR_X = [-105.0, -40.0, 40.0, 105.0]
X_DRAIN = (-70.0, 70.0)          # +x drain moved off the cable exit (frame notch xd+-5 must clear it)
Z_BTN = ZC - T_H / 2 + BTN_FROM_BOTTOM    # buttons on the +x short edge (same end as the USB-C)
Y_BTN = Y_T0 + T_D / 2


def build():
    doc = App.newDocument("X35_TabletBox")
    parts = {}

    # ---------------- body (one piece, 247 wide) ----------------
    body = rbox(-OX, OXP, Y_B0, Y_RIM, -OZ, OZ, 6)
    body = body.cut(rbox(-PX, PX, Y_B1, Y_FR + 5, -PZ, PZ, T_R + CLR))
    zb = ZC - T_H / 2                                                            # tablet bottom edge
    body = body.cut(box(PX - 1, REL_X, Y_B1, Y_FR + 5,
                        zb + BTN_Z0 - BTN_MARGIN, zb + BTN_Z1 + BTN_MARGIN))       # relief for the proud buttons
    body = body.cut(box(X_EXIT - 2.75, X_EXIT + 2.75, Y_B1, Y_FR + 5, -OZ - 1, -PZ + 0.1))   # cable exit, faces down, closed by the frame
    for xd in X_DRAIN:
        body = body.cut(cyl(2.0, 20, V(xd, (Y_B1 + Y_RIM) / 2, -OZ - 1), V(0, 0, 1)))       # drain holes
    for x in FR_X:
        for z in (-Z_SCREW, Z_SCREW):
            body = body.cut(cyl(R_M3, 9.0, V(x, Y_RIM - 9.0, z), V(0, 1, 0)))          # M3 bore, frame screws
            zo, zi = math.copysign(Z_SCREW + 3.35, z), math.copysign(PZ - 1.0, z)
            body = body.cut(box(x - N3_W / 2, x + N3_W / 2, Y_RIM - N_WALL - N3_T, Y_RIM - N_WALL,
                                min(zo, zi), max(zo, zi)))                              # M3 nut slot, opens into the tablet pocket
    for x in (-VESA / 2, VESA / 2):
        for z in (-75.0, 75.0):
            body = body.cut(csk(x, Y_B1, z, 1, r_hole=2.25, r_head=4.4, L=8))   # M4 csk into pod
    body = body.cut(cyl(2.5, 10, V(REL_X - 1, Y_BTN, Z_BTN), V(1, 0, 0)))       # power-button plunger hole
    parts["Boite"] = body

    # power-button plunger, inserted from inside before the tablet (flange keeps it in)
    x_pl = TX1 + BTN_PROUD + 0.4                                                # 0.4 mm off the proud button
    pl = cyl(2.2, OXP + 2.5 - x_pl, V(x_pl, Y_BTN, Z_BTN), V(1, 0, 0))
    pl = pl.fuse(cyl(3.8, 1.0, V(x_pl, Y_BTN, Z_BTN), V(1, 0, 0)))
    parts["Poussoir"] = pl

    # ---------------- front frame (one piece) ----------------
    fr = rbox(-OX, OXP, Y_RIM, Y_FR, -OZ, OZ, 6)
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
            pod = pod.cut(cyl(R_M4, 12.0, V(x, -0.01, z), V(0, 1, 0)))                # VESA 100 bore
            pod = pod.cut(nut_slot_x(x, pw, N_WALL, N_WALL + N4_T, z, N4_W))          # M4 nut, opens into the bank cavity
        for z in (-75.0, 75.0):
            pod = pod.cut(cyl(R_M4, 10.0, V(x, MOD_D - 10.0, z), V(0, 1, 0)))         # body bolt bore
            pod = pod.cut(nut_slot_x(x, pw, MOD_D - N_WALL - N4_T, MOD_D - N_WALL, z, N4_W))
        pod = pod.cut(cyl(R_M3, 10.0, V(x, 7.0, -OZ - 0.01), V(0, 0, 1)))             # cap screw bore
        xo, xi = math.copysign(abs(x) + N3_W / 2 + 0.5, x), math.copysign(pw - 1.0, x)
        pod = pod.cut(box(min(xo, xi), max(xo, xi), 7.0 - N3_W / 2, 7.0 + N3_W / 2,
                          -OZ + N_WALL, -OZ + N_WALL + N3_T))                         # M3 nut slot, opens into the bank cavity
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
    rep["box_outer_x"] = (round(-OX, 1), round(OXP, 1))
    # tablet pushed fully to +x (edge on the wall outside the relief): flange outer face vs relief wall
    rep["button_to_relief_wall_at_heel"] = round(REL_X - (PX + BTN_PROUD), 2)      # tablet pushed fully to +x
    rep["plunger_flange_to_wall_at_heel"] = round(REL_X - (PX + BTN_PROUD + 1.0), 2)  # flange pushed out by the button
    rep["box_outer_WxHxD"] = (round(OX + OXP, 1), round(OZ + 4 + OZ, 1), round(Y_FR, 1))
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
